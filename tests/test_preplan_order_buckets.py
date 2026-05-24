from datetime import datetime, timezone
import unittest

from api.routers.schedule import _build_preplan_order_buckets


def _order(order_id, width=300, thickness=40):
    return {
        "order_id": order_id,
        "product_type": "TestProd",
        "target_width": width,
        "target_thickness": thickness,
        "total_quantity_kg": 100,
        "cleanroom_req": "Class_10K",
        "customer_class": "STANDARD",
        "order_class": "NORMAL",
        "due_date": datetime(2026, 5, 25, tzinfo=timezone.utc),
        "material_available_time": None,
        "status": "PENDING",
        "recipe_layers": 5,
    }


def _order_due(order_id, day, month=5):
    order = _order(order_id)
    order["due_date"] = datetime(2026, month, day, tzinfo=timezone.utc)
    return order


def _machine():
    return {
        "machine_id": "LINE-01",
        "status": "ACTIVE",
        "cleanroom_level": "Class_10K",
        "layer_structure": 5,
        "min_width": 100,
        "max_width": 600,
        "min_thickness": 20,
        "max_thickness": 80,
    }


class TestPreplanOrderBuckets(unittest.TestCase):
    def test_split_scheduled_unplaced_and_blocked(self):
        task = {
            "id": 10,
            "order_id": "ORD-SCHEDULED",
            "machine_id": "LINE-01",
            "sequence_index": 0,
            "start_time": "2026-05-22T08:00:00Z",
            "end_time": "2026-05-22T10:00:00Z",
            "is_late": False,
            "tardiness_mins": 0,
            "task_source": "AUTO",
        }
        diagnostic = {
            "entity_type": "order",
            "entity_id": "ORD-BLOCKED",
            "category": "eligibility",
            "severity": "warning",
            "code": "eligibility.width_out_of_range",
            "root_cause": "幅宽超出所有可用机台能力。",
            "evidence": [],
            "recommendations": [],
        }

        buckets = _build_preplan_order_buckets(
            order_rows=[
                _order("ORD-SCHEDULED"),
                _order("ORD-UNPLACED"),
                _order("ORD-BLOCKED", width=9999),
            ],
            machines=[_machine()],
            tasks=[task],
            diagnostics=[diagnostic],
            selected_order_ids=["ORD-SCHEDULED", "ORD-UNPLACED", "ORD-BLOCKED"],
        )

        self.assertEqual([row["order_id"] for row in buckets["scheduled_orders"]], ["ORD-SCHEDULED"])
        self.assertEqual([row["order_id"] for row in buckets["unplaced_schedulable_orders"]], ["ORD-UNPLACED"])
        self.assertEqual([row["order_id"] for row in buckets["blocked_orders"]], ["ORD-BLOCKED"])
        self.assertEqual(
            [row["order_id"] for row in buckets["schedulable_orders"]],
            ["ORD-SCHEDULED", "ORD-UNPLACED"],
        )
        self.assertEqual(len(buckets["input_orders"]), 3)
        self.assertEqual(
            buckets["unplaced_schedulable_orders"][0]["bucket_reason"],
            "订单满足硬能力约束，但当前草案未生成落位任务。",
        )
        self.assertEqual(buckets["blocked_orders"][0]["root_cause"], "幅宽超出所有可用机台能力。")
        self.assertEqual(buckets["blocked_orders"][0]["eligible_machine_count"], 0)

    def test_reports_late_scheduled_orders(self):
        task = {
            "id": 11,
            "order_id": "ORD-LATE",
            "machine_id": "LINE-01",
            "sequence_index": 0,
            "start_time": "2026-05-27T08:00:00Z",
            "end_time": "2026-05-27T10:00:00Z",
            "is_late": True,
            "tardiness_mins": 120,
            "task_source": "AUTO",
        }

        buckets = _build_preplan_order_buckets(
            order_rows=[_order("ORD-LATE")],
            machines=[_machine()],
            tasks=[task],
            diagnostics=[],
            selected_order_ids=["ORD-LATE"],
        )

        self.assertEqual([row["order_id"] for row in buckets["late_orders"]], ["ORD-LATE"])
        self.assertEqual(buckets["late_orders"][0]["bucket_reason"], "计划完工时间晚于订单交期。")

    def test_exposes_applied_screening_override_on_preplan_rows(self):
        task = {
            "id": 12,
            "order_id": "ORD-OVERRIDE",
            "machine_id": "LINE-01",
            "sequence_index": 0,
            "start_time": "2026-05-22T08:00:00Z",
            "end_time": "2026-05-22T10:00:00Z",
            "is_late": False,
            "tardiness_mins": 0,
            "task_source": "AUTO",
        }
        applied_override = {
            "audit_id": 7,
            "override_policy": "restricted",
            "reason_text": "物料替代方案已确认",
        }

        buckets = _build_preplan_order_buckets(
            order_rows=[_order("ORD-OVERRIDE")],
            machines=[_machine()],
            tasks=[task],
            diagnostics=[],
            selected_order_ids=["ORD-OVERRIDE"],
            screening_items_by_order_id={
                "ORD-OVERRIDE": {
                    "order_id": "ORD-OVERRIDE",
                    "applied_override": applied_override,
                },
            },
        )

        self.assertEqual(buckets["scheduled_orders"][0]["applied_override"], applied_override)
        self.assertEqual(buckets["input_orders"][0]["applied_override"], applied_override)

    def test_decimal_string_dimensions_are_schedulable(self):
        machine = _machine()
        machine.update({
            "min_width": "100.0",
            "max_width": "600.0",
            "min_thickness": "20.0",
            "max_thickness": "80.0",
        })

        buckets = _build_preplan_order_buckets(
            order_rows=[_order("ORD-DECIMAL", width="300.0", thickness="40.0")],
            machines=[machine],
            tasks=[],
            diagnostics=[],
            selected_order_ids=["ORD-DECIMAL"],
        )

        self.assertEqual([row["order_id"] for row in buckets["unplaced_schedulable_orders"]], ["ORD-DECIMAL"])
        self.assertEqual([row["order_id"] for row in buckets["schedulable_orders"]], ["ORD-DECIMAL"])
        self.assertEqual(buckets["schedulable_orders"][0]["eligible_machine_count"], 1)

    def test_planning_policy_splits_must_schedule_candidate_and_deferred(self):
        buckets = _build_preplan_order_buckets(
            order_rows=[
                _order_due("ORD-MUST", 25),
                _order_due("ORD-CANDIDATE", 30),
                _order_due("ORD-DEFERRED", 10, month=6),
            ],
            machines=[_machine()],
            tasks=[],
            diagnostics=[],
            selected_order_ids=["ORD-MUST", "ORD-CANDIDATE", "ORD-DEFERRED"],
            planning_bucket_policy={
                "plan_start": datetime(2026, 5, 24, tzinfo=timezone.utc),
                "must_schedule_horizon_days": 3,
                "candidate_horizon_days": 14,
            },
        )

        self.assertEqual([row["order_id"] for row in buckets["must_schedule_orders"]], ["ORD-MUST"])
        self.assertEqual([row["order_id"] for row in buckets["candidate_orders"]], ["ORD-CANDIDATE"])
        self.assertEqual([row["order_id"] for row in buckets["deferred_orders"]], ["ORD-CANDIDATE", "ORD-DEFERRED"])
        self.assertEqual([row["order_id"] for row in buckets["unplaced_schedulable_orders"]], ["ORD-MUST"])
        self.assertEqual(buckets["candidate_orders"][0]["planning_bucket"], "candidate")
        self.assertEqual(buckets["deferred_orders"][0]["bucket"], "deferred")

    def test_solver_deferred_orders_use_structured_reason(self):
        buckets = _build_preplan_order_buckets(
            order_rows=[_order_due("ORD-CANDIDATE", 30)],
            machines=[_machine()],
            tasks=[],
            diagnostics=[],
            selected_order_ids=["ORD-CANDIDATE"],
            planning_bucket_policy={
                "plan_start": datetime(2026, 5, 24, tzinfo=timezone.utc),
                "must_schedule_horizon_days": 3,
                "candidate_horizon_days": 14,
            },
            deferred_order_items=[{
                "order_id": "ORD-CANDIDATE",
                "planning_bucket": "candidate",
                "reason": "candidate_optional_rejected",
                "message": "候选订单按本轮接受策略延后。",
            }],
        )

        self.assertEqual([row["order_id"] for row in buckets["deferred_orders"]], ["ORD-CANDIDATE"])
        self.assertEqual(buckets["deferred_orders"][0]["bucket_reason"], "候选订单按本轮接受策略延后。")
        self.assertEqual(buckets["deferred_orders"][0]["deferred_reason_code"], "candidate_optional_rejected")
        self.assertEqual(buckets["deferred_reason_counts"], {
            "candidate_optional_rejected": 1,
        })

    def test_deferred_reason_counts_include_planning_window_deferrals(self):
        buckets = _build_preplan_order_buckets(
            order_rows=[
                _order_due("ORD-CANDIDATE", 30),
                _order_due("ORD-DEFERRED", 10, month=6),
            ],
            machines=[_machine()],
            tasks=[],
            diagnostics=[],
            selected_order_ids=["ORD-CANDIDATE", "ORD-DEFERRED"],
            planning_bucket_policy={
                "plan_start": datetime(2026, 5, 24, tzinfo=timezone.utc),
                "must_schedule_horizon_days": 3,
                "candidate_horizon_days": 14,
            },
        )

        self.assertEqual(buckets["deferred_reason_counts"], {
            "planning_window_deferred": 2,
        })

    def test_solver_unplaced_orders_use_structured_bucket(self):
        buckets = _build_preplan_order_buckets(
            order_rows=[_order_due("ORD-MUST", 25)],
            machines=[_machine()],
            tasks=[],
            diagnostics=[],
            selected_order_ids=["ORD-MUST"],
            planning_bucket_policy={
                "plan_start": datetime(2026, 5, 24, tzinfo=timezone.utc),
                "must_schedule_horizon_days": 3,
                "candidate_horizon_days": 14,
            },
            unplaced_solver_failed_order_items=[{
                "order_id": "ORD-MUST",
                "reason": "required_order_unplaced",
                "message": "Required order was not placed by the solver.",
            }],
        )

        self.assertEqual([row["order_id"] for row in buckets["unplaced_solver_failed_orders"]], ["ORD-MUST"])
        self.assertEqual(buckets["unplaced_solver_failed_orders"][0]["bucket"], "unplaced_solver_failed")
        self.assertEqual(
            buckets["unplaced_solver_failed_orders"][0]["bucket_reason"],
            "Required order was not placed by the solver.",
        )
        self.assertEqual(buckets["unplaced_solver_failed_orders"][0]["unplaced_reason_code"], "required_order_unplaced")
        self.assertEqual(buckets["unplaced_schedulable_orders"], [])


if __name__ == "__main__":
    unittest.main()
