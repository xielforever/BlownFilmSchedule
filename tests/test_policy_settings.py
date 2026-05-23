import unittest
from datetime import datetime
from types import SimpleNamespace

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
            "change_reason",
        ]:
            self.assertIn(key, fields)

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
        })()
        snapshot = {"policy_version": 5, "settings": {"review_required": True}}

        params = database._build_schedule_run_solver_params(
            result=result,
            diagnostics_payload=[],
            normalized_order_ids=["ORD-1", "ORD-2"],
            order_snapshots=[],
            mode="AUTO",
            policy_snapshot=snapshot,
        )

        self.assertEqual(params["policy_snapshot"], snapshot)
        self.assertEqual(params["summary"]["input_order_count"], 2)

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


if __name__ == "__main__":
    unittest.main()
