import os
import json
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.diagnostics import Diagnostic, DiagnosticEvidence, DiagnosticRecommendation
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.output_formatter import export_schedule_json, export_schedule_report
from src.scheduler import ScheduleResult, ScheduledTask


def make_order(order_id="ORD-REPORT", **overrides):
    data = {
        "orderId": order_id,
        "productType": "ReportProd",
        "targetWidth": 500,
        "targetThickness": 40,
        "totalQuantityKg": 120,
        "cleanroomReq": "Class_10K",
        "customerClass": "STANDARD",
        "orderClass": "NORMAL",
        "coronaReq": "NO",
        "coreSizeInch": 3,
        "dueDateMins": 100,
        "recipeMaterialsSequence": ["A"] * 5,
    }
    data.update(overrides)
    return ProductionOrderModel.from_dict(data)


def make_machine():
    return BlownFilmMachineModel.from_dict({
        "machineId": "LINE-R",
        "name": "Report Line",
        "cleanroomLevel": "Class_10K",
        "layerStructure": 5,
        "dieDiameterMm": 300,
        "minWidth": 200,
        "maxWidth": 900,
        "minThickness": 20,
        "maxThickness": 80,
        "hourlyOutputKg": 60,
        "maxSlittingLanes": 4,
        "initialMaterialLanes": ["A"] * 5,
        "initialWidth": 300,
        "initialThickness": 40,
        "forbiddenCalendar": [],
    })


