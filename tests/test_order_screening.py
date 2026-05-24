import unittest

from fastapi import HTTPException

from api.routers import orders as orders_router
from api.routers import schedule as schedule_router
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.order_screening import build_screening_snapshot, override_decision_for_screening_item, screen_orders


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
        self.assertEqual(result["summary"]["business_bucket_counts"], {"ready": 1})
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

    def test_allowed_order_statuses_are_configurable(self):
        order = _make_order("ORD-RELEASED")
        result = screen_orders(
            [order],
            [_make_machine()],
            status_by_order_id={"ORD-RELEASED": "RELEASED"},
            screening_policy={"allowed_order_statuses": ["PENDING", "RELEASED"]},
        )

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "ready")
        self.assertEqual(item["code"], "ready")

    def test_allowed_order_statuses_accept_single_string(self):
        order = _make_order("ORD-RELEASED-STRING")
        result = screen_orders(
            [order],
            [_make_machine()],
            status_by_order_id={"ORD-RELEASED-STRING": "RELEASED"},
            screening_policy={"allowed_order_statuses": "RELEASED"},
        )

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "ready")
        self.assertEqual(item["code"], "ready")

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
        self.assertEqual(item["business_bucket"], "blocked_machine_capability")
        self.assertEqual(item["eligible_machine_count"], 0)
        self.assertIn("幅宽", item["root_cause"])
        self.assertEqual(item["diagnostic_code"], "eligibility.width_out_of_range")

    def test_no_cleanroom_machine_uses_cleanroom_business_bucket(self):
        order = _make_order("ORD-CLEANROOM", cleanroom_req="Class_10K")
        result = screen_orders([order], [_make_machine(cleanroom_level="Class_100K")])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["code"], "no_eligible_machine")
        self.assertEqual(item["business_bucket"], "blocked_cleanroom")
        self.assertEqual(item["diagnostic_code"], "eligibility.cleanroom_mismatch")

    def test_material_after_due_date_blocks_order(self):
        order = _make_order("ORD-MATERIAL", material_available_mins=6000, due_date_mins=5000)
        result = screen_orders([order], [_make_machine()])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["code"], "material_not_ready")
        self.assertEqual(item["business_bucket"], "blocked_material")
        self.assertIn("晚于交期", item["root_cause"])

    def test_missing_master_data_uses_data_error_business_bucket(self):
        missing_product = screen_orders(
            [_make_order("ORD-MISSING-PRODUCT")],
            [_make_machine()],
            product_exists_by_order_id={"ORD-MISSING-PRODUCT": False},
        )["items"][0]
        missing_recipe = screen_orders(
            [_make_order("ORD-MISSING-RECIPE", recipe_materials=[])],
            [_make_machine()],
        )["items"][0]

        self.assertEqual(missing_product["business_bucket"], "blocked_data_error")
        self.assertEqual(missing_recipe["business_bucket"], "blocked_data_error")

    def test_due_risk_flags_tight_but_feasible_order(self):
        order = _make_order("ORD-TIGHT", due_date_mins=150)
        result = screen_orders([order], [_make_machine(hourly_output_kg=600)])

        item = result["items"][0]
        self.assertEqual(item["screening_status"], "risk")
        self.assertEqual(item["code"], "due_risk")
        self.assertGreaterEqual(item["slack_mins"], 0)
        self.assertEqual(result["summary"]["risk_count"], 1)

    def test_due_risk_threshold_uses_configurable_screening_policy(self):
        order = _make_order("ORD-CONFIGURED-SLACK", due_date_mins=370)

        default_result = screen_orders([order], [_make_machine(hourly_output_kg=600)])
        strict_result = screen_orders(
            [order],
            [_make_machine(hourly_output_kg=600)],
            screening_policy={
                "due_risk_min_slack_mins": 300,
                "due_risk_duration_multiplier": 1.0,
            },
        )

        self.assertEqual(default_result["items"][0]["screening_status"], "ready")
        self.assertEqual(strict_result["items"][0]["screening_status"], "risk")
        self.assertEqual(strict_result["items"][0]["code"], "due_risk")

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

    def test_restricted_screening_override_allows_preplan_but_marks_item(self):
        screening = screen_orders(
            [_make_order("ORD-MATERIAL-OVERRIDE-PREPLAN", material_available_mins=6000, due_date_mins=5000)],
            [_make_machine()],
            scope="preplan",
        )
        item = screening["items"][0]

        schedule_router._raise_for_blocked_preplan_orders(
            screening,
            override_audits_by_order_id={
                "ORD-MATERIAL-OVERRIDE-PREPLAN": {
                    "id": 7,
                    "screening_status": item["screening_status"],
                    "screening_code": item["code"],
                    "override_policy": item["override_decision"]["policy"],
                    "mode": "formal",
                    "reason_text": "物料替代方案已确认",
                },
            },
        )

        self.assertEqual(item["screening_status"], "blocked")
        self.assertEqual(item["applied_override"]["audit_id"], 7)
        self.assertEqual(item["applied_override"]["reason_text"], "物料替代方案已确认")

    def test_prohibited_screening_override_cannot_allow_preplan(self):
        screening = screen_orders(
            [_make_order("ORD-WIDE-FAKE-OVERRIDE", target_width=9999)],
            [_make_machine()],
            scope="preplan",
        )
        item = screening["items"][0]

        with self.assertRaises(HTTPException) as raised:
            schedule_router._raise_for_blocked_preplan_orders(
                screening,
                override_audits_by_order_id={
                    "ORD-WIDE-FAKE-OVERRIDE": {
                        "id": 8,
                        "screening_status": item["screening_status"],
                        "screening_code": item["code"],
                        "override_policy": "restricted",
                        "mode": "formal",
                        "reason_text": "业务要求强制排入",
                    },
                },
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail["blocked_orders"][0]["order_id"], "ORD-WIDE-FAKE-OVERRIDE")

    def test_screening_snapshot_hash_ignores_generated_at(self):
        first = screen_orders(
            [_make_order("ORD-SNAPSHOT")],
            [_make_machine()],
            generated_at="2026-05-24T08:00:00Z",
            scope="preplan",
        )
        second = screen_orders(
            [_make_order("ORD-SNAPSHOT")],
            [_make_machine()],
            generated_at="2026-05-24T09:00:00Z",
            scope="preplan",
        )

        first_snapshot = build_screening_snapshot(first)
        second_snapshot = build_screening_snapshot(second)

        self.assertEqual(first_snapshot["hash"], second_snapshot["hash"])
        self.assertEqual(first_snapshot["summary"], first["summary"])
        self.assertNotIn("generated_at", first_snapshot)

    def test_screening_snapshot_preserves_business_bucket(self):
        screening = screen_orders(
            [_make_order("ORD-BUCKET-SNAPSHOT", target_width=9999)],
            [_make_machine()],
            scope="preplan",
        )

        snapshot = build_screening_snapshot(screening)

        self.assertEqual(snapshot["items"][0]["business_bucket"], "blocked_machine_capability")

    def test_filter_screening_result_keeps_only_requested_status_and_business_bucket(self):
        screening = screen_orders(
            [
                _make_order("ORD-READY"),
                _make_order("ORD-BLOCKED", target_width=9999),
                _make_order("ORD-MATERIAL", material_available_mins=6000, due_date_mins=5000),
            ],
            [_make_machine()],
            scope="pending",
        )

        filtered = orders_router._filter_screening_result(
            screening,
            "blocked",
            "blocked_machine_capability",
        )

        self.assertEqual(filtered["summary"]["total_orders"], 1)
        self.assertEqual(filtered["summary"]["ready_count"], 0)
        self.assertEqual(filtered["summary"]["blocked_count"], 1)
        self.assertEqual(filtered["summary"]["business_bucket_counts"], {"blocked_machine_capability": 1})
        self.assertEqual([item["order_id"] for item in filtered["items"]], ["ORD-BLOCKED"])
        self.assertEqual(filtered["screening_bucket_filter"], "blocked_machine_capability")

    def test_screening_payload_accepts_business_bucket_filter(self):
        payload = orders_router.OrderScreeningPayload(
            screening_status="blocked",
            screening_bucket="blocked_material",
        )

        self.assertEqual(payload.screening_bucket, "blocked_material")

    def test_override_decision_allows_risk_but_blocks_hard_capability_errors(self):
        risk_item = screen_orders(
            [_make_order("ORD-RISK", due_date_mins=150)],
            [_make_machine(hourly_output_kg=600)],
        )["items"][0]
        blocked_item = screen_orders(
            [_make_order("ORD-WIDE-OVERRIDE", target_width=9999)],
            [_make_machine()],
        )["items"][0]

        risk_decision = override_decision_for_screening_item(risk_item)
        blocked_decision = override_decision_for_screening_item(blocked_item)

        self.assertTrue(risk_decision["allowed"])
        self.assertEqual(risk_decision["policy"], "restricted")
        self.assertTrue(risk_decision["requires_reason"])
        self.assertFalse(blocked_decision["allowed"])
        self.assertEqual(blocked_decision["policy"], "prohibited")

    def test_override_decision_treats_material_blockers_as_restricted(self):
        material_item = screen_orders(
            [_make_order("ORD-MATERIAL-OVERRIDE", material_available_mins=6000, due_date_mins=5000)],
            [_make_machine()],
        )["items"][0]

        decision = override_decision_for_screening_item(material_item)

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["policy"], "restricted")
        self.assertTrue(decision["requires_reason"])
        self.assertIn("material", decision["reason_code"])

    def test_override_policy_codes_are_configurable(self):
        material_item = screen_orders(
            [_make_order("ORD-MATERIAL-PROHIBITED", material_available_mins=6000, due_date_mins=5000)],
            [_make_machine()],
            screening_policy={
                "prohibited_override_codes": [
                    "missing_product",
                    "missing_recipe",
                    "no_eligible_machine",
                    "status_not_pending",
                    "material_not_ready",
                ],
                "restricted_override_codes": ["due_risk"],
            },
        )["items"][0]

        decision = material_item["override_decision"]

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["policy"], "prohibited")
        self.assertEqual(decision["reason_code"], "prohibited_material_not_ready")

    def test_prohibited_override_policy_takes_precedence_over_restricted(self):
        material_item = screen_orders(
            [_make_order("ORD-MATERIAL-CONFLICT", material_available_mins=6000, due_date_mins=5000)],
            [_make_machine()],
            screening_policy={
                "prohibited_override_codes": ["material_not_ready"],
                "restricted_override_codes": ["material_not_ready"],
            },
        )["items"][0]

        decision = material_item["override_decision"]

        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["policy"], "prohibited")

    def test_override_policy_codes_are_case_insensitive(self):
        material_item = screen_orders(
            [_make_order("ORD-MATERIAL-UPPER", material_available_mins=6000, due_date_mins=5000)],
            [_make_machine()],
            screening_policy={
                "prohibited_override_codes": [
                    "missing_product",
                    "missing_recipe",
                    "no_eligible_machine",
                    "status_not_pending",
                ],
                "restricted_override_codes": [" MATERIAL_NOT_READY "],
            },
        )["items"][0]

        decision = material_item["override_decision"]

        self.assertTrue(decision["allowed"])
        self.assertEqual(decision["policy"], "restricted")

    def test_screening_items_expose_override_decision(self):
        screening = screen_orders(
            [
                _make_order("ORD-READY-DECISION"),
                _make_order("ORD-RISK-DECISION", due_date_mins=150),
                _make_order("ORD-BLOCKED-DECISION", target_width=9999),
            ],
            [_make_machine(hourly_output_kg=600)],
        )
        decisions = {
            item["order_id"]: item["override_decision"]
            for item in screening["items"]
        }

        self.assertEqual(decisions["ORD-READY-DECISION"]["policy"], "not_required")
        self.assertTrue(decisions["ORD-RISK-DECISION"]["allowed"])
        self.assertEqual(decisions["ORD-BLOCKED-DECISION"]["policy"], "prohibited")


if __name__ == "__main__":
    unittest.main()
