from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from app.excel_io import load_orders_from_excel, write_schedule_outputs
from app.machines import MACHINE_DATA_PATH, built_in_machines, load_machines_from_excel
from app.models import OrderJob
from app.scheduler import evaluate_machine_fit, is_machine_feasible, run_schedule
from app.spec_parser import parse_spec


def _job(**overrides) -> OrderJob:
    data = {
        "job_id": "J",
        "order_date": datetime(2026, 5, 18, 8),
        "plan_finish_time": datetime(2026, 5, 21),
        "formula": "SF048",
        "batch_no": "J",
        "material_code": "SF048-01",
        "spec_raw": "735*0.15mm",
        "batch_kg": 100,
        "work_hours": 2,
    }
    data.update(overrides)
    data["parsed_spec"] = parse_spec(data["spec_raw"])
    return OrderJob(**data)


def test_parse_insert_spec_uses_base_plus_insert() -> None:
    parsed = parse_spec("370(170+170)*1090*0.08mm")
    assert parsed.parse_status == "ok"
    assert parsed.width_mm == 710
    assert parsed.insert_width_mm == 340
    assert parsed.thickness_mm == 0.08


def test_local_machine_workbook_is_schedule_source() -> None:
    machines = built_in_machines()
    raw = pd.read_excel(MACHINE_DATA_PATH, sheet_name="machines")
    by_id = {machine.machine_id: machine for machine in machines}

    assert MACHINE_DATA_PATH.exists()
    assert len(machines) == len(raw) == 20
    assert by_id["M104"].rule_tags == ["HD_ONLY"]
    assert by_id["M506"].capacity_avg_kg_h == 200


def test_machine_workbook_requires_machine_id(tmp_path: Path) -> None:
    path = tmp_path / "machines.xlsx"
    pd.DataFrame([{"mold_spec": "160"}]).to_excel(path, sheet_name="machines", index=False)

    with pytest.raises(ValueError, match="machine_id"):
        load_machines_from_excel(path)


def test_order_pool_is_scheduled_without_external_plan() -> None:
    result = run_schedule([_job(job_id="C1")], built_in_machines())

    assert result.exceptions == []
    assert result.summary.total_jobs == 1
    assert result.summary.scheduled_jobs == 1
    assert result.assignments[0].start_time == datetime(2026, 5, 18, 8)
    assert result.assignments[0].production_hours > 0
    assert result.assignments[0].duration_hours == result.assignments[0].production_hours
    assert any(row.job_id == "C1" and row.selected and row.rank == 1 for row in result.candidate_audit)


def test_scheduler_selects_feasible_machine_from_order_input() -> None:
    machines = [machine for machine in built_in_machines() if machine.machine_id in {"M105", "M102"}]
    order = _job(job_id="C2", spec_raw="735*0.15mm")
    ok, _ = is_machine_feasible(order, next(machine for machine in machines if machine.machine_id == "M105"))
    assert not ok

    result = run_schedule([order], machines)

    assert result.exceptions == []
    assert result.assignments[0].machine_id == "M102"
    assert result.assignments[0].fit_level == "marginal"


def test_machine_fit_levels_distinguish_recommended_marginal_and_blocked() -> None:
    order = _job(job_id="FIT", spec_raw="735*0.15mm")
    machines = {machine.machine_id: machine for machine in built_in_machines()}

    best = evaluate_machine_fit(order, machines["M101"])
    marginal = evaluate_machine_fit(order, machines["M102"])
    blocked = evaluate_machine_fit(order, machines["M105"])

    assert best.passed and best.level == "best"
    assert marginal.passed and marginal.level == "marginal"
    assert not blocked.passed and blocked.level == "blocked"


def test_hd_only_rejects_non_hd_formula() -> None:
    order = _job(job_id="HD1", formula="SF101", spec_raw="570(235+235)*940*0.015mm")
    machine = next(machine for machine in built_in_machines() if machine.machine_id == "M104")

    ok, messages = is_machine_feasible(order, machine)

    assert not ok
    assert "HD专用机台仅接受HD订单" in messages


def test_sf101_only_machine_rejects_other_formula() -> None:
    order = _job(job_id="SF", formula="SF048", spec_raw="500*0.1mm")
    machine = next(machine for machine in built_in_machines() if machine.machine_id == "M110")

    ok, messages = is_machine_feasible(order, machine)

    assert not ok
    assert "机台仅限 SF101" in messages


def test_order_sheet_does_not_require_plan_columns(tmp_path: Path) -> None:
    path = tmp_path / "orders_only.xlsx"
    pd.DataFrame(
        [
            {
                "job_id": "PURE1",
                "order_date": "2026-05-18 08:00",
                "plan_finish_time": "2026-05-21",
                "formula": "SF048",
                "batch_no": "PURE1",
                "material_code": "SF048-01",
                "spec_raw": "735*0.15mm",
                "batch_kg": 100,
                "work_hours": 2,
            }
        ]
    ).to_excel(path, sheet_name="orders", index=False)

    orders, issues = load_orders_from_excel(path)
    result = run_schedule(orders, built_in_machines(), issues)

    assert not [issue for issue in issues if issue.severity.value == "error"]
    assert result.exceptions == []
    assert result.assignments[0].job_id == "PURE1"


