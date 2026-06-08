import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from api.routers import schedule as schedule_router
from src import database
from src.models import BlownFilmMachineModel, ProductionOrderModel


class TestSchedulePolicySettings(unittest.TestCase):
    def test_database_manager_planning_schema_creates_policy_audit_contract(self):
        class Cursor:
            def __init__(self):
                self.sql = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                self.sql.append(sql)

        class Conn:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.commits = 0

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.commits += 1

        manager = object.__new__(database.DatabaseManager)
        manager.conn = Conn()

        manager.ensure_planning_schema()

        ddl = "\n".join(manager.conn.cursor_obj.sql)
        for key in [
            "policy_version",
            "updated_by",
            "change_reason",
            "config_change_audit",
            "idx_config_change_audit_created",
        ]:
            self.assertIn(key, ddl)
        self.assertEqual(manager.conn.commits, 1)

    def test_database_manager_planning_schema_declares_global_constraint_switches(self):
        class Cursor:
            def __init__(self):
                self.sql = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql):
                self.sql.append(sql)

        class Conn:
            def __init__(self):
                self.cursor_obj = Cursor()

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                pass

        manager = object.__new__(database.DatabaseManager)
        manager.conn = Conn()

        manager.ensure_planning_schema()

        ddl = "\n".join(manager.conn.cursor_obj.sql)
        for key in [
            "material_constraint_enabled",
            "maintenance_constraint_enabled",
            "setup_rules_enabled",
            "cleanroom_constraint_enabled",
            "machine_capability_constraint_enabled",
            "due_date_optimization_enabled",
        ]:
            self.assertIn(key, ddl)

    def test_database_policy_loader_exposes_candidate_acceptance_limits(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def execute(self, sql):
                self.sql = sql

            def fetchone(self):
                return {
                    "candidate_max_deferred_count": 3,
                    "candidate_min_acceptance_ratio": 0.6,
                }

        cur = Cursor()
        manager = object.__new__(database.DatabaseManager)

        policy = manager._load_schedule_policy(cur)

        self.assertIn("candidate_max_deferred_count", cur.sql)
        self.assertIn("candidate_min_acceptance_ratio", cur.sql)
        self.assertEqual(policy["candidate_max_deferred_count"], 3)
        self.assertEqual(policy["candidate_min_acceptance_ratio"], 0.6)

    def test_database_policy_loader_exposes_business_bucket_rules(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def execute(self, sql):
                self.sql = sql

            def fetchone(self):
                return {
                    "planning_material_ready_horizon_days": 10,
                    "planning_force_must_order_classes": ["URGENT", "SAMPLE"],
                    "planning_force_must_customer_classes": ["VIP"],
                    "planning_scarce_machine_threshold": 2,
                }

        cur = Cursor()
        manager = object.__new__(database.DatabaseManager)

        policy = manager._load_schedule_policy(cur)

        for key in [
            "planning_material_ready_horizon_days",
            "planning_force_must_order_classes",
            "planning_force_must_customer_classes",
            "planning_scarce_machine_threshold",
        ]:
            self.assertIn(key, cur.sql)
            self.assertIn(key, policy)
        self.assertEqual(policy["planning_material_ready_horizon_days"], 10)
        self.assertEqual(policy["planning_force_must_order_classes"], ["URGENT", "SAMPLE"])
        self.assertEqual(policy["planning_force_must_customer_classes"], ["VIP"])
        self.assertEqual(policy["planning_scarce_machine_threshold"], 2)

    def test_database_fresh_schema_declares_candidate_acceptance_limits(self):
        with open(database.DDL_PATH, encoding="utf-8") as schema:
            ddl = schema.read()

        self.assertIn("candidate_max_deferred_count", ddl)
        self.assertIn("candidate_min_acceptance_ratio", ddl)
        self.assertIn("planning_material_ready_horizon_days", ddl)
        self.assertIn("planning_force_must_order_classes", ddl)
        self.assertIn("planning_force_must_customer_classes", ddl)
        self.assertIn("planning_scarce_machine_threshold", ddl)

    def test_database_policy_loader_exposes_screening_and_review_strategy(self):
        class Cursor:
            def __init__(self):
                self.sql = ""

            def execute(self, sql):
                self.sql = sql

            def fetchone(self):
                return {
                    "screening_allowed_order_statuses": ["PENDING", "RELEASED"],
                    "screening_prohibited_override_codes": ["no_eligible_machine"],
                    "screening_restricted_override_codes": ["material_not_ready"],
                    "screening_required_positive_order_fields": ["target_width"],
                    "manual_adjust_review_delay_threshold_mins": 45,
                    "manual_adjust_review_setup_threshold_mins": 30,
                    "manual_adjust_review_tardiness_threshold_mins": 20,
                }

        cur = Cursor()
        manager = object.__new__(database.DatabaseManager)

        policy = manager._load_schedule_policy(cur)

        for key in [
            "screening_allowed_order_statuses",
            "screening_prohibited_override_codes",
            "screening_restricted_override_codes",
            "screening_required_positive_order_fields",
            "manual_adjust_review_delay_threshold_mins",
            "manual_adjust_review_setup_threshold_mins",
            "manual_adjust_review_tardiness_threshold_mins",
        ]:
            self.assertIn(key, cur.sql)
            self.assertIn(key, policy)

        self.assertEqual(policy["screening_allowed_order_statuses"], ["PENDING", "RELEASED"])
        self.assertEqual(policy["manual_adjust_review_delay_threshold_mins"], 45)

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
            "planning_material_ready_horizon_days",
            "planning_force_must_order_classes",
            "planning_force_must_customer_classes",
            "planning_scarce_machine_threshold",
            "candidate_reject_penalty",
            "candidate_max_deferred_count",
            "candidate_min_acceptance_ratio",
            "arc_pruning_enabled",
            "arc_pruning_max_setup_mins",
            "arc_pruning_top_k_per_order",
            "arc_pruning_same_material_family_top_k",
            "arc_pruning_same_cleanroom_top_k",
            "arc_pruning_due_window_mins",
            "arc_pruning_due_window_top_k",
            "screening_due_risk_min_slack_mins",
            "screening_due_risk_duration_multiplier",
            "screening_allowed_order_statuses",
            "screening_prohibited_override_codes",
            "screening_restricted_override_codes",
            "screening_required_positive_order_fields",
            "manual_adjust_review_delay_threshold_mins",
            "manual_adjust_review_setup_threshold_mins",
            "manual_adjust_review_tardiness_threshold_mins",
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

    def test_order_screening_policy_uses_settings_for_preplan_admission(self):
        policy = schedule_router._order_screening_policy({
            **schedule_router.POLICY_DEFAULTS,
            "screening_due_risk_min_slack_mins": 360,
            "screening_due_risk_duration_multiplier": 2.5,
            "screening_allowed_order_statuses": ["PENDING", "RELEASED"],
            "screening_prohibited_override_codes": ["no_eligible_machine"],
            "screening_restricted_override_codes": ["material_not_ready", "due_risk"],
            "screening_required_positive_order_fields": ["target_width", "total_quantity_kg"],
        })

        self.assertEqual(policy["due_risk_min_slack_mins"], 360)
        self.assertEqual(policy["due_risk_duration_multiplier"], 2.5)
        self.assertEqual(policy["allowed_order_statuses"], ["PENDING", "RELEASED"])
        self.assertEqual(policy["prohibited_override_codes"], ["no_eligible_machine"])
        self.assertEqual(policy["restricted_override_codes"], ["material_not_ready", "due_risk"])
        self.assertEqual(policy["required_positive_order_fields"], ["target_width", "total_quantity_kg"])

    def test_order_screening_policy_normalizes_override_codes_for_audit_snapshot(self):
        settings = {
            **schedule_router.POLICY_DEFAULTS,
            "screening_allowed_order_statuses": [" pending ", "released", "PENDING"],
            "screening_prohibited_override_codes": [" NO_ELIGIBLE_MACHINE ", "due_risk"],
            "screening_restricted_override_codes": ["due_risk", " MATERIAL_NOT_READY "],
            "screening_required_positive_order_fields": [" total_quantity_kg ", "target_width", "target_width"],
        }

        policy = schedule_router._order_screening_policy(settings)
        snapshot = schedule_router._policy_snapshot(settings, {})

        self.assertEqual(policy["allowed_order_statuses"], ["PENDING", "RELEASED"])
        self.assertEqual(policy["prohibited_override_codes"], ["no_eligible_machine", "due_risk"])
        self.assertEqual(policy["restricted_override_codes"], ["material_not_ready"])
        self.assertEqual(snapshot["order_screening"]["allowed_order_statuses"], ["PENDING", "RELEASED"])
        self.assertEqual(snapshot["order_screening"]["prohibited_override_codes"], ["no_eligible_machine", "due_risk"])
        self.assertEqual(snapshot["order_screening"]["restricted_override_codes"], ["material_not_ready"])
        self.assertEqual(snapshot["order_screening"]["required_positive_order_fields"], [
            "total_quantity_kg",
            "target_width",
        ])

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
                    "candidate_max_deferred_count": 2,
                    "candidate_min_acceptance_ratio": 0.5,
                    "arc_pruning_enabled": True,
                    "arc_pruning_max_setup_mins": 240,
                    "arc_pruning_top_k_per_order": 3,
                    "arc_pruning_same_material_family_top_k": 2,
                    "arc_pruning_same_cleanroom_top_k": 2,
                    "arc_pruning_due_window_mins": 1440,
                    "arc_pruning_due_window_top_k": 4,
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
                "phase1_tardiness_weight": 10000,
                "phase1_late_order_penalty": 0,
                "phase2_tardiness_weight": 0,
                "max_late_order_count": None,
                "max_weighted_tardiness": None,
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
                "max_deferred_count": 2,
                "min_acceptance_ratio": 0.5,
                "post_solve_late_defer_count": 0,
            },
            arc_pruning_policy={
                "enabled": True,
                "max_setup_time_mins": 240,
                "top_k_per_order": 3,
                "same_material_family_top_k": 2,
                "same_cleanroom_top_k": 2,
                "due_window_mins": 1440,
                "due_window_top_k": 4,
            },
            tardiness_weights={
                "vip_urgent": 100,
                "high": 50,
                "normal": 10,
                "sample": 80,
            },
            scrap_weights={
                "material_change": 25.0,
                "same_material": 5.0,
                "width_change": 15.0,
                "thickness_change": 10.0,
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
                "planning_material_ready_horizon_days": 13,
                "planning_force_must_order_classes": ["URGENT"],
                "planning_force_must_customer_classes": ["VIP"],
                "planning_scarce_machine_threshold": 1,
                "candidate_reject_penalty": 4321,
                "candidate_max_deferred_count": 2,
                "candidate_min_acceptance_ratio": 0.5,
                "arc_pruning_enabled": True,
                "arc_pruning_max_setup_mins": 180,
                "arc_pruning_top_k_per_order": 2,
                "arc_pruning_same_material_family_top_k": 1,
                "arc_pruning_same_cleanroom_top_k": 1,
                "arc_pruning_due_window_mins": 720,
                "arc_pruning_due_window_top_k": 3,
                "screening_due_risk_min_slack_mins": 300,
                "screening_due_risk_duration_multiplier": 2.0,
                "screening_allowed_order_statuses": ["PENDING", "RELEASED"],
                "screening_prohibited_override_codes": ["no_eligible_machine"],
                "screening_restricted_override_codes": ["material_not_ready"],
                "screening_required_positive_order_fields": ["due_date_mins", "total_quantity_kg"],
                "manual_adjust_review_delay_threshold_mins": 30,
                "manual_adjust_review_setup_threshold_mins": 20,
                "manual_adjust_review_tardiness_threshold_mins": 15,
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
        self.assertEqual(snapshot["planning_bucket"]["material_ready_horizon_days"], 13)
        self.assertEqual(snapshot["planning_bucket"]["force_must_order_classes"], ["URGENT"])
        self.assertEqual(snapshot["planning_bucket"]["force_must_customer_classes"], ["VIP"])
        self.assertEqual(snapshot["planning_bucket"]["scarce_machine_threshold"], 1)
        self.assertEqual(snapshot["candidate_acceptance"]["reject_penalty"], 4321)
        self.assertEqual(snapshot["candidate_acceptance"]["max_deferred_count"], 2)
        self.assertEqual(snapshot["candidate_acceptance"]["min_acceptance_ratio"], 0.5)
        self.assertEqual(snapshot["arc_pruning"]["enabled"], True)
        self.assertEqual(snapshot["arc_pruning"]["max_setup_time_mins"], 180)
        self.assertEqual(snapshot["arc_pruning"]["top_k_per_order"], 2)
        self.assertEqual(snapshot["arc_pruning"]["same_material_family_top_k"], 1)
        self.assertEqual(snapshot["arc_pruning"]["same_cleanroom_top_k"], 1)
        self.assertEqual(snapshot["arc_pruning"]["due_window_mins"], 720)
        self.assertEqual(snapshot["arc_pruning"]["due_window_top_k"], 3)
        self.assertEqual(snapshot["order_screening"]["due_risk_min_slack_mins"], 300)
        self.assertEqual(snapshot["order_screening"]["due_risk_duration_multiplier"], 2.0)
        self.assertEqual(snapshot["order_screening"]["allowed_order_statuses"], ["PENDING", "RELEASED"])
        self.assertEqual(snapshot["order_screening"]["prohibited_override_codes"], ["no_eligible_machine"])
        self.assertEqual(snapshot["order_screening"]["restricted_override_codes"], ["material_not_ready"])
        self.assertEqual(snapshot["order_screening"]["required_positive_order_fields"], [
            "due_date_mins",
            "total_quantity_kg",
        ])
        self.assertEqual(snapshot["manual_adjustment_review"]["delay_threshold_mins"], 30)
        self.assertEqual(snapshot["manual_adjustment_review"]["setup_threshold_mins"], 20)
        self.assertEqual(snapshot["manual_adjustment_review"]["tardiness_threshold_mins"], 15)

    def test_policy_snapshot_allows_empty_force_must_bucket_lists(self):
        snapshot = schedule_router._policy_snapshot(
            {
                **schedule_router.POLICY_DEFAULTS,
                "planning_force_must_order_classes": [],
                "planning_force_must_customer_classes": [],
            },
            {},
        )

        self.assertEqual(snapshot["planning_bucket"]["force_must_order_classes"], [])
        self.assertEqual(snapshot["planning_bucket"]["force_must_customer_classes"], [])

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

    def test_experimental_continuous_run_mode_requires_admin(self):
        with self.assertRaises(schedule_router.HTTPException) as raised:
            schedule_router._require_high_risk_policy_permission(
                SimpleNamespace(username="planner", role="planner"),
                {"continuous_run_enforcement_mode": "experimental_disabled"},
            )

        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn("管理员", raised.exception.detail)
        schedule_router._require_high_risk_policy_permission(
            SimpleNamespace(username="admin", role="admin"),
            {"continuous_run_enforcement_mode": "experimental_disabled"},
        )

    def test_disabling_hard_policy_switches_requires_admin(self):
        for key in schedule_router.ADMIN_ONLY_DISABLE_POLICY_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(schedule_router.HTTPException) as raised:
                    schedule_router._require_high_risk_policy_permission(
                        SimpleNamespace(username="planner", role="planner"),
                        {key: False},
                    )

                self.assertEqual(raised.exception.status_code, 403)
                self.assertIn("管理员", raised.exception.detail)

                schedule_router._require_high_risk_policy_permission(
                    SimpleNamespace(username="admin", role="admin"),
                    {key: False},
                )

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

    def test_policy_snapshot_mismatch_detects_order_screening_policy_change(self):
        saved = schedule_router._policy_snapshot(
            {**schedule_router.POLICY_DEFAULTS, "policy_version": 3},
            {},
        )
        current = schedule_router._policy_snapshot(
            {
                **schedule_router.POLICY_DEFAULTS,
                "policy_version": 3,
                "screening_due_risk_min_slack_mins": 360,
            },
            {},
        )

        message = schedule_router._policy_snapshot_mismatch(saved, current)

        self.assertIn("订单初筛策略", message)
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

    def test_schedule_policy_assigns_planning_buckets_from_configured_windows(self):
        orders = [
            ProductionOrderModel(
                order_id="ORD-MUST",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=2 * 1440,
            ),
            ProductionOrderModel(
                order_id="ORD-CANDIDATE",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=7 * 1440,
            ),
            ProductionOrderModel(
                order_id="ORD-DEFERRED",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=20 * 1440,
            ),
        ]

        database._apply_schedule_policy_to_master_data(
            [],
            orders,
            {
                "planning_must_schedule_horizon_days": 3,
                "planning_candidate_horizon_days": 14,
            },
        )

        self.assertEqual([order.planning_bucket for order in orders], [
            "must_schedule",
            "candidate",
            "deferred",
        ])

    def test_schedule_policy_uses_configured_business_bucket_rules(self):
        machines = [
            BlownFilmMachineModel(
                machine_id="LINE-WIDE",
                name="Wide line",
                cleanroom_level="Class_100K",
                layer_structure=3,
                die_diameter_mm=300,
                min_width=400,
                max_width=1200,
                min_thickness=20,
                max_thickness=80,
                hourly_output_kg=100,
                max_slitting_lanes=4,
            ),
            BlownFilmMachineModel(
                machine_id="LINE-NARROW",
                name="Narrow line",
                cleanroom_level="Class_100K",
                layer_structure=3,
                die_diameter_mm=200,
                min_width=400,
                max_width=700,
                min_thickness=20,
                max_thickness=80,
                hourly_output_kg=80,
                max_slitting_lanes=3,
            ),
        ]
        orders = [
            ProductionOrderModel(
                order_id="ORD-MATERIAL-LATE",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=2 * 1440,
                material_available_mins=20 * 1440,
            ),
            ProductionOrderModel(
                order_id="ORD-URGENT",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="URGENT",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=10 * 1440,
            ),
            ProductionOrderModel(
                order_id="ORD-VIP",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="VIP",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=10 * 1440,
            ),
            ProductionOrderModel(
                order_id="ORD-SCARCE",
                product_type="Film-A",
                target_width=1000,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=10 * 1440,
            ),
            ProductionOrderModel(
                order_id="ORD-CANDIDATE",
                product_type="Film-A",
                target_width=500,
                target_thickness=35,
                total_quantity_kg=1000,
                cleanroom_req="Class_100K",
                customer_class="STANDARD",
                order_class="NORMAL",
                corona_req=False,
                core_size_inch=3,
                due_date_mins=10 * 1440,
            ),
        ]

        database._apply_schedule_policy_to_master_data(
            machines,
            orders,
            {
                "planning_must_schedule_horizon_days": 3,
                "planning_candidate_horizon_days": 14,
                "planning_material_ready_horizon_days": 14,
                "planning_force_must_order_classes": ["URGENT"],
                "planning_force_must_customer_classes": ["VIP"],
                "planning_scarce_machine_threshold": 1,
            },
        )

        self.assertEqual(
            {order.order_id: order.planning_bucket for order in orders},
            {
                "ORD-MATERIAL-LATE": "deferred",
                "ORD-URGENT": "must_schedule",
                "ORD-VIP": "must_schedule",
                "ORD-SCARCE": "must_schedule",
                "ORD-CANDIDATE": "candidate",
            },
        )

    def test_solver_params_include_policy_snapshot_when_present(self):
        result = type("Result", (), {
            "input_order_count": 2,
            "schedulable_order_count": 1,
            "blocked_order_count": 1,
            "tasks": [object()],
            "deferred_orders": [
                {"order_id": "ORD-CANDIDATE-A", "deferred_reason_code": "candidate_optional_rejected"},
                {"order_id": "ORD-CANDIDATE-B", "reason": "candidate_optional_rejected"},
                {"order_id": "ORD-WINDOW", "reason": "planning_window_deferred"},
                {"order_id": "ORD-UNKNOWN"},
            ],
            "unplaced_solver_failed_orders": [{"order_id": "ORD-MUST"}],
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
        self.assertEqual(params["summary"]["scheduled_order_count"], 1)
        self.assertEqual(params["summary"]["deferred_order_count"], 4)
        self.assertEqual(params["summary"]["deferred_reason_counts"], {
            "candidate_optional_rejected": 2,
            "planning_window_deferred": 1,
            "unknown": 1,
        })
        self.assertEqual(params["summary"]["unplaced_solver_failed_order_count"], 1)
        self.assertEqual(params["unplaced_solver_failed_orders"], result.unplaced_solver_failed_orders)

    def test_solver_params_summary_counts_planning_buckets(self):
        task = SimpleNamespace(order=SimpleNamespace(planning_bucket="must_schedule"))
        result = type("Result", (), {
            "input_order_count": 3,
            "schedulable_order_count": 2,
            "blocked_order_count": 0,
            "tasks": [task],
            "deferred_orders": [
                {"order_id": "ORD-CANDIDATE", "planning_bucket": "candidate", "reason": "candidate_optional_rejected"},
                {"order_id": "ORD-DEFERRED", "planning_bucket": "deferred", "reason": "planning_window_deferred"},
            ],
            "unplaced_solver_failed_orders": [],
            "solver_metrics": {},
        })()

        params = database._build_schedule_run_solver_params(
            result=result,
            diagnostics_payload=[],
            normalized_order_ids=["ORD-MUST", "ORD-CANDIDATE", "ORD-DEFERRED"],
            order_snapshots=[],
            mode="AUTO",
        )

        self.assertEqual(params["summary"]["planning_bucket_counts"], {
            "must_schedule": 1,
            "candidate": 1,
            "deferred": 1,
        })

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
                "solver_metrics": {
                    "phase_1": {"status": "OPTIMAL", "gap": 0.0},
                    "model_size": {"order_count": 1},
                },
            },
            "confirmed_by": None,
            "confirmed_at": None,
            "cancelled_by": None,
            "cancelled_at": None,
            "cancel_reason": None,
        }

        data = schedule_router._run_row_to_dict(row)

        self.assertEqual(data["preplan_screening"], screening_snapshot)
        self.assertEqual(data["solver_metrics"]["phase_1"]["status"], "OPTIMAL")
        self.assertEqual(data["solver_metrics"]["model_size"]["order_count"], 1)

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

    def test_in_production_queue_rows_become_machine_and_time_locked_inputs(self):
        order = ProductionOrderModel(
            order_id="ORD-STARTED-API",
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
                    "order_id": "ORD-STARTED-API",
                    "machine_id": "LINE-A",
                    "start_mins": 120,
                    "end_mins": 240,
                    "setup_time_mins": 30,
                    "scrap_kg": 2,
                    "sequence_index": 3,
                    "manual_lock_machine": False,
                    "manual_lock_time": False,
                    "queue_status": "IN_PRODUCTION",
                    "started_at": datetime(2026, 5, 23, 8, 0),
                },
            ],
            orders=[order],
            machines=[machine],
        )

        self.assertEqual(len(locked_tasks), 1)
        self.assertEqual(locked_tasks[0].order.order_id, "ORD-STARTED-API")
        self.assertTrue(locked_tasks[0].manual_lock_machine)
        self.assertTrue(locked_tasks[0].manual_lock_time)

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
        self.assertTrue(summary["has_negative_impact"])
        self.assertEqual(summary["negative_impact_order_ids"], ["ORD-A"])
        self.assertEqual(summary["review_reasons"], [
            {
                "order_id": "ORD-A",
                "reasons": ["end_delayed", "setup_increased", "tardiness_increased"],
                "reason_details": [
                    {
                        "code": "end_delayed",
                        "label": "完工延后",
                        "description": schedule_router.ADJUSTMENT_REVIEW_REASON_DETAILS["end_delayed"]["description"],
                        "actual_delta_mins": 120,
                        "threshold_mins": 0,
                    },
                    {
                        "code": "setup_increased",
                        "label": "换产增加",
                        "description": schedule_router.ADJUSTMENT_REVIEW_REASON_DETAILS["setup_increased"]["description"],
                        "actual_delta_mins": 40,
                        "threshold_mins": 0,
                    },
                    {
                        "code": "tardiness_increased",
                        "label": "逾期增加",
                        "description": schedule_router.ADJUSTMENT_REVIEW_REASON_DETAILS["tardiness_increased"]["description"],
                        "actual_delta_mins": 45,
                        "threshold_mins": 0,
                    },
                ],
            }
        ])
        self.assertEqual(summary["affected_order_ids"], ["ORD-A", "ORD-B"])

    def test_manual_adjustment_impact_summary_uses_configured_review_thresholds(self):
        summary = schedule_router._manual_adjustment_impact_summary(
            [
                {
                    "order_id": "ORD-BELOW",
                    "impact": {
                        "end_delta_mins": 10,
                        "setup_time_delta_mins": 4,
                        "tardiness_delta_mins": 9,
                    },
                },
                {
                    "order_id": "ORD-REVIEW",
                    "impact": {
                        "end_delta_mins": 31,
                        "setup_time_delta_mins": 21,
                        "tardiness_delta_mins": 16,
                    },
                },
            ],
            {
                "delay_threshold_mins": 30,
                "setup_threshold_mins": 20,
                "tardiness_threshold_mins": 15,
            },
        )

        self.assertEqual(summary["negative_impact_order_ids"], ["ORD-REVIEW"])
        self.assertEqual(summary["review_reasons"], [
            {
                "order_id": "ORD-REVIEW",
                "reasons": ["end_delayed", "setup_increased", "tardiness_increased"],
                "reason_details": [
                    {
                        "code": "end_delayed",
                        "label": "完工延后",
                        "description": schedule_router.ADJUSTMENT_REVIEW_REASON_DETAILS["end_delayed"]["description"],
                        "actual_delta_mins": 31,
                        "threshold_mins": 30,
                    },
                    {
                        "code": "setup_increased",
                        "label": "换产增加",
                        "description": schedule_router.ADJUSTMENT_REVIEW_REASON_DETAILS["setup_increased"]["description"],
                        "actual_delta_mins": 21,
                        "threshold_mins": 20,
                    },
                    {
                        "code": "tardiness_increased",
                        "label": "逾期增加",
                        "description": schedule_router.ADJUSTMENT_REVIEW_REASON_DETAILS["tardiness_increased"]["description"],
                        "actual_delta_mins": 16,
                        "threshold_mins": 15,
                    },
                ],
            }
        ])
        self.assertEqual(summary["review_required_count"], 1)
        self.assertEqual(summary["review_required_order_ids"], ["ORD-REVIEW"])
        self.assertEqual(summary["review_reason_summary"], {
            "end_delayed": {
                "code": "end_delayed",
                "label": "完工延后",
                "count": 1,
                "order_ids": ["ORD-REVIEW"],
                "affected_order_count": 1,
                "max_actual_delta_mins": 31,
                "max_excess_mins": 1,
                "total_excess_mins": 1,
                "threshold_mins": 30,
            },
            "setup_increased": {
                "code": "setup_increased",
                "label": "换产增加",
                "count": 1,
                "order_ids": ["ORD-REVIEW"],
                "affected_order_count": 1,
                "max_actual_delta_mins": 21,
                "max_excess_mins": 1,
                "total_excess_mins": 1,
                "threshold_mins": 20,
            },
            "tardiness_increased": {
                "code": "tardiness_increased",
                "label": "逾期增加",
                "count": 1,
                "order_ids": ["ORD-REVIEW"],
                "affected_order_count": 1,
                "max_actual_delta_mins": 16,
                "max_excess_mins": 1,
                "total_excess_mins": 1,
                "threshold_mins": 15,
            },
        })

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

    def test_adjustment_review_reason_summary_deduplicates_affected_orders(self):
        summary = schedule_router._manual_adjustment_review_reason_summary([
            {
                "order_id": "ORD-DUP",
                "reason_details": [
                    {
                        "code": "end_delayed",
                        "label": "完工延后",
                        "actual_delta_mins": 20,
                        "threshold_mins": 10,
                    },
                ],
            },
            {
                "order_id": "ORD-DUP",
                "reason_details": [
                    {
                        "code": "end_delayed",
                        "label": "完工延后",
                        "actual_delta_mins": 30,
                        "threshold_mins": 10,
                    },
                ],
            },
        ])

        self.assertEqual(summary["end_delayed"]["count"], 2)
        self.assertEqual(summary["end_delayed"]["order_ids"], ["ORD-DUP"])
        self.assertEqual(summary["end_delayed"]["affected_order_count"], 1)
        self.assertEqual(summary["end_delayed"]["max_actual_delta_mins"], 30)
        self.assertEqual(summary["end_delayed"]["max_excess_mins"], 20)
        self.assertEqual(summary["end_delayed"]["total_excess_mins"], 30)

    def test_adjustment_reason_summary_groups_audit_causes_and_actors(self):
        summary = schedule_router._adjustment_reason_summary([
            {
                "order_id": "ORD-A",
                "reason_code": "URGENT_INSERT",
                "reason_text": "客户急单插入",
                "changed_by": "planner-a",
                "validation_status": "PASSED",
            },
            {
                "order_id": "ORD-B",
                "reason_code": "URGENT_INSERT",
                "reason_text": "客户急单插入",
                "changed_by": "planner-b",
                "validation_status": "FAILED",
            },
            {
                "order_id": "ORD-C",
                "reason_code": "MATERIAL_DELAY",
                "reason_text": "原料延期",
                "changed_by": "planner-a",
                "validation_status": "PASSED",
            },
        ])

        self.assertEqual(summary["adjustment_count"], 3)
        self.assertEqual(summary["failed_adjustment_count"], 1)
        self.assertEqual(summary["reason_counts"], {"URGENT_INSERT": 2, "MATERIAL_DELAY": 1})
        self.assertEqual(summary["actor_counts"], {"planner-a": 2, "planner-b": 1})
        self.assertEqual(summary["reason_texts"]["URGENT_INSERT"], "客户急单插入")
        self.assertEqual(summary["reason_items"], [
            {
                "reason_code": "URGENT_INSERT",
                "count": 2,
                "sample_reason_text": summary["reason_texts"]["URGENT_INSERT"],
            },
            {
                "reason_code": "MATERIAL_DELAY",
                "count": 1,
                "sample_reason_text": summary["reason_texts"]["MATERIAL_DELAY"],
            },
        ])

    def test_order_what_if_changes_apply_without_mutating_source_order(self):
        order = ProductionOrderModel(
            order_id="ORD-WHATIF",
            product_type="INFUSION_FILM",
            target_width=800,
            target_thickness=80,
            total_quantity_kg=1000,
            cleanroom_req="Class_100K",
            customer_class="STANDARD",
            order_class="NORMAL",
            corona_req=False,
            core_size_inch=3,
            due_date_mins=1440,
            material_available_mins=0,
            recipe_materials=["PE", "PE", "PE"],
        )

        changed, status, fields = schedule_router._apply_order_what_if_changes(
            order,
            "PENDING",
            {
                "target_width": 1200,
                "cleanroom_req": "Class_10K",
                "status": "released",
            },
        )

        self.assertEqual(order.target_width, 800)
        self.assertEqual(changed.target_width, 1200)
        self.assertEqual(changed.cleanroom_req, "Class_10K")
        self.assertEqual(status, "RELEASED")
        self.assertEqual(fields, ["target_width", "cleanroom_req", "status"])

    def test_order_what_if_impact_reports_direction_and_preplan_gate(self):
        impact = schedule_router._screening_impact(
            {
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "code": "no_eligible_machine",
            },
            {
                "screening_status": "ready",
                "business_bucket": "ready",
                "code": None,
            },
        )

        self.assertTrue(impact["screening_status_changed"])
        self.assertTrue(impact["business_bucket_changed"])
        self.assertTrue(impact["code_changed"])
        self.assertEqual(impact["direction"], "improved")
        self.assertFalse(impact["can_enter_preplan_before"])
        self.assertTrue(impact["can_enter_preplan_after"])


if __name__ == "__main__":
    unittest.main()
