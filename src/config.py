"""
APS 排程系统集中配置管理模块

所有可调参数集中管理，避免魔法数字散布在各模块中。
"""

# ─── 时间基准 ───────────────────────────────────────────
# 排程零点基准时间（所有 DateTime → 整数分钟偏移量的锚点）
BASELINE_TIME = "2026-05-17 08:00"

# CP-SAT 求解器每阶段时间限制（秒）
# 232 单压力场景在修复同机台重叠后需要更长时间找到可行解。
SOLVER_TIME_LIMIT_SECONDS = 120.0

# 计划域上界（分钟），31 天 × 24 小时 × 60 分钟
MAX_HORIZON_MINUTES = 44640

# ─── 法规合规约束 ─────────────────────────────────────────
# 连续运行上限（分钟），72 小时 = 4320 分钟
CONTINUOUS_RUN_LIMIT_MINUTES = 4320

# 72 小时强制清场操作持续时间（分钟）
MANDATORY_CLEANING_DURATION_MINUTES = 90

# ─── 交期惩罚权重 ─────────────────────────────────────────
# VIP + URGENT 订单的交期延迟惩罚权重
TARDINESS_WEIGHT_VIP_URGENT = 100

# VIP + NORMAL / STANDARD + URGENT 的交期延迟惩罚权重
TARDINESS_WEIGHT_HIGH = 50

# 普通订单（STANDARD + NORMAL）的交期延迟惩罚权重
TARDINESS_WEIGHT_NORMAL = 10

# SAMPLE 订单的交期延迟惩罚权重（临床试验交期通常极紧迫）
TARDINESS_WEIGHT_SAMPLE = 80

# ─── 废料估算参数 ─────────────────────────────────────────
# 每层异质换料的单层废料基准重量（kg）
SCRAP_PER_LAYER_MATERIAL_CHANGE_KG = 25

# 同料换批次的单层废料重量（kg）
SCRAP_PER_LAYER_SAME_MATERIAL_KG = 5

# 幅宽调机废料基准重量（kg）
SCRAP_WIDTH_CHANGE_KG = 15

# 厚度调机废料基准重量（kg）
SCRAP_THICKNESS_CHANGE_KG = 10

# ─── 维保日历规则 ─────────────────────────────────────────
# 全厂默认维保日历（适用于所有机台）
# 格式: {"startMins": int, "endMins": int, "reason": str}
# 以下为相对于 BASELINE_TIME 的分钟偏移量
FORBIDDEN_CALENDAR_RULES = [
    {
        "startMins": 2880,   # 基准时间 +48h = 周日 08:00
        "endMins": 3160,     # 基准时间 +52h40min = 周日 12:40
        "reason": "洁净车间每周固定微生物消杀与空载测试"
    },
]

# ─── 换产矩阵默认降级值 ─────────────────────────────────────
# 当换产矩阵查表未命中时的安全降级默认值（分钟）
DEFAULT_MATERIAL_SWITCH_TIME_MINS = 120

# ─── 输入/输出路径 ─────────────────────────────────────────
INPUT_EXCEL_PATH = "input/吹膜机排程数据.xlsx"

OUTPUT_DIR = "output"
OUTPUT_SCHEDULE_JSON = "output/schedule_result.json"
OUTPUT_SCHEDULE_CSV = "output/schedule_result.csv"
OUTPUT_MATERIAL_CORRECTION_CSV = "output/material_correction.csv"
OUTPUT_SCHEDULE_REPORT_MD = "output/schedule_report.md"

# ─── 数据库连接 ─────────────────────────────────────────────
DATABASE_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "ap",
    "username": "ap_user",
    "password": "123456",
}


def get_tardiness_weight(customer_class: str, order_class: str) -> int:
    """根据客户等级和订单类型返回对应的交期惩罚权重"""
    if order_class == "SAMPLE":
        return TARDINESS_WEIGHT_SAMPLE
    if customer_class == "VIP" and order_class == "URGENT":
        return TARDINESS_WEIGHT_VIP_URGENT
    if customer_class == "VIP" or order_class == "URGENT":
        return TARDINESS_WEIGHT_HIGH
    return TARDINESS_WEIGHT_NORMAL
