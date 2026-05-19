import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.diagnostics import (
    build_infeasible_order_diagnostic,
    evaluate_machine_fit,
    parse_infeasible_log_diagnostics,
)
from src.models import BlownFilmMachineModel, ProductionOrderModel


def make_order(order_id="ORD-DIAG", **overrides):
    data = {
        "orderId": order_id,
        "productType": "TestProd",
        "targetWidth": 900,
        "targetThickness": 40,
        "totalQuantityKg": 60,
        "cleanroomReq": "Class_10K",
        "customerClass": "STANDARD",
        "orderClass": "NORMAL",
        "coronaReq": "NO",
        "coreSizeInch": 3,
        "dueDateMins": 5000,
        "recipeMaterialsSequence": ["A"] * 5,
    }
    data.update(overrides)
    return ProductionOrderModel.from_dict(data)


def make_machine(**overrides):
    data = {
        "machineId": "LINE-D",
        "name": "Diagnostic Line",
        "cleanroomLevel": "Class_10K",
        "layerStructure": 5,
        "dieDiameterMm": 300,
        "minWidth": 200,
        "maxWidth": 600,
        "minThickness": 20,
        "maxThickness": 80,
        "hourlyOutputKg": 60,
        "maxSlittingLanes": 4,
        "initialMaterialLanes": ["A"] * 5,
        "initialWidth": 300,
        "initialThickness": 40,
        "forbiddenCalendar": [],
    }
    data.update(overrides)
    return BlownFilmMachineModel.from_dict(data)


class TestDiagnostics(unittest.TestCase):
    def test_machine_fit_explains_width_blocker(self):
        order = make_order(targetWidth=999)
        machine = make_machine(maxWidth=600)

        fit = evaluate_machine_fit(order, machine)

        self.assertFalse(fit.eligible)
        self.assertEqual(fit.issues[0].code, "eligibility.width_out_of_range")
        self.assertIn("999", fit.issues[0].root_cause)

    def test_infeasible_order_diagnostic_is_serializable(self):
        order = make_order(targetWidth=999)
        machine = make_machine(maxWidth=600)

        diagnostic = build_infeasible_order_diagnostic(order, [machine]).to_dict(run_id=12)

        self.assertEqual(diagnostic["run_id"], 12)
        self.assertEqual(diagnostic["entity_type"], "order")
        self.assertEqual(diagnostic["entity_id"], order.order_id)
        self.assertEqual(diagnostic["code"], "eligibility.width_out_of_range")
        self.assertEqual(diagnostic["display_title"], f"{order.order_id} 无可用机台")
        self.assertTrue(diagnostic["evidence"])
        self.assertTrue(diagnostic["recommendations"])

    def test_parse_infeasible_log_diagnostics(self):
        text = "07:05:11 [ERROR] src.scheduler: 订单 ORD-062 无可用机台: width=1718, thickness=80"

        diagnostics = parse_infeasible_log_diagnostics(text)

        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["entity_id"], "ORD-062")
        self.assertEqual(diagnostics[0]["code"], "eligibility.no_eligible_machine")
        self.assertIn("检查订单配置", diagnostics[0]["recommendations"][0]["label"])


if __name__ == "__main__":
    unittest.main()
