"""
APS 排程系统换产矩阵数据驱动管理器

从 Excel 中解析四张换产规则矩阵表，提供标准化查表接口。
彻底替代硬编码的换产时间值，提升系统可维护性和可配置性。
"""

from __future__ import annotations
import re
import logging
from typing import Dict, List, Tuple, Optional, Any

from src.config import DEFAULT_MATERIAL_SWITCH_TIME_MINS

logger = logging.getLogger(__name__)


class SetupMatricesManager:
    """换产矩阵数据驱动管理器"""

    def __init__(self):
        # 原料切换矩阵: (from_material, to_material) -> mins
        self.material_switch_matrix: Dict[Tuple[str, str], int] = {}
        self.material_switch_scrap_matrix: Dict[Tuple[str, str], float] = {}
        # 同料换批次耗时
        self.same_material_time: int = 30
        self.same_material_scrap_kg: Optional[float] = None
        # 涉及 Special_Co-PE 的特殊换产
        self.special_to_any_time: int = 150
        self.any_to_special_time: int = 120
        self.special_to_any_scrap_kg: Optional[float] = None
        self.any_to_special_scrap_kg: Optional[float] = None

        # 规格调机矩阵: list of rules
        self.width_up_rules: List[Tuple[int, int]] = []    # (threshold, mins)
        self.width_down_rules: List[Tuple[int, int]] = []   # (threshold, mins)
        self.width_up_scrap_rules: List[Tuple[int, Optional[float]]] = []
        self.width_down_scrap_rules: List[Tuple[int, Optional[float]]] = []
        self.die_change_time: int = 360
        self.die_change_scrap_kg: Optional[float] = None
        self.thickness_rules: List[Tuple[int, int]] = []    # (threshold, mins)
        self.thickness_scrap_rules: List[Tuple[int, Optional[float]]] = []
        self.corona_switch_time: int = 20
        self.corona_switch_scrap_kg: Optional[float] = None
        self.core_size_switch_time: int = 30
        self.core_size_switch_scrap_kg: Optional[float] = None

        # GMP 合规清场矩阵: (from_class, to_class) -> mins
        self.gmp_clearance_matrix: Dict[Tuple[str, str], int] = {}

        # 72h 强制停机清场耗时
        self.continuous_run_cleaning_time: int = 90
        self.missing_material_switch_fallback_mins: int = DEFAULT_MATERIAL_SWITCH_TIME_MINS
        self.scrap_defaults_enabled: bool = True

        # 本轮求解观测：缺失的材料切换规则。求解器会高频查询换产矩阵，
        # 因此缺失规则只记录一次 warning，并在排程结果里汇总诊断。
        self.missing_material_switch_pairs: Dict[Tuple[str, str], int] = {}
        self._warned_missing_material_switches = set()

    @classmethod
    def empty_rules(cls) -> "SetupMatricesManager":
        """Create a setup manager whose rules contribute no hidden time or scrap."""
        mgr = cls()
        mgr.material_switch_matrix = {}
        mgr.material_switch_scrap_matrix = {}
        mgr.same_material_time = 0
        mgr.same_material_scrap_kg = 0.0
        mgr.special_to_any_time = 0
        mgr.any_to_special_time = 0
        mgr.special_to_any_scrap_kg = 0.0
        mgr.any_to_special_scrap_kg = 0.0
        mgr.width_up_rules = []
        mgr.width_down_rules = []
        mgr.width_up_scrap_rules = []
        mgr.width_down_scrap_rules = []
        mgr.die_change_time = 0
        mgr.die_change_scrap_kg = 0.0
        mgr.thickness_rules = []
        mgr.thickness_scrap_rules = []
        mgr.corona_switch_time = 0
        mgr.corona_switch_scrap_kg = 0.0
        mgr.core_size_switch_time = 0
        mgr.core_size_switch_scrap_kg = 0.0
        mgr.gmp_clearance_matrix = {}
        mgr.continuous_run_cleaning_time = 0
        mgr.missing_material_switch_fallback_mins = 0
        mgr.scrap_defaults_enabled = False
        return mgr

    def reset_runtime_observations(self) -> None:
        """清空本轮求解期间收集的运行时观测。"""
        self.missing_material_switch_pairs.clear()
        self._warned_missing_material_switches.clear()

    def load_from_dataframes(
        self,
        df_material: Any,
        df_physical: Any,
        df_medical: Any,
    ) -> None:
        """从 Pandas DataFrame 加载所有换产矩阵"""
        self._load_material_matrix(df_material)
        self._load_physical_matrix(df_physical)
        self._load_medical_matrix(df_medical)
        logger.info("换产矩阵加载完成: 原料组合=%d, 规格规则=%d, GMP清场规则=%d",
                     len(self.material_switch_matrix),
                     len(self.width_up_rules) + len(self.width_down_rules) + len(self.thickness_rules),
                     len(self.gmp_clearance_matrix))

    def _load_material_matrix(self, df: Any) -> None:
        """解析原料切换矩阵 Sheet"""
        col_from = df.columns[0]   # 前序原料牌号 (fromMaterial)
        col_to = df.columns[1]     # 后续原料牌号 (toMaterial)
        col_mins = df.columns[2]   # 洗机切换耗时 (mins)

        for _, row in df.iterrows():
            from_mat = str(row[col_from]).strip()
            to_mat = str(row[col_to]).strip()
            mins = int(row[col_mins])

            # 处理特殊通配符
            if "Same" in from_mat and "Same" in to_mat:
                self.same_material_time = mins
            elif "Special_Co-PE" in from_mat and ("Any" in to_mat or "任何" in to_mat):
                self.special_to_any_time = mins
            elif ("Any" in from_mat or "任何" in from_mat) and "Special_Co-PE" in to_mat:
                self.any_to_special_time = mins
            else:
                self.material_switch_matrix[(from_mat, to_mat)] = mins

    def _load_physical_matrix(self, df: Any) -> None:
        """解析规格与调机时间矩阵 Sheet"""
        col_attr = df.columns[0]       # 属性维度 (attribute)
        col_condition = df.columns[1]  # 变动条件边界 (condition)
        col_mins = df.columns[2]       # 调试耗时 (mins)

        for _, row in df.iterrows():
            attr = str(row[col_attr]).strip()
            condition = str(row[col_condition]).strip()
            mins = int(row[col_mins])

            if "Width_Up" in attr:
                threshold = self._parse_threshold(condition)
                self.width_up_rules.append((threshold, mins))
                self.width_up_scrap_rules.append((threshold, None))
            elif "Width_Down" in attr:
                threshold = self._parse_threshold(condition)
                self.width_down_rules.append((threshold, mins))
                self.width_down_scrap_rules.append((threshold, None))
            elif "Die_Change" in attr:
                self.die_change_time = mins
            elif "Thickness" in attr:
                threshold = self._parse_threshold(condition)
                self.thickness_rules.append((threshold, mins))
                self.thickness_scrap_rules.append((threshold, None))
            elif "Corona" in attr:
                self.corona_switch_time = mins
            elif "Core_Size" in attr:
                self.core_size_switch_time = mins

        # 按阈值升序排列（用于阶梯查表）
        self.width_up_rules.sort(key=lambda x: x[0])
        self.width_down_rules.sort(key=lambda x: x[0])
        self.thickness_rules.sort(key=lambda x: x[0])
        self.width_up_scrap_rules.sort(key=lambda x: x[0])
        self.width_down_scrap_rules.sort(key=lambda x: x[0])
        self.thickness_scrap_rules.sort(key=lambda x: x[0])

    def _load_medical_matrix(self, df: Any) -> None:
        """解析医疗级清场验证矩阵 Sheet"""
        col_from = df.columns[0]   # 前序工单特征 (fromOrderClass)
        col_to = df.columns[1]     # 后续工单特征 (toOrderClass)
        col_mins = df.columns[2]   # 验证清场耗时 (mins)

        for _, row in df.iterrows():
            from_class = str(row[col_from]).strip()
            to_class = str(row[col_to]).strip()
            mins = int(row[col_mins])

            # 解析含有中文标注的分类标识
            from_key = self._extract_order_class(from_class)
            to_key = self._extract_order_class(to_class)

            if from_key == "CONTINUOUS_RUN":
                self.continuous_run_cleaning_time = mins
            else:
                self.gmp_clearance_matrix[(from_key, to_key)] = mins

    @staticmethod
    def _parse_threshold(condition: str) -> int:
        """从条件描述中提取数字阈值，用于阶梯规则排序"""
        # 匹配 "≤ 50mm", "51mm - 200mm", "> 200mm", "≤ 10um", "> 10um" 等
        numbers = re.findall(r'(\d+)', condition)
        if not numbers:
            return 999999  # 无限大，兜底
        if '>' in condition and '≤' not in condition:
            # "> 200mm" 类型 → 阈值是 200（取最后一个数字）
            return int(numbers[-1])
        # "≤ 50mm" 或 "51mm - 200mm" 类型 → 取最后一个数字作为上界
        return int(numbers[-1])

    @staticmethod
    def _extract_order_class(raw: str) -> str:
        """从含中文标注的字符串中提取纯英文分类标识"""
        if "Continuous_Run" in raw or "持续开机" in raw:
            return "CONTINUOUS_RUN"
        if "NORMAL" in raw:
            return "NORMAL"
        if "URGENT" in raw:
            return "URGENT"
        if "SAMPLE" in raw:
            return "SAMPLE"
        if "ANY" in raw or "任何" in raw:
            return "ANY"
        return raw

    @staticmethod
    def _match_threshold_rule(
        rules: List[Tuple[int, Optional[float]]],
        delta: int,
    ) -> Optional[float]:
        if delta == 0:
            return 0.0
        if not rules:
            return None
        abs_delta = abs(delta)
        for threshold, value in rules:
            if abs_delta <= threshold:
                return value
        return rules[-1][1]

    def iter_spec_rules(self) -> List[Dict[str, Any]]:
        """按数据库/API字段导出当前规格换产规则。"""
        rows: List[Dict[str, Any]] = []

        def append_threshold_rules(attribute: str, rules, scrap_rules, unit: str) -> None:
            for idx, (threshold, mins) in enumerate(rules):
                prev_threshold = rules[idx - 1][0] if idx else None
                is_last = idx == len(rules) - 1
                if idx == 0:
                    condition_desc = f"<= {threshold}{unit}"
                    lower = 0
                    upper = threshold
                elif is_last:
                    condition_desc = f"> {prev_threshold}{unit}"
                    lower = prev_threshold + 1 if prev_threshold is not None else threshold
                    upper = None
                else:
                    condition_desc = f"{prev_threshold + 1}{unit} - {threshold}{unit}"
                    lower = prev_threshold + 1
                    upper = threshold
                scrap = scrap_rules[idx][1] if idx < len(scrap_rules) else None
                rows.append({
                    "attribute": attribute,
                    "condition_desc": condition_desc,
                    "threshold_lower": lower,
                    "threshold_upper": upper,
                    "change_time_mins": mins,
                    "scrap_weight_kg": scrap,
                    "description": None,
                })

        append_threshold_rules("Width_Up", self.width_up_rules, self.width_up_scrap_rules, "mm")
        append_threshold_rules("Width_Down", self.width_down_rules, self.width_down_scrap_rules, "mm")
        append_threshold_rules("Thickness", self.thickness_rules, self.thickness_scrap_rules, "um")
        rows.extend([
            {
                "attribute": "Die_Change",
                "condition_desc": "target width exceeds current die range",
                "threshold_lower": None,
                "threshold_upper": None,
                "change_time_mins": self.die_change_time,
                "scrap_weight_kg": self.die_change_scrap_kg,
                "description": None,
            },
            {
                "attribute": "Corona",
                "condition_desc": "corona requirement changes",
                "threshold_lower": None,
                "threshold_upper": None,
                "change_time_mins": self.corona_switch_time,
                "scrap_weight_kg": self.corona_switch_scrap_kg,
                "description": None,
            },
            {
                "attribute": "Core_Size",
                "condition_desc": "core size changes",
                "threshold_lower": None,
                "threshold_upper": None,
                "change_time_mins": self.core_size_switch_time,
                "scrap_weight_kg": self.core_size_switch_scrap_kg,
                "description": None,
            },
        ])
        return rows

    # ─── 公开查表接口 ────────────────────────────────────

    def get_material_switch_time(self, from_grade: str, to_grade: str) -> int:
        """查询原料切换耗时（单层）"""
        key = (from_grade, to_grade)
        if key in self.material_switch_matrix:
            return self.material_switch_matrix[key]

        if from_grade == to_grade:
            return self.same_material_time

        # 处理 Special_Co-PE 的通配规则
        if from_grade == "Special_Co-PE":
            return self.special_to_any_time
        if to_grade == "Special_Co-PE":
            return self.any_to_special_time

        # 未命中：安全降级
        fallback_mins = self.missing_material_switch_fallback_mins
        if fallback_mins > 0:
            self.missing_material_switch_pairs[key] = (
                self.missing_material_switch_pairs.get(key, 0) + 1
            )
            if key not in self._warned_missing_material_switches:
                self._warned_missing_material_switches.add(key)
                logger.warning("原料切换矩阵未命中: %s → %s，降级使用默认值 %d min",
                                from_grade, to_grade, fallback_mins)
        return fallback_mins

    def get_material_switch_scrap(self, from_grade: str, to_grade: str) -> Optional[float]:
        """查询原料切换废料；未配置时返回 None 让算法使用旧默认值。"""
        key = (from_grade, to_grade)
        if key in self.material_switch_scrap_matrix:
            return self.material_switch_scrap_matrix[key]

        if from_grade == to_grade:
            return self.same_material_scrap_kg

        if from_grade == "Special_Co-PE":
            return self.special_to_any_scrap_kg
        if to_grade == "Special_Co-PE":
            return self.any_to_special_scrap_kg
        return None

    def get_missing_material_switches(self) -> List[Dict[str, Any]]:
        """返回本轮求解中触发默认降级的材料切换组合。"""
        return [
            {
                "from_material": from_mat,
                "to_material": to_mat,
                "lookup_count": count,
                "fallback_mins": self.missing_material_switch_fallback_mins,
            }
            for (from_mat, to_mat), count in sorted(
                self.missing_material_switch_pairs.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
        ]

    def get_width_change_time(self, delta_width: int, exceeds_max: bool) -> int:
        """查询幅宽变动耗时"""
        if exceeds_max:
            return self.die_change_time

        if delta_width == 0:
            return 0

        abs_delta = abs(delta_width)
        rules = self.width_up_rules if delta_width > 0 else self.width_down_rules

        # 阶梯查表：找到 abs_delta 所落入的区间
        for threshold, mins in rules:
            if abs_delta <= threshold:
                return mins

        # 超过最大阈值 → 返回最后一条规则的耗时
        if rules:
            return rules[-1][1]
        return 0

    def get_width_change_scrap(self, delta_width: int) -> Optional[float]:
        """查询幅宽变动废料；未配置时返回 None 让算法使用旧默认值。"""
        rules = self.width_up_scrap_rules if delta_width > 0 else self.width_down_scrap_rules
        return self._match_threshold_rule(rules, delta_width)

    def get_thickness_change_time(self, delta_thickness: int) -> int:
        """查询厚度变动耗时"""
        if delta_thickness == 0:
            return 0

        abs_delta = abs(delta_thickness)
        for threshold, mins in self.thickness_rules:
            if abs_delta <= threshold:
                return mins

        if self.thickness_rules:
            return self.thickness_rules[-1][1]
        return 0

    def get_thickness_change_scrap(self, delta_thickness: int) -> Optional[float]:
        """查询厚度变动废料；未配置时返回 None 让算法使用旧默认值。"""
        return self._match_threshold_rule(self.thickness_scrap_rules, delta_thickness)

    def get_corona_change_time(self, from_corona: bool, to_corona: bool) -> int:
        """查询电晕切换耗时"""
        if from_corona != to_corona:
            return self.corona_switch_time
        return 0

    def get_core_size_change_time(self, from_core: int, to_core: int) -> int:
        """查询卷芯管径切换耗时"""
        if from_core != to_core:
            return self.core_size_switch_time
        return 0

    def get_gmp_clearance_time(self, from_class: str, to_class: str) -> int:
        """查询 GMP 合规清场耗时"""
        # 精确匹配
        key = (from_class, to_class)
        if key in self.gmp_clearance_matrix:
            return self.gmp_clearance_matrix[key]

        # ANY 通配匹配
        any_key = ("ANY", to_class)
        if any_key in self.gmp_clearance_matrix:
            return self.gmp_clearance_matrix[any_key]

        from_any_key = (from_class, "ANY")
        if from_any_key in self.gmp_clearance_matrix:
            return self.gmp_clearance_matrix[from_any_key]

        # 同级别流转默认无额外清场
        return 0
