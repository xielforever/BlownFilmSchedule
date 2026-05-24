import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from api.routers import schedule as schedule_router
from src import database
from src.models import BlownFilmMachineModel, ProductionOrderModel


class TestSchedulePolicySettings(unittest.TestCase):
    def test_policy_payload_exposes_global_constraint_switches(self):
        fields = schedule_router.ScheduleSettingsPayload.model_fields

        for key in [
            "material_constraint_enabled",
            "maintenance_constraint_enabled",
            "setup_rules_enabled",
            "cleanroom_constraint_enabled",
            "machine_capability_constraint_enabled",
            "due_date_optimization_enabled",
            "continuous_run_limit_mins",
            "continuous_run_enforcement_mode",
            "phase2_feasible_tardiness_tolerance_mins",
            "solver_profile",
            "solver_time_limit_seconds",
            "solver_relative_gap_limit",
            "solver_random_seed",
            "solver_num_workers",
            "solver_log_search_progress",
            "planning_must_schedule_horizon_days",
            "planning_candidate_horizon_days",
            "candidate_reject_penalty",
            "arc_pruning_enabled",
            "arc_pruning_max_setup_mins",
            "change_reason",
        ]:
            self.assertIn(key, fields)

    def test_continuous_run_policy_uses_settings_and_setup_matrix(self):
        setup_mgr = SimpleNamespace(continuous_run_cleaning_time=45)

        policy = schedule_router._continuous_run_policy(
            {
                **schedule_router.POLICY_DEFAULTS,
                "continuous_run_limit_mins": 240,
                "continuous_run_enforcement_mode": "hard",
            },
            setup_mgr,
        )

        self.assertEqual(policy["limit_mins"], 240)
        self.assertEqual(policy["cleaning_mins"], 45)
        self.assertEqual(policy["enforcement_mode"], "hard")

    def test_build_scheduler_passes_continuous_run_policy_to_solver(self):
        setup_mgr = SimpleNamespace(continuous_run_cleaning_time=55)

        with patch.object(schedule_router, "AdvancedMedicalAPS") as aps_cls:
            schedule_router._build_scheduler(
                setup_mgr,
                {
                    **schedule_router.POLICY_DEFAULTS,
                    "continuous_run_limit_mins": 180,
                    "continuous_run_enforcement_mode": "publish_blocker",
                    "phase2_feasible_tardiness_tolerance_mins": 20,
                    "solver_profile": "fast",
                    "solver_time_limit_seconds": 5.0,
                    "solver_relative_gap_limit": 0.2,
                    "solver_random_seed": 7,
                    "solver_num_workers": 2,
                    "solver_log_search_progress": True,
                    "candidate_reject_penalty": 1234,
                    "arc_pruning_enabled": True,
                    "arc_pruning_max_setup_mins": 240,
                },
            )

        aps_cls.assert_called_once_with(
            setup_mgr,
            continuous_run_policy={
                "limit_mins": 180,
                "cleaning_mins": 55,
                "enforcement_mode": "publish_blocker",
            },
            solver_quality_policy={
                "phase2_feasible_tardiness_tolerance_mins": 20,
            },
            solver_profile_policy={
                "profile": "fast",
                "time_limit_seconds": 5.0,
                "relative_gap_limit": 0.2,
                "random_seed": 7,
                "num_workers": 2,
                "log_search_progress": True,
            },
            candidate_acceptance_policy={
                "reject_penalty": 1234,
            },
            arc_pruning_policy={
                "enabled": True,
                "max_setup_time_mins": 240,
            },
        )

    def test_policy_snapshot_captures_continuous_run_strategy(self):
        snapshot = schedule_router._policy_snapshot(
            {
                **schedule_router.POLICY_DEFAULTS,
                "policy_version": 6,
                "continuous_run_limit_mins": 360,
                "continuous_run_enforcement_mode": "publish_blocker",
                "phase2_feasible_tardiness_tolerance_mins": 25,
                "solver_profile": "deep",
                "solver_time_limit_seconds": 180.0,
                "solver_relative_gap_limit": 0.01,
                "solver_random_seed": 11,
                "solver_num_workers": 4,
                "solver_log_search_progress": True,
                "planning_must_schedule_horizon_days": 5,
                "planning_candidate_horizon_days": 21,
                "candidate_reject_penalty": 4321,
                "arc_pruning_enabled": True,
                "arc_pruning_max_setup_mins": 180,
            },
            {},
        )

        self.assertEqual(snapshot["continuous_run"]["limit_mins"], 360)
        self.assertEqual(snapshot["continuous_run"]["enforcement_mode"], "publish_blocker")
        self.assertEqual(snapshot["solver_quality"]["phase2_feasible_tardiness_tolerance_mins"], 25)
        self.assertEqual(snapshot["solver_profile"]["profile"], "deep")
        self.assertEqual(snapshot["solver_profile"]["time_limit_seconds"], 180.0)
        self.assertEqual(snapshot["solver_profile"]["relative_gap_limit"], 0.01)
        self.assertEqual(snapshot["planning_bucket"]["must_schedule_horizon_days"], 5)
        self.assertEqual(snapshot["planning_bucket"]["candidate_horizon_days"], 21)
        self.assertEqual(snapshot["candidate_acceptance"]["reject_penalty"], 4321)
        self.assertEqual(snapshot["arc_pruning"]["enabled"], True)
        self.assertEqual(snapshot["arc_pruning"]["max_setup_time_mins"], 180)

    def test_policy_snapshot_captures_version_settings_and_rule_counts(self):
        snapshot = schedule_router._policy_snapshot(
            {
                "policy_version": 3,
                "review_required": True,
                "manual_adjust_enabled": False,
                "material_constraint_enabled": True,
                "maintenance_constraint_enabled": False,
                "setup_rules_enabled": True,
                "cleanroom_constraint_enabled": True,
                "machine_capability_constraint_enabled": True,
                "due_date_optimization_enabled": True,
            },
            {
                "material_switch": {"enabled": 2, "disabled": 1},
                "gmp_clearance": {"enabled": 1, "disabled": 0},
            },
        )

        self.assertEqual(snapshot["policy_version"], 3)
        self.assertFalse(snapshot["settings"]["manual_adjust_enabled"])
        self.assertFalse(snapshot["settings"]["maintenance_constraint_enabled"])
        self.assertEqual(snapshot["enabled_rule_counts"]["material_switch"]["enabled"], 2)
        self.assertEqual(snapshot["runtime_rule_source"], "db_only")
        self.assertFalse(snapshot["fallback_setup_used"])

    def test_policy_update_requires_non_empty_change_reason(self):
        with self.assertRaises(schedule_router.HTTPException) as raised:
            schedule_router._require_policy_change_reason("  ")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("变更原因", raised.exception.detail)
        self.assertEqual(schedule_router._require_policy_change_reason("  产线切换验证  "), "产线切换验证")

    def test_config_audit_rows_are_serialized_for_api(self):
        row = schedule_router._config_audit_row_to_dict({
            "id": 7,
            "config_scope": "schedule_policy",
            "config_key": "maintenance_constraint_enabled",
            "entity_id": "global",
            "before_state": {"maintenance_constraint_enabled": True},
            "after_state": {"maintenance_constraint_enabled": False},
            "changed_by": "planner",
            "reason_text": "临时诊断维护窗口影响",
            "created_at": datetime(2026, 5, 23, 9, 30),
        })

        self.assertEqual(row["id"], 7)
        self.assertEqual(row["scope_label"], "全局策略")
        self.assertEqual(row["created_at"], "2026-05-23T09:30:00")
        self.assertEqual(row["reason_text"], "临时诊断维护窗口影响")

    def test_policy_snapshot_mismatch_detects_version_setting_and_rule_changes(self):
        base = schedule_router._policy_snapshot(
            {
                "policy_version": 3,
                "review_required": True,
                "manual_adjust_enabled": True,
                "material_constraint_enabled": True,
                "maintenance_constraint_enabled": True,
                "setup_rules_enabled": True,
                "cleanroom_constraint_enabled": True,
                "machine_capability_constraint_enabled": True,
                "due_date_optimization_enabled": True,
            },
            {"spec_change": {"enabled": 4, "disabled": 0}},
        )

        same = schedule_router._policy_snapshot(
            {
                "policy_version": 3,
                "review_required": True,
                "manual_adjust_enabled": True,
                "material_constraint_enabled": True,
                "maintenance_constraint_enabled": True,
                "setup_rules_enabled": True,
                "cleanroom_constraint_enabled": True,
                "machine_capability_constraint_enabled": True,
                "due_date_optimization_enabled": True,
            },
            {"spec_change": {"enabled": 4, "disabled": 0}},
        )
        changed = schedule_router._policy_snapshot(
            {
                "policy_version": 4,
                "review_required": True,
                "manual_adjust_enabled": True,
                "material_constraint_enabled": True,
                "maintenance_constraint_enabled": False,
                "setup_rules_enabled": True,
                "cleanroom_constraint_enabled": True,
                "machine_capability_constraint_enabled": True,
                "due_date_optimization_enabled": True,
            },
            {"spec_change": {"enabled": 3, "disabled": 1}},
        )

        self.assertIsNone(schedule_router._policy_snapshot_mismatch(base, same))
        message = schedule_router._policy_snapshot_mismatch(base, changed)
        self.assertIn("全局策略", message)
        self.assertIn("重新预排", message)

    def test_stale_policy_snapshot_becomes_blocking_validation_item(self):
        saved = schedule_router._policy_snapshot(
            {**schedule_router.POLICY_DEFAULTS, "policy_version": 2},
            {"material_switch": {"enabled": 2, "disabled": 0}},
        )
        current = schedule_router._policy_snapshot(
            {**schedule_router.POLICY_DEFAULTS, "policy_version": 3},
            {"material_switch": {"enabled": 2, "disabled": 0}},
        )

        item = schedule_router._policy_snapshot_validation_item(saved, current)

        self.assertEqual(item["severity"], "error")
        self.assertEqual(item["code"], "policy_snapshot_stale")
        self.assertIn("重新预排", item["message"])

    def test_stale_input_snapshot_becomes_blocking_validation_item(self):
        saved = {
            "hash": "input-v1",
            "machine_capability": {"hash": "machine-v1"},
            "maintenance_calendar": {"hash": "calendar-v1"},
            "rule_matrix": {"hash": "rules-v1"},
            "process": {"hash": "process-v1"},
            "screening": {"hash": "screening-v1"},
        }
        current = {
            **saved,
            "hash": "input-v2",
            "machine_capability": {"hash": "machine-v2"},
        }

        item = schedule_router._input_snapshot_validation_item(saved, current)

        self.assertEqual(item["severity"], "error")
        self.assertEqual(item["code"], "input_snapshot_stale")
        self.assertIn("机台能力", item["message"])
        self.assertIn("重新预排", item["message"])

    def test_current_input_snapshot_uses_saved_preplan_screening_snapshot(self):
        screening = {
            "generated_at": "2026-05-24T09:00:00",
            "items": [
                {"order_id": "ORD-001", "screening_status": "ready", "reasons": []},
            ],
            "summary": {"ready": 1, "risk": 0, "blocked": 0},
        }
        order_snapshots = [
            {"order_id": "ORD-001", "hash": "order-v1"},
        ]

        snapshot = schedule_router._screening_snapshot_for_input_snapshot(screening, order_snapshots)

        self.assertEqual(snapshot, schedule_router.build_screening_snapshot(screening))

    def test_manual_adjustment_validation_respects_global_policy_switches(self):
        payload = SimpleNamespace(
            order_id="ORD-POLICY",
            machine_id="BF-01",
            start_time=datetime(2026, 5, 23, 8, 0),
        )
        ctx = {
            "status": "PENDING",
            "machine_status": "ACTIVE",
            "min_width": 100,
            "target_width": 2600,
            "max_width": 1500,
            "min_thickness": 10,
            "target_thickness": 250,
            "max_thickness": 120,
            "cleanroom_req": "Class_10K",
            "cleanroom_level": "Class_100K",
            "recipe_layers": 7,
            "layer_structure": 5,
            "material_available_time": datetime(2026, 5, 23, 10, 0),
        }

        disabled_policy = {
            **schedule_router.POLICY_DEFAULTS,
            "machine_capability_constraint_enabled": False,
            "cleanroom_constraint_enabled": False,
            "material_constraint_enabled": False,
        }
        disabled_codes = {
            item["code"]
            for item in schedule_router._manual_adjustment_policy_items(ctx, payload, disabled_policy)
        }

        self.assertNotIn("width_capacity", disabled_codes)
        self.assertNotIn("thickness_capacity", disabled_codes)
        self.assertNotIn("layer_capacity", disabled_codes)
        self.assertNotIn("cleanroom_capacity", disabled_codes)
        self.assertNotIn("material_not_ready", disabled_codes)

        enabled_codes = {
            item["code"]
            for item in schedule_router._manual_adjustment_policy_items(
                ctx,
                payload,
                {**schedule_router.POLICY_DEFAULTS},
            )
        }
        self.assertIn("width_capacity", enabled_codes)
        self.assertIn("thickness_capacity", enabled_codes)
        self.assertIn("layer_capacity", enabled_codes)
        self.assertIn("cleanroom_capacity", enabled_codes)
        self.assertIn("material_not_ready", enabled_codes)

    def test_schedule_policy_is_applied_to_in_memory_master_data(self):
        machine = BlownFilmMachineModel(
            machine_id="BF-01",
            name="BF-01",
            cleanroom_level="Class_100K",
            layer_structure=3,
            die_diameter_mm=300,
            min_width=100,
            max_width=1500,
            min_thickness=20,
            max_thickness=80,
            hourly_output_kg=100,
            max_slitting_lanes=4,
        )
        order = ProductionOrderModel(
            order_id="ORD-POLICY",
            product_type="Film-A",
            target_width=1800,
            target_thickness=120,
            total_quantity_kg=1000,
            cleanroom_req="Class_10K",
            customer_class="STANDARD",
            order_class="URGENT",
            corona_req=False,
            core_size_inch=3,
            due_date_mins=120,
            material_available_mins=60,
            priority_override=8,
            recipe_materials=["A", "B", "C", "D", "E"],
        )

        database._apply_schedule_policy_to_master_data(
            [machine],
            [order],
            {
                "material_constraint_enabled": False,
                "cleanroom_constraint_enabled": False,
                "machine_capability_constraint_enabled": False,
                "due_date_optimization_enabled": False,
            },
        )

        self.assertEqual(order.material_available_mins, 0)
        self.assertEqual(order.cleanroom_req, "Class_100K")
        self.assertEqual(order.priority_override, 0)
        self.assertGreaterEqual(machine.max_width, order.target_width)
        self.assertGreaterEqual(machine.max_thickness, order.target_thickness)
        self.assertGreaterEqual(machine.layer_structure, len(order.recipe_materials))

    def test_solver_params_include_policy_snapshot_when_present(self):
        result = type("Result", (), {
            "input_order_count": 2,
            "schedulable_order_count": 1,
            "blocked_order_count": 1,
            "solver_metrics": {"phase_1": {"status": "OPTIMAL", "gap": 0.0}},
        })()
        snapshot = {"policy_version": 5, "settings": {"review_required": True}}
        input_snapshot = {"hash": "input-v1", "orders": {"count": 2}}
        screening_snapshot = {
            "summary": {"ready_count": 1, "risk_count": 1, "blocked_count": 0},
            "items": [{"order_id": "ORD-1", "screening_status": "ready"}],
        }

        params = database._build_schedule_run_solver_params(
            result=result,
            diagnostics_payload=[],
            normalized_order_ids=["ORD-1", "ORD-2"],
            order_snapshots=[],
            mode="AUTO",
            policy_snapshot=snapshot,
            input_snapshot=input_snapshot,
            screening_snapshot=screening_snapshot,
        )

        self.assertEqual(params["policy_snapshot"], snapshot)
        self.assertEqual(params["input_snapshot"], input_snapshot)
        self.assertEqual(params["preplan_screening"], screening_snapshot)
        self.assertEqual(params["solver_metrics"], result.solver_metrics)
        self.assertEqual(params["summary"]["input_order_count"], 2)

    def test_run_row_to_dict_exposes_preplan_screening_snapshot(self):
        screening_snapshot = {
            "summary": {"ready_count": 1, "risk_count": 0, "blocked_count": 0},
            "items": [{"order_id": "ORD-READY", "screening_status": "ready"}],
        }
        row = {
            "run_id": 42,
            "run_time": None,
            "baseline_time": None,
            "triggered_by": "planner",
            "status": "FEASIBLE",
            "mode": "AUTO",
            "lifecycle_status": "DRAFT",
            "total_orders": 1,
            "total_machines_used": 1,
            "total_setup_time_mins": 0,
            "total_scrap_kg": 0,
            "total_late_orders": 0,
            "is_active": False,
            "solver_params": {
                "selected_order_ids": ["ORD-READY"],
                "preplan_screening": screening_snapshot,
            },
            "confirmed_by": None,
            "confirmed_at": None,
            "cancelled_by": None,
            "cancelled_at": None,
            "cancel_reason": None,
        }

        data = schedule_router._run_row_to_dict(row)

        self.assertEqual(data["preplan_screening"], screening_snapshot)

    def test_task_row_to_dict_exposes_prev_order_and_setup_detail(self):
        row = {
            "id": 1,
            "run_id": 10,
            "order_id": "ORD-009",
            "machine_id": "LINE-01",
            "sequence_index": 1,
            "setup_start_time": datetime(2026, 5, 17, 22, 30),
            "start_time": datetime(2026, 5, 17, 23, 50),
            "end_time": datetime(2026, 5, 18, 14, 50),
            "duration_mins": 900,
            "setup_time_mins": 80,
            "setup_detail": {
                "total_mins": 80,
                "components": [{"category": "width", "minutes": 40}],
            },
            "scrap_kg": 0,
            "net_weight_kg": 1800,
            "actual_material_required_kg": 1800,
            "is_late": False,
            "tardiness_mins": 0,
            "prev_order_id": "ORD-001",
            "task_source": "AUTO",
            "manual_lock_machine": False,
            "manual_lock_time": False,
            "product_type": "Medical Film",
            "target_width": 420,
            "target_thickness": 45,
            "total_quantity_kg": 1800,
            "order_class": "NORMAL",
            "due_date": datetime(2026, 5, 22, 18, 0),
        }

        data = schedule_router._task_row_to_dict(row)

        self.assertEqual(data["prev_order_id"], "ORD-001")
        self.assertEqual(data["setup_detail"]["total_mins"], 80)
        self.assertEqual(data["setup_detail"]["components"][0]["category"], "width")

    def test_locked_task_rows_become_solver_locked_inputs(self):
        order = ProductionOrderModel(
            order_id="ORD-LOCKED-API",
            product_type="Film-A",
            target_width=520,
            target_thickness=35,
            total_quantity_kg=1200,
            cleanroom_req="Class_10K",
            customer_class="STANDARD",
            order_class="NORMAL",
            corona_req=False,
            core_size_inch=3,
            due_date_mins=1440,
            recipe_materials=["L1", "L2", "L3"],
        )
        machine = BlownFilmMachineModel(
            machine_id="LINE-A",
            name="LINE-A",
            cleanroom_level="Class_10K",
            layer_structure=5,
            die_diameter_mm=300,
            min_width=100,
            max_width=1500,
            min_thickness=20,
            max_thickness=80,
            hourly_output_kg=600,
            max_slitting_lanes=4,
        )

        locked_tasks = schedule_router._locked_task_rows_to_solver_inputs(
            [
                {
                    "order_id": "ORD-LOCKED-API",
                    "machine_id": "LINE-A",
                    "start_mins": 120,
                    "end_mins": 240,
                    "setup_time_mins": 30,
                    "scrap_kg": 2,
                    "sequence_index": 3,
                    "manual_lock_machine": True,
                    "manual_lock_time": False,
                },
                {
                    "order_id": "ORD-EXTERNAL-API",
                    "machine_id": "LINE-A",
                    "start_mins": 300,
                    "end_mins": 420,
                    "setup_time_mins": 0,
                    "scrap_kg": 0,
                    "sequence_index": 4,
                    "manual_lock_machine": True,
                    "manual_lock_time": True,
                },
            ],
            orders=[order],
            machines=[machine],
        )

        self.assertEqual([task.order.order_id for task in locked_tasks], ["ORD-LOCKED-API", "ORD-EXTERNAL-API"])
        self.assertIs(locked_tasks[0].order, order)
        self.assertIs(locked_tasks[0].machine, machine)
        self.assertEqual(locked_tasks[0].start_mins, 120)
        self.assertEqual(locked_tasks[0].end_mins, 240)
        self.assertTrue(locked_tasks[0].manual_lock_machine)
        self.assertFalse(locked_tasks[0].manual_lock_time)
        self.assertEqual(locked_tasks[1].order.product_type, "LOCKED_EXTERNAL")
        self.assertTrue(locked_tasks[1].manual_lock_time)

    def test_manual_adjustment_impact_summarizes_move_cost(self):
        impact = schedule_router._manual_adjustment_impact(
            {
                "machine_id": "LINE-A",
                "start_time": "2026-05-17T08:00:00",
                "end_time": "2026-05-17T10:00:00",
                "setup_time_mins": 20,
                "tardiness_mins": 0,
                "manual_lock_machine": False,
                "manual_lock_time": False,
            },
            {
                "machine_id": "LINE-B",
                "start_time": "2026-05-17T09:30:00",
                "end_time": "2026-05-17T12:15:00",
                "setup_time_mins": 50,
                "tardiness_mins": 45,
                "lock_machine": True,
                "lock_time": True,
            },
        )

        self.assertTrue(impact["machine_changed"])
        self.assertEqual(impact["from_machine_id"], "LINE-A")
        self.assertEqual(impact["to_machine_id"], "LINE-B")
        self.assertEqual(impact["start_delta_mins"], 90)
        self.assertEqual(impact["end_delta_mins"], 135)
        self.assertEqual(impact["duration_delta_mins"], 45)
        self.assertEqual(impact["setup_time_delta_mins"], 30)
        self.assertEqual(impact["tardiness_delta_mins"], 45)
        self.assertTrue(impact["lock_machine"])
        self.assertTrue(impact["lock_time"])

    def test_manual_adjustment_impact_summary_totals_adjustment_cost(self):
        summary = schedule_router._manual_adjustment_impact_summary([
            {
                "order_id": "ORD-A",
                "impact": {
                    "machine_changed": True,
                    "start_delta_mins": 90,
                    "end_delta_mins": 120,
                    "duration_delta_mins": 30,
                    "setup_time_delta_mins": 40,
                    "tardiness_delta_mins": 45,
                    "lock_machine": True,
                    "lock_time": False,
                },
            },
            {
                "order_id": "ORD-B",
                "impact": {
                    "machine_changed": False,
                    "start_delta_mins": -30,
                    "end_delta_mins": -15,
                    "duration_delta_mins": 15,
                    "setup_time_delta_mins": -10,
                    "tardiness_delta_mins": -20,
                    "lock_machine": False,
                    "lock_time": True,
                },
            },
        ])

        self.assertEqual(summary["adjustment_count"], 2)
        self.assertEqual(summary["machine_change_count"], 1)
        self.assertEqual(summary["time_changed_count"], 2)
        self.assertEqual(summary["locked_after_adjustment_count"], 2)
        self.assertEqual(summary["total_setup_time_delta_mins"], 30)
        self.assertEqual(summary["total_tardiness_delta_mins"], 25)
        self.assertEqual(summary["max_delay_delta_mins"], 120)
        self.assertEqual(summary["affected_order_ids"], ["ORD-A", "ORD-B"])

    def test_locked_task_summary_lists_protected_orders(self):
        summary = schedule_router._locked_task_summary([
            {
                "order_id": "ORD-MACHINE-LOCK",
                "machine_id": "LINE-A",
                "manual_lock_machine": True,
                "manual_lock_time": False,
            },
            {
                "order_id": "ORD-TIME-LOCK",
                "machine_id": "LINE-B",
                "manual_lock_machine": False,
                "manual_lock_time": True,
            },
            {
                "order_id": "ORD-FREE",
                "machine_id": "LINE-C",
                "manual_lock_machine": False,
                "manual_lock_time": False,
            },
        ])

        self.assertEqual(summary["locked_task_count"], 2)
        self.assertEqual(summary["machine_locked_count"], 1)
        self.assertEqual(summary["time_locked_count"], 1)
        self.assertEqual(summary["protected_order_ids"], ["ORD-MACHINE-LOCK", "ORD-TIME-LOCK"])
        self.assertEqual(summary["protected_machine_ids"], ["LINE-A", "LINE-B"])


if __name__ == "__main__":
    unittest.main()
