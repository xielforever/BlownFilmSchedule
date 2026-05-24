import unittest
from types import SimpleNamespace
from unittest.mock import patch

from api.routers import rules as rules_router
from src import database
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.scheduler import SetupCalculator
from src.setup_matrices import SetupMatricesManager


class TestRuleEnablementContracts(unittest.TestCase):
    def _line_01(self):
        return BlownFilmMachineModel(
            machine_id="LINE-01",
            name="LINE-01",
            cleanroom_level="Class_10K",
            layer_structure=5,
            die_diameter_mm=300,
            min_width=100,
            max_width=1500,
            min_thickness=20,
            max_thickness=120,
            hourly_output_kg=120,
            max_slitting_lanes=4,
        )

    def _order(self, order_id, width, thickness, order_class):
        return ProductionOrderModel(
            order_id=order_id,
            product_type="Medical Film",
            target_width=width,
            target_thickness=thickness,
            total_quantity_kg=1000,
            cleanroom_req="Class_10K",
            customer_class="STANDARD",
            order_class=order_class,
            corona_req=True,
            core_size_inch=3,
            due_date_mins=10_000,
            recipe_materials=["A", "A", "A", "B", "A"],
        )

    def test_empty_runtime_setup_manager_produces_zero_setup_and_scrap(self):
        mgr = SetupMatricesManager.empty_rules()
        calc = SetupCalculator(mgr)
        prev = self._order("ORD-001", 300, 40, "URGENT")
        nxt = self._order("ORD-009", 420, 45, "NORMAL")

        self.assertEqual(calc.calculate_setup_time(prev, nxt, self._line_01()), 0)
        self.assertEqual(calc.calculate_scrap_weight(prev, nxt, self._line_01()), 0.0)

    def test_setup_detail_explains_legacy_ord001_to_ord009_80_minutes(self):
        mgr = SetupMatricesManager()
        mgr.same_material_time = 30
        mgr.width_up_rules = [(50, 15), (200, 40)]
        mgr.thickness_rules = [(10, 10)]
        calc = SetupCalculator(mgr)
        prev = self._order("ORD-001", 300, 40, "URGENT")
        nxt = self._order("ORD-009", 420, 45, "NORMAL")

        detail = calc.calculate_setup_detail(prev, nxt, self._line_01())

        self.assertEqual(detail["total_mins"], 80)
        self.assertEqual([item["category"] for item in detail["components"]], ["material", "width", "thickness"])
        self.assertEqual([item["minutes"] for item in detail["components"]], [30, 40, 10])

    def test_rule_payloads_support_enable_disable_reason(self):
        for payload_type in [
            rules_router.MaterialSwitchUpdate,
            rules_router.GmpUpdate,
            rules_router.SpecRuleUpdate,
            rules_router.MaintenanceUpdate,
        ]:
            fields = payload_type.model_fields
            self.assertIn("is_enabled", fields)
            self.assertIn("disabled_reason", fields)

    def test_enabled_clause_filters_enabled_rows_by_default(self):
        self.assertTrue(hasattr(database, "_enabled_clause"))
        self.assertEqual(database._enabled_clause("material_switch_matrix"), "COALESCE(is_enabled, TRUE)=TRUE")
        self.assertEqual(database._enabled_clause("machine_maintenance_calendar"), "COALESCE(is_enabled, TRUE)=TRUE")

    def test_rules_summary_exposes_policy_metadata(self):
        self.assertTrue(hasattr(rules_router, "_rule_state_counts"))
        rows = [
            {"is_enabled": True},
            {"is_enabled": False},
            {"is_enabled": True},
        ]

        self.assertEqual(rules_router._rule_state_counts(rows), {"enabled": 2, "disabled": 1})

    def test_disabled_rule_requires_reason_and_enabling_clears_reason(self):
        with self.assertRaises(rules_router.HTTPException) as raised:
            rules_router._normalize_rule_enablement_fields(
                {"is_enabled": False},
                before={"is_enabled": True, "disabled_reason": None},
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("禁用原因", raised.exception.detail)

        fields = rules_router._normalize_rule_enablement_fields(
            {"is_enabled": True},
            before={"is_enabled": False, "disabled_reason": "临时停用"},
        )

        self.assertIsNone(fields["disabled_reason"])

    def test_rule_change_audit_payload_uses_rule_scope_and_disable_reason(self):
        payload = rules_router._rule_audit_payload(
            table="material_switch_matrix",
            row_id=12,
            before={"id": 12, "is_enabled": True, "disabled_reason": None},
            after={"id": 12, "is_enabled": False, "disabled_reason": "供应商牌号停用"},
            user="planner",
        )

        self.assertEqual(payload["config_scope"], "rule")
        self.assertEqual(payload["config_key"], "material_switch")
        self.assertEqual(payload["entity_id"], "12")
        self.assertEqual(payload["changed_by"], "planner")
        self.assertEqual(payload["reason_text"], "供应商牌号停用")

    def test_rule_config_audit_marks_screening_cache_stale(self):
        class Cursor:
            def __init__(self):
                self.sql = []
                self.rowcount = 0

            def execute(self, sql, params=None):
                self.sql.append(" ".join(sql.split()).lower())
                if self.sql[-1].startswith("update order_screening_cache"):
                    self.rowcount = 2

        cur = Cursor()

        rules_router._insert_config_audit(
            cur,
            {
                "config_scope": "rule",
                "config_key": "material_switch",
                "entity_id": "12",
                "before_state": {"is_enabled": True},
                "after_state": {"is_enabled": False},
                "changed_by": "planner",
                "reason_text": "供应商牌号停用",
            },
        )

        self.assertTrue(any(sql.startswith("update order_screening_cache") for sql in cur.sql))

    def test_create_material_switch_rule_marks_screening_cache_stale(self):
        class Cursor:
            rowcount = 0

            def execute(self, sql, params=None):
                self.last_sql = " ".join(sql.split()).lower()

            def fetchone(self):
                return {"id": 31}

        class Db:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.commit_count = 0

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.commit_count += 1

        db = Db()
        payload = rules_router.MaterialSwitchRule(
            from_material="A",
            to_material="B",
            switch_time_mins=30,
        )

        with patch.object(rules_router, "ensure_rule_enablement_schema"), \
             patch.object(rules_router, "_mark_order_screening_cache_stale") as mark_stale:
            result = rules_router.create_material_switch_rule(
                payload,
                db=db,
                _=SimpleNamespace(username="planner"),
            )

        self.assertEqual(result["id"], 31)
        mark_stale.assert_called_once_with(db.cursor_obj, reason="rule_matrix_changed")
        self.assertEqual(db.commit_count, 1)


if __name__ == "__main__":
    unittest.main()
