import unittest

from fastapi import HTTPException

from api.routers import schedule as schedule_router
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.order_screening import screen_orders


def _make_order(order_id: str, **overrides) -> ProductionOrderModel:
    data = {
        "order_id": order_id,
        "product_type": "Film-A",
        "target_width": 520,
        "target_thickness": 35,
        "total_quantity_kg": 1200,
        "cleanroom_req": "Class_10K",
        "customer_class": "STANDARD",
        "order_class": "NORMAL",
        "corona_req": False,
        "core_size_inch": 3,
        "order_date_mins": 0,
        "due_date_mins": 5000,
        "material_available_mins": 0,
        "priority_override": None,
        "recipe_materials": ["L1", "L2", "L3", "L4", "L5"],
    }
    data.update(overrides)
    return ProductionOrderModel(**data)


def _make_machine(machine_id: str = "LINE-A", **overrides) -> BlownFilmMachineModel:
    data = {
        "machine_id": machine_id,
        "name": machine_id,
        "cleanroom_level": "Class_10K",
        "layer_structure": 5,
        "die_diameter_mm": 300,
        "min_width": 100,
        "max_width": 1500,
        "min_thickness": 20,
        "max_thickness": 80,
        "hourly_output_kg": 600,
        "max_slitting_lanes": 4,
    }
    data.update(overrides)
    return BlownFilmMachineModel(**data)


class TestOrderScreening(unittest.TestCase):
    def test_ready_order_has_machine_fit_and_computed_summary(self):
        result = screen_orders([_make_order("ORD-READY")], [_make_machine()])

        self.assertEqual(result["mode"], "computed")
        self.assertEqual(result["summary"]["ready_count"], 1)
        self.assertEqual(result["summary"]["risk_count"], 0)
        self.assertEqual(result["summary"]["blocked_count"], 0)
        item = result["items"][0]
        self.assertEqual(item["screening_status"], "ready")
        self.assertEqual(item["code"], "ready")
        self.assertEqual(item["eligible_machine_count"], 1)

    def test_status_not_pending_blocks_before_machine_fit(self):
        order = _make_order("ORD-SCHEDULED")
        result = screen_orders([order], [_make_machine()], status_by_order_id={"ORD-SCHEDULED": "SCHEDULED"})

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["code"], "status_not_pending")
        self.assertEqual(result["summary"]["blocked_count"], 1)

    def test_missing_recipe_blocks_order(self):
        order = _make_order("ORD-NO-RECIPE", recipe_materials=[])
        result = screen_orders([order], [_make_machine()])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["code"], "missing_recipe")

    def test_no_eligible_machine_reports_diagnostic_root_cause(self):
        order = _make_order("ORD-WIDE", target_width=9999)
        result = screen_orders([order], [_make_machine()])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["code"], "no_eligible_machine")
        self.assertEqual(item["eligible_machine_count"], 0)
        self.assertIn("幅宽", item["root_cause"])
        self.assertEqual(item["diagnostic_code"], "eligibility.width_out_of_range")

    def test_material_after_due_date_blocks_order(self):
        order = _make_order("ORD-MATERIAL", material_available_mins=6000, due_date_mins=5000)
        result = screen_orders([order], [_make_machine()])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["code"], "material_not_ready")
        self.assertIn("晚于交期", item["root_cause"])

    def test_due_risk_flags_tight_but_feasible_order(self):
        order = _make_order("ORD-TIGHT", due_date_mins=150)
        result = screen_orders([order], [_make_machine(hourly_output_kg=600)])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "risk")
        self.assertEqual(item["code"], "due_risk")
        self.assertGreaterEqual(item["slack_mins"], 0)
        self.assertEqual(result["summary"]["risk_count"], 1)

    def test_non_ready_screening_items_have_specific_action_recommendations(self):
        cases = [
            (
                screen_orders(
                    [_make_order("ORD-SCHEDULED")],
                    [_make_machine()],
                    status_by_order_id={"ORD-SCHEDULED": "SCHEDULED"},
                )["items"][0],
                "release_or_reopen_order",
                "order",
            ),
            (
                screen_orders(
                    [_make_order("ORD-MISSING-PRODUCT")],
                    [_make_machine()],
                    product_exists_by_order_id={"ORD-MISSING-PRODUCT": False},
                )["items"][0],
                "configure_product",
                "rules",
            ),
            (
                screen_orders(
                    [_make_order("ORD-NO-RECIPE", recipe_materials=[])],
                    [_make_machine()],
                )["items"][0],
                "configure_recipe",
                "rules",
            ),
            (
                screen_orders(
                    [_make_order("ORD-WIDE-ACTION", target_width=9999)],
                    [_make_machine()],
                )["items"][0],
                "expand_machine_capability",
                "machine",
            ),
            (
                screen_orders(
                    [_make_order("ORD-MATERIAL-ACTION", material_available_mins=6000, due_date_mins=5000)],
                    [_make_machine()],
                )["items"][0],
                "update_material_or_due_date",
                "material",
            ),
            (
                screen_orders(
                    [_make_order("ORD-TIGHT-ACTION", due_date_mins=150)],
                    [_make_machine(hourly_output_kg=600)],
                )["items"][0],
                "relieve_due_risk",
                "schedule",
            ),
        ]

        for item, expected_action, expected_category in cases:
            with self.subTest(code=item["code"]):
                self.assertNotEqual(item["screening_status"], "ready")
                self.assertTrue(item["recommendations"])
                primary = item["recommendations"][0]
                self.assertEqual(primary["action"], expected_action)
                self.assertEqual(primary["category"], expected_category)
                self.assertTrue(primary["href"])
                self.assertTrue(primary["label"])
                self.assertTrue(primary["guidance"])

    def test_blocked_screening_items_reject_preplan_creation(self):
        screening = screen_orders(
            [_make_order("ORD-WIDE-PREPLAN", target_width=9999)],
            [_make_machine()],
            scope="preplan",
        )

        with self.assertRaises(HTTPException) as raised:
            schedule_router._raise_for_blocked_preplan_orders(screening)

        self.assertEqual(raised.exception.status_code, 400)
        detail = raised.exception.detail
        self.assertEqual(detail["code"], "preplan_blocked_orders")
        self.assertEqual(detail["summary"]["blocked_count"], 1)
        self.assertEqual(detail["blocked_orders"][0]["order_id"], "ORD-WIDE-PREPLAN")
        self.assertEqual(detail["blocked_orders"][0]["code"], "no_eligible_machine")
        self.assertIn("不能进入预排", detail["message"])


if __name__ == "__main__":
    unittest.main()
