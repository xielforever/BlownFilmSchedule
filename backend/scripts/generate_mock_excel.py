from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from app.excel_io import machines_to_dataframe
from app.machines import built_in_machines


OUTPUT_PATH = WORKSPACE_DIR / "examples" / "blownfilm_mvp_mock_v2.xlsx"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    orders = pd.DataFrame(_orders())
    machines = machines_to_dataframe(built_in_machines())
    rules = pd.DataFrame(
        [
            {"rule_type": "SCHEDULING_OBJECTIVE", "value": "DUE_DATE_FIRST", "description": "交期优先"},
            {"rule_type": "CHANGEOVER_FACTOR", "value": "MATERIAL", "description": "换料成本按配方变化评分"},
            {"rule_type": "CHANGEOVER_FACTOR", "value": "SETUP", "description": "调机成本按宽度、厚度变化评分"},
            {"rule_type": "MACHINE_TAG", "value": "HD_ONLY", "description": "HD 专用机台"},
            {"rule_type": "MACHINE_TAG", "value": "SF101_ONLY", "description": "仅允许 SF101"},
            {"rule_type": "MACHINE_TAG", "value": "NON_BLOW_RATIO_RULE", "description": "非普通吹胀比规则"},
        ]
    )
    field_reservation = pd.DataFrame(
        [
            {"field": "customer", "scope": "orders", "mvp_required": False, "description": "客户名称"},
            {"field": "clean_level", "scope": "orders", "mvp_required": False, "description": "洁净等级"},
            {"field": "is_medical", "scope": "orders", "mvp_required": False, "description": "是否医用订单"},
            {"field": "allow_split", "scope": "orders", "mvp_required": False, "description": "是否允许拆单"},
            {"field": "changeover_hours", "scope": "rules", "mvp_required": False, "description": "真实换型小时规则"},
            {"field": "cleaning_validation_hours", "scope": "rules", "mvp_required": False, "description": "医用清洁验证时间"},
        ]
    )
    data_quality = pd.DataFrame(
        [
            {
                "sheet": "orders",
                "record_key": "*",
                "source": "provided screenshots, normalized for MVP demo",
                "quality_flag": "PRODUCTION_PRESSURE_DEMO",
                "comment": "只输出订单需求字段；包含紧急、同交期、换料、调机和大批量订单，排程结果由算法自动生成。",
            }
        ]
    )

    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        orders.to_excel(writer, sheet_name="orders", index=False)
        machines.to_excel(writer, sheet_name="machines", index=False)
        rules.to_excel(writer, sheet_name="rules", index=False)
        field_reservation.to_excel(writer, sheet_name="field_reservation", index=False)
        data_quality.to_excel(writer, sheet_name="data_quality", index=False)
    print(OUTPUT_PATH)