class TestOutputFormatter(unittest.TestCase):
    def test_schedule_json_exports_solver_metrics(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.solver_metrics = {
            "phase_1": {
                "status": "OPTIMAL",
                "objective": 0,
                "best_bound": 0.0,
                "gap": 0.0,
                "branches": 10,
                "conflicts": 0,
                "wall_time": 0.01,
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            export_schedule_json(result, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

        self.assertEqual(data["solver_metrics"], result.solver_metrics)

    def test_schedule_json_exports_impact_summaries_as_top_level_contract(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.solver_metrics = {
            "locked_task_protection": {
                "locked_input_order_count": 1,
                "external_locked_interval_count": 1,
                "items": [{"order_id": "ORD-LOCKED"}],
            },
            "adjustment_impact_summary": {
                "adjustment_count": 1,
                "review_required_order_ids": ["ORD-LOCKED"],
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            export_schedule_json(result, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

        self.assertEqual(
            data["locked_task_protection"],
            result.solver_metrics["locked_task_protection"],
        )
        self.assertEqual(
            data["adjustment_impact_summary"],
            result.solver_metrics["adjustment_impact_summary"],
        )

    def test_schedule_json_exports_deferred_orders(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.deferred_orders = [{
            "order_id": "ORD-CANDIDATE",
            "planning_bucket": "candidate",
            "reason": "candidate_optional_rejected",
        }]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            export_schedule_json(result, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

        self.assertEqual(data["deferred_order_count"], 1)
        self.assertEqual(data["deferred_orders"], result.deferred_orders)

    def test_schedule_json_exports_deferred_reason_counts(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.deferred_orders = [
            {"order_id": "ORD-CANDIDATE-A", "reason": "candidate_optional_rejected"},
            {"order_id": "ORD-CANDIDATE-B", "deferred_reason_code": "candidate_optional_rejected"},
            {"order_id": "ORD-WINDOW", "reason": "planning_window_deferred"},
            {"order_id": "ORD-UNKNOWN"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            export_schedule_json(result, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

        self.assertEqual(data["deferred_reason_counts"], {
            "candidate_optional_rejected": 2,
            "planning_window_deferred": 1,
            "unknown": 1,
        })

    def test_schedule_json_exports_result_bucket_counts(self):
        result = ScheduleResult()
        result.status = "INVALID"
        result.input_order_count = 4
        result.blocked_order_count = 1
        result.deferred_orders = [{"order_id": "ORD-CANDIDATE"}]
        result.unplaced_solver_failed_orders = [{"order_id": "ORD-MUST"}]
        result.add_task(ScheduledTask(make_order("ORD-SCHEDULED"), make_machine(), 120, 260, 30, 0, 0))

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            export_schedule_json(result, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

        self.assertEqual(data["scheduled_order_count"], 1)
        self.assertEqual(data["blocked_order_count"], 1)
        self.assertEqual(data["deferred_order_count"], 1)
        self.assertEqual(data["unplaced_solver_failed_order_count"], 1)
        self.assertEqual(data["unplaced_solver_failed_orders"], result.unplaced_solver_failed_orders)

    def test_schedule_report_contains_order_and_global_root_causes(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        order = make_order()
        machine = make_machine()
        result.add_task(ScheduledTask(order, machine, 120, 260, 30, 5.5, 1))
        result.diagnostics.extend([
            Diagnostic(
                entity_type="order",
                entity_id="ORD-REPORT",
                severity="warning",
                category="lateness",
                code="lateness.machine_bottleneck",
                confidence="inferred",
                root_cause="订单在 LINE-R 上逾期，优先检查机台负载。",
                evidence=[DiagnosticEvidence("tardiness_mins", 160, "min")],
                recommendations=[
                    DiagnosticRecommendation("review_order", "检查订单交期", "/config?tab=orders&order=ORD-REPORT")
                ],
                display_title="ORD-REPORT 逾期",
            ),
            Diagnostic(
                entity_type="machine",
                entity_id="LINE-R",
                severity="info",
                category="capacity",
                code="machine.high_load",
                confidence="inferred",
                root_cause="LINE-R 负载偏高。",
                evidence=[DiagnosticEvidence("load_pct", 88, "%")],
                recommendations=[
                    DiagnosticRecommendation("review_machine", "检查机台负载", "/machines")
                ],
                display_title="LINE-R 高负载",
            ),
        ])

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule_report.md")
            export_schedule_report(result, path)
            with open(path, encoding="utf-8") as f:
                text = f.read()

        self.assertIn("## 订单异常根因", text)
        self.assertIn("ORD-REPORT 逾期", text)
        self.assertIn("## 全局排程根因分析", text)
        self.assertIn("LINE-R 高负载", text)
        self.assertIn("## 机台排程摘要", text)

    def test_schedule_report_contains_locked_task_protection_summary(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.solver_metrics = {
            "locked_task_protection": {
                "locked_input_order_count": 1,
                "external_locked_interval_count": 1,
                "items": [
                    {
                        "order_id": "ORD-LOCKED",
                        "machine_id": "LINE-R",
                        "start_mins": 120,
                        "end_mins": 180,
                        "protection_mode": "machine_and_time",
                    },
                    {
                        "order_id": "ORD-EXTERNAL",
                        "machine_id": "LINE-R",
                        "start_mins": 240,
                        "end_mins": 300,
                        "protection_mode": "external_interval",
                    },
                ],
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule_report.md")
            export_schedule_report(result, path)
            with open(path, encoding="utf-8") as f:
                text = f.read()

        self.assertIn("## 锁定任务保护", text)
        self.assertIn("ORD-LOCKED", text)
        self.assertIn("machine_and_time", text)
        self.assertIn("ORD-EXTERNAL", text)
        self.assertIn("external_interval", text)

    def test_schedule_report_contains_manual_adjustment_impact_summary(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.solver_metrics = {
            "adjustment_impact_summary": {
                "adjustment_count": 2,
                "machine_change_count": 1,
                "time_changed_count": 2,
                "locked_after_adjustment_count": 1,
                "total_setup_time_delta_mins": 30,
                "total_tardiness_delta_mins": 45,
                "max_delay_delta_mins": 120,
                "has_negative_impact": True,
                "negative_impact_order_ids": ["ORD-A"],
                "review_required_count": 1,
                "review_required_order_ids": ["ORD-A"],
                "review_reason_summary": {
                    "end_delayed": {
                        "label": "完工延后",
                        "affected_order_count": 1,
                        "max_actual_delta_mins": 120,
                        "threshold_mins": 30,
                    },
                    "tardiness_increased": {
                        "label": "逾期增加",
                        "affected_order_count": 1,
                        "max_actual_delta_mins": 45,
                        "threshold_mins": 15,
                    },
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule_report.md")
            export_schedule_report(result, path)
            with open(path, encoding="utf-8") as f:
                text = f.read()

        self.assertIn("## 人工调整影响", text)
        self.assertIn("ORD-A", text)
        self.assertIn("完工延后", text)
        self.assertIn("逾期增加", text)
        self.assertIn("120", text)
        self.assertIn("45", text)

    def test_schedule_report_explains_deferred_and_unplaced_orders(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        result.deferred_orders = [
            {
                "order_id": "ORD-DEFERRED",
                "planning_bucket": "candidate",
                "deferred_reason_code": "candidate_optional_rejected",
                "reason": "候选订单未被本轮接受",
            }
        ]
        result.unplaced_solver_failed_orders = [
            {
                "order_id": "ORD-UNPLACED",
                "planning_bucket": "must_schedule",
                "unplaced_reason_code": "required_order_unplaced",
                "reason": "锁定窗口下无可用空隙",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule_report.md")
            export_schedule_report(result, path)
            with open(path, encoding="utf-8") as f:
                text = f.read()

        self.assertIn("## 未进入本轮计划订单", text)
        self.assertIn("ORD-DEFERRED", text)
        self.assertIn("candidate_optional_rejected", text)
        self.assertIn("候选订单未被本轮接受", text)
        self.assertIn("ORD-UNPLACED", text)
        self.assertIn("required_order_unplaced", text)
        self.assertIn("锁定窗口下无可用空隙", text)


if __name__ == "__main__":
    unittest.main()