def test_order_input_quality_validation_flags_bad_rows(tmp_path: Path) -> None:
    path = tmp_path / "bad_orders.xlsx"
    pd.DataFrame(
        [
            {
                "job_id": "DUP",
                "order_date": "2026-05-18 08:00",
                "plan_finish_time": "2026-05-17 18:00",
                "formula": "SF048",
                "batch_no": "DUP",
                "material_code": "SF048-01",
                "spec_raw": "735*0.15mm",
                "order_qty": 1000,
                "unit_weight_g": 100,
                "batch_kg": 500,
                "work_hours": 1,
            },
            {
                "job_id": "DUP",
                "order_date": "2026-05-18 08:00",
                "plan_finish_time": "2026-06-10 18:00",
                "formula": "SF048",
                "batch_no": "DUP-2",
                "material_code": "SF048-02",
                "spec_raw": "735*0.15mm",
                "order_qty": 1000,
                "unit_weight_g": 100,
                "batch_kg": 100,
                "work_hours": 2,
            },
        ]
    ).to_excel(path, sheet_name="orders", index=False)

    _, issues = load_orders_from_excel(path)
    messages = "\n".join(issue.message for issue in issues)

    assert any(issue.severity.value == "error" and issue.field == "job_id" for issue in issues)
    assert any(issue.severity.value == "error" and issue.field == "plan_finish_time" for issue in issues)
    assert any(issue.severity.value == "warning" and issue.field == "batch_kg" for issue in issues)
    assert any(issue.severity.value == "warning" and issue.field == "work_hours" for issue in issues)
    assert "人工" not in messages


def test_reason_mentions_material_change_and_setup() -> None:
    machines = [machine for machine in built_in_machines() if machine.machine_id == "M102"]
    first = _job(job_id="A", formula="SF048", spec_raw="705*0.15mm", plan_finish_time=datetime(2026, 5, 20))
    second = _job(job_id="B", formula="SF038", spec_raw="645*0.12mm", plan_finish_time=datetime(2026, 5, 21))

    result = run_schedule([first, second], machines)
    second_assignment = next(item for item in result.assignments if item.job_id == "B")

    assert "换料" in second_assignment.reason
    assert "调机" in second_assignment.reason
    assert second_assignment.changeover_hours > 0
    assert second_assignment.production_start_time > second_assignment.start_time


def test_schedule_result_exposes_priority_and_machine_load_metrics() -> None:
    machines = [machine for machine in built_in_machines() if machine.machine_id == "M101"]
    first = _job(job_id="A", formula="SF101", spec_raw="900*930*0.04mm", batch_kg=200)
    second = _job(job_id="B", formula="SF101", spec_raw="900*900*0.09mm", batch_kg=100)

    result = run_schedule([first, second], machines)
    first_assignment = next(item for item in result.assignments if item.job_id == "A")
    load = next(item for item in result.machine_loads if item.machine_id == "M101")

    assert "交期 2026-05-21 00:00" in first_assignment.priority_reason
    assert "批量 200kg" in first_assignment.priority_reason
    assert first_assignment.idle_before_hours == 0
    assert result.summary.total_production_hours > 0
    assert result.summary.total_changeover_hours >= 0
    assert load.job_count == 2
    assert load.production_hours > 0
    assert load.load_pct > 0
    assert any(row.job_id == "A" and row.machine_id == first_assignment.machine_id and row.selected for row in result.candidate_audit)


def test_schedule_insights_explain_due_slack_and_same_due_spread() -> None:
    machines = [machine for machine in built_in_machines() if machine.machine_id == "M101"]
    first = _job(
        job_id="B2605104",
        formula="SF101",
        spec_raw="800*1250*0.08mm",
        batch_kg=222,
        work_hours=4,
        plan_finish_time=datetime(2026, 6, 1, 18),
    )
    second = _job(
        job_id="B2605143",
        formula="SF101",
        spec_raw="900*930*0.04mm",
        batch_kg=769,
        work_hours=13,
        plan_finish_time=datetime(2026, 6, 1, 18),
    )

    result = run_schedule([first, second], machines)
    codes = {item.code for item in result.schedule_insights}
    messages = "\n".join(item.message for item in result.schedule_insights)

    assert "large_due_slack" in codes
    assert "same_due_spread" in codes
    assert "B2605104" in messages
    assert "B2605143" in messages
    assert "人工" not in messages


def test_schedule_export_contains_insight_sheet_and_report_section(tmp_path: Path) -> None:
    result = run_schedule([_job(job_id="A"), _job(job_id="B", batch_kg=900)], built_in_machines())
    paths = write_schedule_outputs(result, tmp_path, "case")

    workbook = pd.ExcelFile(paths["schedule"])
    report = paths["report"].read_text(encoding="utf-8")

    assert "schedule_insights" in workbook.sheet_names
    assert "candidate_audit" in workbook.sheet_names
    assert "## 排程解释" in report
    assert "## 候选机台审计" in report


def test_downloadable_mock_orders_are_pure_order_input() -> None:
    path = Path(__file__).resolve().parents[2] / "examples" / "blownfilm_mvp_mock_v2.xlsx"
    workbook = pd.ExcelFile(path)
    assert workbook.sheet_names == ["orders", "machines", "rules", "field_reservation", "data_quality"]

    raw_orders = pd.read_excel(path, sheet_name="orders")
    assert list(raw_orders.columns) == [
        "job_id",
        "order_date",
        "planner",
        "plan_finish_time",
        "formula",
        "batch_no",
        "material_code",
        "spec_raw",
        "order_qty",
        "unit_weight_g",
        "batch_kg",
        "work_hours",
        "urgency",
        "customer",
        "clean_level",
        "is_medical",
        "color",
        "allow_split",
    ]

    orders, issues = load_orders_from_excel(path)
    result = run_schedule(orders, built_in_machines(), issues)

    assert orders
    assert not [issue for issue in issues if issue.severity.value == "error"]
    assert result.exceptions == []
    assert result.summary.scheduled_jobs == len(orders)
    assert result.summary.late_jobs == 0
    assert result.summary.total_production_hours > 0
    assert result.machine_loads
    assert all("换料" in item.reason or "调机" in item.reason or "机台首单" in item.reason or "同配方衔接" in item.reason for item in result.assignments)
