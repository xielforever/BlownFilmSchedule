"""
APS 排程系统数据清洗与转换管道

基于 Pandas 读取 Excel 多 Sheet，执行防御性数据清洗、
配方按层重组、时钟基准换算、维保日历注入，
最终输出标准化的业务模型对象列表。
"""

from __future__ import annotations
import datetime
import logging
from typing import List, Dict, Tuple, Any

import pandas as pd

from src.config import BASELINE_TIME, FORBIDDEN_CALENDAR_RULES
from src.models import ProductionOrderModel, BlownFilmMachineModel
from src.setup_matrices import SetupMatricesManager

logger = logging.getLogger(__name__)


class BlownFilmDataIngestionPipeline:
    """数据清洗与转换管道"""

    def __init__(self, baseline_str: str = BASELINE_TIME):
        self.baseline_time = datetime.datetime.strptime(baseline_str, "%Y-%m-%d %H:%M")

    def _parse_time_to_mins(self, datetime_val) -> int:
        """无损将 DateTime 转化为距离基准线的纯整数分钟偏移量"""
        if pd.isna(datetime_val):
            return 0
        if isinstance(datetime_val, str):
            dt = datetime.datetime.strptime(datetime_val.strip(), "%Y-%m-%d %H:%M")
        elif isinstance(datetime_val, pd.Timestamp):
            dt = datetime_val.to_pydatetime()
        elif isinstance(datetime_val, datetime.datetime):
            dt = datetime_val
        else:
            return 0
        return int((dt - self.baseline_time).total_seconds() / 60)

    def load_from_excel(self, excel_path: str) -> Tuple[
        List[BlownFilmMachineModel],
        List[ProductionOrderModel],
        Dict[str, List[str]],
        SetupMatricesManager,
    ]:
        """
        从 Excel 文件加载所有数据并返回清洗后的业务对象。

        Returns:
            machines: 机台模型列表
            orders: 订单模型列表
            recipes_map: 产品类型 → 有序原料牌号数组
            setup_mgr: 换产矩阵管理器
        """
        xls = pd.ExcelFile(excel_path)
        sheet_names = xls.sheet_names
        logger.info("Excel Sheets: %s", sheet_names)

        # 按 Sheet 索引加载（Sheet 名称可能包含中文编码差异）
        # Sheet 0: 封面/公式页（跳过）
        # Sheet 1: 订单表
        # Sheet 2: 工艺配方表
        # Sheet 3: 吹膜机设备表
        # Sheet 4: 原料切换矩阵
        # Sheet 5: 规格调机矩阵
        # Sheet 6: 医疗级清场矩阵
        df_orders = pd.read_excel(excel_path, sheet_name=1)
        df_recipes = pd.read_excel(excel_path, sheet_name=2)
        df_machines = pd.read_excel(excel_path, sheet_name=3)
        df_material_trans = pd.read_excel(excel_path, sheet_name=4)
        df_physical = pd.read_excel(excel_path, sheet_name=5)
        df_medical = pd.read_excel(excel_path, sheet_name=6)

        # 1. 解析工艺配方
        recipes_map = self._parse_recipes(df_recipes)

        # 2. 解析换产矩阵
        setup_mgr = SetupMatricesManager()
        setup_mgr.load_from_dataframes(df_material_trans, df_physical, df_medical)

        # 3. 解析机台
        machines = self._parse_machines(df_machines)

        # 4. 解析订单
        orders = self._parse_orders(df_orders, recipes_map)

        logger.info("数据加载完成: %d 台机台, %d 笔订单, %d 种配方",
                     len(machines), len(orders), len(recipes_map))

        return machines, orders, recipes_map, setup_mgr

    def _parse_recipes(self, df: pd.DataFrame) -> Dict[str, List[str]]:
        """将多行平铺的配方表重组为以产品类型为主键的有序原料数组"""
        col_product = df.columns[1]   # 关联产品类型 (productType)
        col_layer = df.columns[3]     # 目标层级 (layer)
        col_material = df.columns[4]  # 原料牌号 (materialGrade)

        # 按产品类型与层级字母升序排序
        df_sorted = df.sort_values(by=[col_product, col_layer])

        recipes_map: Dict[str, List[str]] = {}
        for prod_type, group in df_sorted.groupby(col_product):
            prod_type_str = str(prod_type).strip()
            materials = [str(m).strip() for m in group[col_material].tolist()]
            recipes_map[prod_type_str] = materials

        logger.info("配方解析完成: %s", {k: v for k, v in recipes_map.items()})
        return recipes_map

    def _parse_machines(self, df: pd.DataFrame) -> List[BlownFilmMachineModel]:
        """解析吹膜机设备表，执行初始挂料广播与维保日历注入"""
        machines = []

        for _, row in df.iterrows():
            # 提取层数
            layer_str = str(row[df.columns[3]]).strip()  # 层级结构 (layerStructure)
            layer_num = int(layer_str.replace("层共挤", "").strip())

            # 初始挂料广播
            initial_mat = str(row[df.columns[11]]).strip()  # 初始挂料牌号
            broadcasted = [initial_mat] * layer_num

            # 构建维保日历
            forbidden = []
            for rule in FORBIDDEN_CALENDAR_RULES:
                forbidden.append({
                    "startMins": rule["startMins"],
                    "endMins": rule["endMins"],
                    "reason": rule["reason"],
                })

            machine_dict = {
                "machineId": str(row[df.columns[0]]).strip(),
                "name": str(row[df.columns[1]]).strip(),
                "cleanroomLevel": str(row[df.columns[2]]).strip(),
                "layerStructure": layer_num,
                "dieDiameterMm": int(row[df.columns[4]]),
                "minWidth": int(row[df.columns[5]]),
                "maxWidth": int(row[df.columns[6]]),
                "minThickness": int(row[df.columns[7]]),
                "maxThickness": int(row[df.columns[8]]),
                "hourlyOutputKg": int(row[df.columns[9]]),
                "maxSlittingLanes": int(row[df.columns[10]]),
                "initialMaterialLanes": broadcasted,
                "initialWidth": int(row[df.columns[12]]),
                "initialThickness": int(row[df.columns[13]]),
                "forbiddenCalendar": forbidden,
            }
            machines.append(BlownFilmMachineModel.from_dict(machine_dict))

        return machines

    def _parse_orders(
        self,
        df: pd.DataFrame,
        recipes_map: Dict[str, List[str]],
    ) -> List[ProductionOrderModel]:
        """解析订单表，执行时钟换算、到货期防御补丁、配方挂载"""
        orders = []

        for _, row in df.iterrows():
            prod_type = str(row[df.columns[1]]).strip()

            # 配方挂载：从配方表关联，缺失时安全降级
            recipe_materials = recipes_map.get(prod_type, ["Standard_Med_LDPE"])

            # 时钟换算
            order_date_mins = self._parse_time_to_mins(row[df.columns[6]])
            due_date_mins = self._parse_time_to_mins(row[df.columns[7]])

            # 到货期防御补丁
            mat_avail = 0
            if len(df.columns) > 12:
                val = row[df.columns[12]]
                if pd.notna(val):
                    mat_avail = int(val)

            order_dict = {
                "orderId": str(row[df.columns[0]]).strip(),
                "productType": prod_type,
                "targetWidth": int(row[df.columns[2]]),
                "targetThickness": int(row[df.columns[3]]),
                "totalQuantityKg": int(row[df.columns[4]]),
                "cleanroomReq": str(row[df.columns[5]]).strip(),
                "customerClass": str(row[df.columns[8]]).strip(),
                "orderClass": str(row[df.columns[9]]).strip(),
                "coronaReq": str(row[df.columns[10]]).strip(),
                "coreSizeInch": int(row[df.columns[11]]),
                "orderDateMins": order_date_mins,
                "dueDateMins": due_date_mins,
                "materialAvailableMins": mat_avail,
                "recipeMaterialsSequence": recipe_materials,
            }
            orders.append(ProductionOrderModel.from_dict(order_dict))

        return orders
