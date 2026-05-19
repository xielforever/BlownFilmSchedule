"""
排程顺序约束与结果校验回归测试。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import ProductionOrderModel, BlownFilmMachineModel
from src.scheduler import AdvancedMedicalAPS, ScheduleResult, ScheduledTask
from src.setup_matrices import SetupMatricesManager
from api.routers.schedule import _decode_child_output


def _make_order(order_id: str, **overrides) -> ProductionOrderModel:
    data = {
        "orderId": order_id,
        "productType": "TestProd",
        "targetWidth": 300,
        "targetThickness": 40,
        "totalQuantityKg": 60,
        "cleanroomReq": "Class_10K",
        "customerClass": "STANDARD",
        "orderClass": "NORMAL",
        "coronaReq": "NO",
        "coreSizeInch": 3,
        "dueDateMins": 5000,
        "recipeMaterialsSequence": ["Borealis_LE6601-PH"] * 5,
    }
    data.update(overrides)
    return ProductionOrderModel.from_dict(data)


def _make_machine(**overrides) -> BlownFilmMachineModel:
    data = {
        "machineId": "LINE-T",
        "name": "Test Line",
        "cleanroomLevel": "Class_10K",
        "layerStructure": 5,
        "dieDiameterMm": 300,
        "minWidth": 200,
        "maxWidth": 600,
        "minThickness": 20,
        "maxThickness": 80,
        "hourlyOutputKg": 60,
        "maxSlittingLanes": 4,
        "initialMaterialLanes": ["Standard_Med_LDPE"] * 5,
        "initialWidth": 300,
        "initialThickness": 40,
        "forbiddenCalendar": [],
    }
    data.update(overrides)
    return BlownFilmMachineModel.from_dict(data)


def _make_setup_mgr() -> SetupMatricesManager:
    mgr = SetupMatricesManager()
    mgr.same_material_time = 30
    mgr.material_switch_matrix[("Standard_Med_LDPE", "Borealis_LE6601-PH")] = 120
    mgr.width_up_rules = [(999, 0)]
    mgr.width_down_rules = [(999, 0)]
    mgr.thickness_rules = [(999, 0)]
    mgr.corona_switch_time = 0
    mgr.core_size_switch_time = 0
    return mgr


class TestSchedulerSequencing(unittest.TestCase):
    def test_same_machine_tasks_reserve_setup_gap(self):
        orders = [_make_order(f"ORD-T{i}") for i in range(3)]
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run(orders, [machine])

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(result.validation_errors, [])
        tasks = sorted(result.tasks, key=lambda t: t.start_mins)
        self.assertEqual(len(tasks), len(orders))
        self.assertGreaterEqual(tasks[0].start_mins, tasks[0].setup_time)

        for prev, curr in zip(tasks, tasks[1:]):
            self.assertGreaterEqual(
                curr.start_mins,
                prev.end_mins + curr.setup_time,
                f"{prev.order.order_id}->{curr.order.order_id} lacks setup gap",
            )

    def test_validation_catches_machine_overlap(self):
        order_a = _make_order("ORD-A")
        order_b = _make_order("ORD-B")
        machine = _make_machine()
        result = ScheduleResult()
        result.add_task(ScheduledTask(order_a, machine, 0, 100, 0, 0, 0))
        result.add_task(ScheduledTask(order_b, machine, 50, 150, 0, 0, 1))

        aps = AdvancedMedicalAPS(_make_setup_mgr())
        aps._validate_result(result, expected_order_count=2)

        self.assertTrue(result.validation_errors)

    def test_infeasible_order_returns_validation_error(self):
        order = _make_order("ORD-WIDE", targetWidth=9999)
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run([order], [machine])

        self.assertEqual(result.status, "INFEASIBLE")
        self.assertEqual(result.tasks, [])
        self.assertEqual(len(result.validation_errors), 1)
        self.assertIn("无可用机台", result.validation_errors[0])
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "eligibility.width_out_of_range")

    def test_decode_child_output_handles_gbk_logs(self):
        text = "订单 ORD-062 无可用机台: width=1718, thickness=80"
        self.assertEqual(_decode_child_output(text.encode("gbk")), text)


if __name__ == "__main__":
    unittest.main()
