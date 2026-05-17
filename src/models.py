"""
APS 排程系统业务实体定义模块

定义生产订单和吹膜机台的内存结构模型。
所有时间字段均为距离基准时间的纯整数分钟偏移量。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class ProductionOrderModel:
    """生产订单内存规范模型类"""

    # 订单基本信息
    order_id: str
    product_type: str

    # 物理规格
    target_width: int          # mm
    target_thickness: int      # um
    total_quantity_kg: int     # kg

    # 洁净度与合规
    cleanroom_req: str         # Class_10K / Class_100K
    customer_class: str        # VIP / STANDARD
    order_class: str           # URGENT / NORMAL / SAMPLE
    corona_req: bool           # 电晕处理需求
    core_size_inch: int        # 卷芯管径（英寸）

    # 时间字段（整数分钟偏移量）
    order_date_mins: int = 0
    due_date_mins: int = 0
    material_available_mins: int = 0    # 原料齐套时点

    # 运行时注入的配方信息
    recipe_materials: List[str] = field(default_factory=list)

    # 排程结果（求解后填充）
    assigned_machine_id: Optional[str] = None
    scheduled_start_mins: Optional[int] = None
    scheduled_end_mins: Optional[int] = None
    scrap_weight_kg: float = 0.0
    actual_material_required_kg: float = 0.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProductionOrderModel":
        """从清洗后的字典构造订单模型"""
        return cls(
            order_id=str(d["orderId"]),
            product_type=str(d["productType"]),
            target_width=int(d["targetWidth"]),
            target_thickness=int(d["targetThickness"]),
            total_quantity_kg=int(d["totalQuantityKg"]),
            cleanroom_req=str(d["cleanroomReq"]),
            customer_class=str(d["customerClass"]),
            order_class=str(d["orderClass"]),
            corona_req=(str(d["coronaReq"]).upper() == "YES"),
            core_size_inch=int(d["coreSizeInch"]),
            order_date_mins=int(d.get("orderDateMins", 0)),
            due_date_mins=int(d.get("dueDateMins", 0)),
            material_available_mins=int(d.get("materialAvailableMins", 0)),
            recipe_materials=list(d.get("recipeMaterialsSequence", [])),
        )


@dataclass
class ForbiddenWindow:
    """禁排时间窗口"""
    start_mins: int
    end_mins: int
    reason: str


@dataclass
class BlownFilmMachineModel:
    """吹膜设备资源内存规范模型类"""

    # 基本信息
    machine_id: str
    name: str
    cleanroom_level: str       # Class_10K / Class_100K

    # 能力参数
    layer_structure: int       # 层数（3 / 5）
    die_diameter_mm: int       # 模头口径 mm
    min_width: int             # mm
    max_width: int             # mm
    min_thickness: int         # um
    max_thickness: int         # um
    hourly_output_kg: int      # 每小时标准产量 kg
    max_slitting_lanes: int    # 最大分切轴数

    # 初始状态
    initial_material_lanes: List[str] = field(default_factory=list)  # 广播后的多螺杆挂料数组
    initial_width: int = 0     # mm
    initial_thickness: int = 0 # um

    # 合规约束
    forbidden_calendar: List[ForbiddenWindow] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BlownFilmMachineModel":
        """从清洗后的字典构造机台模型"""
        # 解析禁排日历
        calendar = []
        for fw in d.get("forbiddenCalendar", []):
            calendar.append(ForbiddenWindow(
                start_mins=int(fw["startMins"]),
                end_mins=int(fw["endMins"]),
                reason=str(fw["reason"]),
            ))

        return cls(
            machine_id=str(d["machineId"]),
            name=str(d["name"]),
            cleanroom_level=str(d["cleanroomLevel"]),
            layer_structure=int(d["layerStructure"]),
            die_diameter_mm=int(d["dieDiameterMm"]),
            min_width=int(d["minWidth"]),
            max_width=int(d["maxWidth"]),
            min_thickness=int(d["minThickness"]),
            max_thickness=int(d["maxThickness"]),
            hourly_output_kg=int(d["hourlyOutputKg"]),
            max_slitting_lanes=int(d["maxSlittingLanes"]),
            initial_material_lanes=list(d.get("initialMaterialLanes", [])),
            initial_width=int(d.get("initialWidth", 0)),
            initial_thickness=int(d.get("initialThickness", 0)),
            forbidden_calendar=calendar,
        )

    def can_produce(self, order: ProductionOrderModel) -> bool:
        """检查此机台是否具备生产指定订单的能力（硬拦截）"""
        # 洁净度级联：Class_10K 订单不能上 Class_100K 机台
        if order.cleanroom_req == "Class_10K" and self.cleanroom_level == "Class_100K":
            return False
        # 幅宽能力边界
        if order.target_width < self.min_width or order.target_width > self.max_width:
            return False
        # 厚度能力边界
        if order.target_thickness < self.min_thickness or order.target_thickness > self.max_thickness:
            return False
        # 配方层数不能超过机台层数
        if len(order.recipe_materials) > self.layer_structure:
            return False
        return True

    def calculate_duration(self, order: ProductionOrderModel) -> int:
        """计算订单在此机台上的生产耗时（分钟），向上进位整算"""
        # 无损除法向上进位：(A * 60 + B - 1) // B
        return (order.total_quantity_kg * 60 + self.hourly_output_kg - 1) // self.hourly_output_kg