def _orders() -> list[dict]:
    return [
        _row("B2605215", "岳丽贤", "2026-05-19 18:00", "SF101", "B2605215", "0170-0005", "490(160+160)*1050*0.08mm", 5000, 126.0, 630, 11, "高"),
        _row("B2605104", "岳丽贤", "2026-05-19 18:00", "SF101", "B2605104", "0713-0102", "800*1250*0.08mm", 1500, 148.0, 222, 4, "中"),
        _row("B2605143", "岳丽贤", "2026-05-19 18:00", "SF101", "B2605143", "3926-0101", "900*930*0.04mm", 12400, 62.0, 769, 13, "急"),
        _row("B2605232", "徐娇", "2026-05-19 18:00", "SF101", "B2605232", "3817-0101", "900*900*0.09mm", 500, 134.9, 67, 1, "低"),
        _row("B2605207", "岳丽贤", "2026-05-20 18:00", "SF101", "B2605207", "4362-0102", "850*1300*0.1mm", 5000, 204.4, 1022, 17, "高"),
        _row("B2604741", "刘广", "2026-05-20 18:00", "SF048", "B2604741", "SF048-05", "635*0.15mm", 1000, 179.7, 180, 4, "中"),
        _row("B2605015", "高晓芳", "2026-05-20 18:00", "SF048", "B2605015", "SF048-07", "735*0.15mm", 2500, 205.0, 513, 13, "高"),
        _row("B2604743", "刘广", "2026-05-20 18:00", "SF048", "B2604743", "SF048-07", "735*0.15mm", 1100, 205.0, 226, 6, "低"),
        _row("B2605265", "徐娇", "2026-05-21 18:00", "SF121黑色", "B2605265", "2480-0001", "370(170+170)*1090*0.08mm", 750, 117.0, 88, 2, "中"),
        _row("B2605170", "徐娇", "2026-05-21 18:00", "SF121黑色", "B2605170", "0036-0001", "330(160+160)*1150*0.08mm", 4000, 113.0, 452, 11, "高"),
        _row("B2605041", "徐娇", "2026-05-21 18:00", "SF101", "B2605041", "2105-0002", "365(177.5+177.5)*900*0.08mm", 2000, 61.0, 122, 3, "中"),
        _row("B2604706", "徐娇", "2026-05-23 12:00", "SF101", "B2604706", "2079-0001", "380(170+170)*1070*0.08mm", 20100, 116.2, 2336, 58, "急"),
        _row("B2605140", "徐娇", "2026-05-22 18:00", "SF101", "B2605140", "1658-0001", "370(165+165)*1120*0.07mm", 3000, 103.5, 311, 8, "中"),
        _row("B2605154", "顾玲", "2026-05-22 18:00", "SF101", "B2605154", "HM1935-1", "270(100+100)*710*0.09mm", 16000, 56.0, 896, 22, "高"),
        _row("B2604331", "岳丽贤", "2026-05-24 08:00", "SF152", "B2604331", "0024-0001", "570(235+235)*940*0.015mm", 180000, 27.8, 5004, 100, "急"),
        _row("B2605035", "岳丽贤", "2026-05-22 18:00", "SF151", "B2605035", "4140-0102", "650*790*0.04mm", 12825, 39.0, 500, 10, "中"),
        _row("B2605029", "蔡倩", "2026-05-24 12:00", "SF152", "B2605029", "0038-0101", "930*910*0.025mm", 25000, 40.0, 1000, 20, "中"),
        _row("B2605256", "岳丽贤", "2026-05-23 18:00", "SF151", "B2605256", "0002-0001", "480(100+100)*900*0.03mm", 38800, 34.6, 1342, 27, "高"),
        _row("B2604562", "岳丽贤", "2026-05-22 18:00", "SF101", "B2604562", "0077-0002", "400*600*0.08mm", 5000, 36.2, 181, 9, "低"),
        _row("B2604636", "徐娇", "2026-05-22 18:00", "SF101", "B2604636", "2836-0102", "400*800*0.08mm", 2700, 48.0, 130, 6, "中"),
        _row("B2605003", "高晓芳", "2026-05-23 18:00", "SF048", "B2605003", "SF048-03", "335*0.15mm", 3000, 94.8, 284, 14, "高"),
        _row("B2604739", "刘广", "2026-05-23 18:00", "SF048", "B2604739", "SF048-03", "335*0.15mm", 1000, 94.8, 95, 5, "低"),
    ]


def _row(
    job_id: str,
    planner: str,
    due: str,
    formula: str,
    batch_no: str,
    material_code: str,
    spec: str,
    order_qty: float,
    unit_weight: float | None,
    batch_kg: float,
    work_hours: float,
    urgency: str | None = None,
) -> dict:
    return {
        "job_id": job_id,
        "order_date": "2026-05-18 08:00",
        "planner": planner,
        "plan_finish_time": due,
        "formula": formula,
        "batch_no": batch_no,
        "material_code": material_code,
        "spec_raw": spec,
        "order_qty": order_qty,
        "unit_weight_g": unit_weight,
        "batch_kg": batch_kg,
        "work_hours": work_hours,
        "urgency": urgency,
        "customer": "",
        "clean_level": "",
        "is_medical": "",
        "color": "",
        "allow_split": False,
    }


if __name__ == "__main__":
    main()
