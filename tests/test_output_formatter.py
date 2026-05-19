import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.diagnostics import Diagnostic, DiagnosticEvidence, DiagnosticRecommendation
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.output_formatter import export_schedule_report
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


if __name__ == "__main__":
    unittest.main()
