"""
排程顺序约束与结果校验回归测试。
"""

import os
import sys
import unittest
from types import SimpleNamespace

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

    def test_solver_metrics_record_phase_quality(self):
        orders = [_make_order(f"ORD-METRIC-{i}") for i in range(2)]
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run(orders, [machine])

        self.assertIn("phase_1", result.solver_metrics)
        self.assertIn("phase_2", result.solver_metrics)
        phase1 = result.solver_metrics["phase_1"]
        self.assertIn(phase1["status"], {"OPTIMAL", "FEASIBLE"})
        for key in ["objective", "best_bound", "gap", "branches", "conflicts", "wall_time"]:
            self.assertIn(key, phase1)
        self.assertGreaterEqual(phase1["wall_time"], 0)

    def test_solver_metrics_record_model_size(self):
        orders = [
            _make_order("ORD-MODEL-MUST"),
            _make_order("ORD-MODEL-CANDIDATE", planningBucket="candidate"),
        ]
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run(orders, [machine])

        model_size = result.solver_metrics["model_size"]
        self.assertEqual(model_size["order_count"], 2)
        self.assertEqual(model_size["machine_count"], 1)
        self.assertEqual(model_size["assignment_count"], 2)
        self.assertEqual(model_size["optional_candidate_count"], 1)
        self.assertEqual(model_size["eligible_orders_per_machine"], {"LINE-T": 2})
        self.assertGreaterEqual(model_size["arc_count"], 7)
        self.assertEqual(model_size["setup_cache_size"], 4)

    def test_arc_pruning_policy_reduces_order_to_order_arcs(self):
        orders = [
            _make_order("ORD-PRUNE-MUST"),
            _make_order("ORD-PRUNE-CANDIDATE", planningBucket="candidate"),
        ]
        machine = _make_machine()
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            candidate_acceptance_policy={"reject_penalty": 1},
            arc_pruning_policy={
                "enabled": True,
                "max_setup_time_mins": 0,
            },
        )

        result = aps.run(orders, [machine])

        model_size = result.solver_metrics["model_size"]
        self.assertEqual(model_size["pruned_arc_count"], 2)
        self.assertEqual(model_size["arc_count"], 7)
        self.assertEqual([task.order.order_id for task in result.tasks], ["ORD-PRUNE-MUST"])

    def test_locked_task_keeps_machine_and_time(self):
        locked_order = _make_order("ORD-LOCKED")
        next_order = _make_order("ORD-NEXT")
        machine = _make_machine()
        locked_task = ScheduledTask(
            locked_order,
            machine,
            start_mins=120,
            end_mins=180,
            setup_time=120,
            scrap_kg=0,
            sequence_index=0,
        )
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run([locked_order, next_order], [machine], locked_tasks=[locked_task])

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(result.validation_errors, [])
        by_order = {task.order.order_id: task for task in result.tasks}
        self.assertEqual(by_order["ORD-LOCKED"].machine.machine_id, "LINE-T")
        self.assertEqual(by_order["ORD-LOCKED"].start_mins, 120)
        self.assertEqual(by_order["ORD-LOCKED"].end_mins, 180)
        self.assertGreaterEqual(by_order["ORD-NEXT"].start_mins, by_order["ORD-LOCKED"].end_mins)

    def test_machine_locked_task_can_move_when_time_is_unlocked(self):
        locked_order = _make_order("ORD-MACHINE-LOCKED")
        machine = _make_machine()
        locked_task = ScheduledTask(
            locked_order,
            machine,
            start_mins=999,
            end_mins=1059,
            setup_time=120,
            scrap_kg=0,
            sequence_index=0,
            manual_lock_machine=True,
            manual_lock_time=False,
        )
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run([locked_order], [machine], locked_tasks=[locked_task])

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        task = result.tasks[0]
        self.assertEqual(task.machine.machine_id, "LINE-T")
        self.assertNotEqual(task.start_mins, 999)
        self.assertNotEqual(task.end_mins, 1059)

    def test_external_locked_task_blocks_machine_interval(self):
        external_order = _make_order("ORD-EXTERNAL-LOCKED")
        order = _make_order("ORD-AFTER-EXTERNAL")
        machine = _make_machine()
        locked_task = ScheduledTask(
            external_order,
            machine,
            start_mins=120,
            end_mins=240,
            setup_time=0,
            scrap_kg=0,
            sequence_index=0,
        )
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run([order], [machine], locked_tasks=[locked_task])

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE"})
        task = result.tasks[0]
        overlaps_locked = task.start_mins < locked_task.end_mins and task.end_mins > locked_task.start_mins
        self.assertFalse(overlaps_locked)

    def test_solver_metrics_record_locked_task_counts(self):
        locked_order = _make_order("ORD-LOCKED-METRIC")
        external_order = _make_order("ORD-EXTERNAL-METRIC")
        order = _make_order("ORD-METRIC-FREE")
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run(
            [locked_order, order],
            [machine],
            locked_tasks=[
                ScheduledTask(locked_order, machine, 120, 180, 120, 0, 0),
                ScheduledTask(external_order, machine, 240, 300, 0, 0, 0),
            ],
        )

        model_size = result.solver_metrics["model_size"]
        self.assertEqual(model_size["locked_order_count"], 1)
        self.assertEqual(model_size["external_locked_interval_count"], 1)

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

    def test_infeasible_order_returns_order_diagnostic(self):
        order = _make_order("ORD-WIDE", targetWidth=9999)
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run([order], [machine])

        self.assertEqual(result.status, "INFEASIBLE")
        self.assertEqual(result.tasks, [])
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(result.input_order_count, 1)
        self.assertEqual(result.schedulable_order_count, 0)
        self.assertEqual(result.blocked_order_count, 1)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "eligibility.width_out_of_range")

    def test_mixed_feasible_and_blocked_orders_returns_partial_schedule(self):
        feasible = _make_order("ORD-OK")
        blocked = _make_order("ORD-WIDE", targetWidth=9999)
        machine = _make_machine()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        result = aps.run([feasible, blocked], [machine])

        self.assertEqual(result.status, "PARTIAL")
        self.assertEqual(result.validation_errors, [])
        self.assertEqual(result.input_order_count, 2)
        self.assertEqual(result.schedulable_order_count, 1)
        self.assertEqual(result.blocked_order_count, 1)
        self.assertEqual([task.order.order_id for task in result.tasks], ["ORD-OK"])
        self.assertTrue(any(
            diagnostic.entity_id == "ORD-WIDE"
            and diagnostic.code == "eligibility.width_out_of_range"
            for diagnostic in result.diagnostics
        ))

    def test_phase2_fallback_diagnostic_is_structured(self):
        result = ScheduleResult()
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        aps._append_phase2_fallback_diagnostic(
            result,
            phase1_status="FEASIBLE",
            phase2_status="UNKNOWN",
            best_tardiness=123,
            order_count=5,
            machine_count=2,
        )

        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.code, "solver.phase2_fallback")
        self.assertEqual(diagnostic.category, "capacity")
        self.assertEqual(diagnostic.severity, "warning")
        self.assertTrue(any(item.metric == "phase2_status" and item.actual == "UNKNOWN" for item in diagnostic.evidence))

    def test_phase2_tardiness_bound_uses_tolerance_only_when_phase1_not_optimal(self):
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            solver_quality_policy={"phase2_feasible_tardiness_tolerance_mins": 30},
        )

        self.assertEqual(aps._phase2_tardiness_bound(120, "OPTIMAL"), 120)
        self.assertEqual(aps._phase2_tardiness_bound(120, "FEASIBLE"), 150)
        self.assertEqual(aps._phase2_tardiness_bound(120, "UNKNOWN"), 150)

    def test_candidate_order_can_be_deferred_without_invalidating_schedule(self):
        must = _make_order("ORD-MUST")
        candidate = _make_order(
            "ORD-CANDIDATE",
            planningBucket="candidate",
            materialAvailableMins=999999,
        )
        machine = _make_machine()
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            candidate_acceptance_policy={"reject_penalty": 1},
        )

        result = aps.run([must, candidate], [machine])

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE", "PARTIAL"})
        self.assertEqual(result.validation_errors, [])
        self.assertEqual([task.order.order_id for task in result.tasks], ["ORD-MUST"])
        self.assertEqual(result.input_order_count, 2)
        self.assertEqual(result.schedulable_order_count, 2)
        self.assertEqual(len(result.deferred_orders), 1)
        self.assertEqual(result.deferred_orders[0]["order_id"], "ORD-CANDIDATE")
        self.assertEqual(result.deferred_orders[0]["planning_bucket"], "candidate")
        self.assertIn("message", result.deferred_orders[0])

    def test_candidate_acceptance_policy_limits_deferred_count(self):
        must = _make_order("ORD-MUST-LIMIT")
        candidate_a = _make_order("ORD-CANDIDATE-A", planningBucket="candidate")
        candidate_b = _make_order("ORD-CANDIDATE-B", planningBucket="candidate")
        machine = _make_machine()
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            candidate_acceptance_policy={
                "reject_penalty": 0,
                "max_deferred_count": 1,
            },
        )

        self.assertEqual(aps.candidate_acceptance_policy["max_deferred_count"], 1)
        result = aps.run([must, candidate_a, candidate_b], [machine])

        self.assertIn(result.status, {"OPTIMAL", "FEASIBLE", "PARTIAL"})
        self.assertLessEqual(len(result.deferred_orders), 1)
        scheduled_candidate_ids = {
            task.order.order_id
            for task in result.tasks
            if task.order.planning_bucket == "candidate"
        }
        self.assertGreaterEqual(len(scheduled_candidate_ids), 1)

    def test_solver_profile_policy_sets_cp_sat_parameters(self):
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            solver_profile_policy={
                "profile": "fast",
                "time_limit_seconds": 3.5,
                "relative_gap_limit": 0.15,
                "random_seed": 42,
                "num_workers": 2,
                "log_search_progress": True,
            },
        )
        solver = SimpleNamespace(parameters=SimpleNamespace())

        aps._apply_solver_profile(solver)

        self.assertEqual(solver.parameters.max_time_in_seconds, 3.5)
        self.assertEqual(solver.parameters.relative_gap_limit, 0.15)
        self.assertEqual(solver.parameters.random_seed, 42)
        self.assertEqual(solver.parameters.num_workers, 2)
        self.assertTrue(solver.parameters.log_search_progress)

    def test_material_matrix_missing_diagnostic_is_structured(self):
        result = ScheduleResult()
        setup_mgr = _make_setup_mgr()
        setup_mgr.get_material_switch_time("RAW-A", "RAW-B")
        setup_mgr.get_material_switch_time("RAW-A", "RAW-B")
        aps = AdvancedMedicalAPS(setup_mgr)

        aps._append_material_matrix_diagnostic(result)

        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.code, "setup.material_switch_matrix_missing")
        self.assertEqual(diagnostic.category, "setup")
        self.assertTrue(any(item.metric == "fallback_lookup_count" and item.actual == 2 for item in diagnostic.evidence))

    def test_priority_override_replaces_default_tardiness_weight(self):
        order = _make_order(
            "ORD-PRIORITY",
            customerClass="VIP",
            orderClass="URGENT",
            priorityOverride=7,
        )
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        self.assertEqual(aps._tardiness_weight(order), 7)

    def test_continuous_run_diagnostic_flags_cleaning_need(self):
        result = ScheduleResult()
        machine = _make_machine(initialContinuousRunMins=4300)
        order = _make_order("ORD-CLEAN")
        result.add_task(ScheduledTask(order, machine, 30, 90, 30, 0, 0))
        aps = AdvancedMedicalAPS(_make_setup_mgr())

        aps._append_continuous_run_diagnostics(result)

        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.code, "maintenance.continuous_run_cleaning_required")
        self.assertEqual(diagnostic.entity_id, machine.machine_id)
        self.assertTrue(any(
            item.metric == "continuous_run_mins" and item.actual > 4320
            for item in diagnostic.evidence
        ))

    def test_continuous_run_policy_controls_limit_duration_and_level(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        machine = _make_machine(initialContinuousRunMins=0)
        order = _make_order("ORD-CLEAN-POLICY")
        result.add_task(ScheduledTask(order, machine, 0, 70, 0, 0, 0))
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            continuous_run_policy={
                "limit_mins": 60,
                "cleaning_mins": 15,
                "enforcement_mode": "publish_blocker",
            },
        )

        aps._append_continuous_run_diagnostics(result)

        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.severity, "critical")
        self.assertEqual(diagnostic.level, "publish_blocker")
        self.assertTrue(any(item.metric == "limit_mins" and item.actual == 60 for item in diagnostic.evidence))
        self.assertTrue(any(item.metric == "required_cleaning_mins" and item.actual == 15 for item in diagnostic.evidence))

    def test_publish_blocker_diagnostic_marks_result_unpublishable(self):
        result = ScheduleResult()
        result.status = "FEASIBLE"
        machine = _make_machine(initialContinuousRunMins=0)
        order = _make_order("ORD-CLEAN-STATUS")
        result.add_task(ScheduledTask(order, machine, 0, 70, 0, 0, 0))
        aps = AdvancedMedicalAPS(
            _make_setup_mgr(),
            continuous_run_policy={
                "limit_mins": 60,
                "cleaning_mins": 15,
                "enforcement_mode": "publish_blocker",
            },
        )

        aps._append_continuous_run_diagnostics(result)
        aps._apply_post_solve_diagnostic_status(result)

        self.assertEqual(result.status, "UNPUBLISHABLE")
        self.assertTrue(any("不可发布" in item for item in result.validation_errors))

    def test_decode_child_output_handles_gbk_logs(self):
        text = "订单 ORD-062 无可用机台: width=1718, thickness=80"
        self.assertEqual(_decode_child_output(text.encode("gbk")), text)


if __name__ == "__main__":
    unittest.main()
