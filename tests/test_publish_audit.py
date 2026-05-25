import unittest

from api.routers import schedule as schedule_router


class TestPublishAuditPayload(unittest.TestCase):
    def test_publish_audit_payload_captures_release_counts(self):
        payload = schedule_router._publish_audit_payload(
            event_type="PUBLISH",
            run_id=42,
            actor="planner",
            selected_order_count=8,
            warning_count=2,
            queue_row_count=7,
            details={"superseded_run_ids": [1, 2]},
        )

        self.assertEqual(payload["event_type"], "PUBLISH")
        self.assertEqual(payload["run_id"], 42)
        self.assertEqual(payload["actor"], "planner")
        self.assertEqual(payload["selected_order_count"], 8)
        self.assertEqual(payload["warning_count"], 2)
        self.assertEqual(payload["queue_row_count"], 7)
        self.assertEqual(payload["details"]["superseded_run_ids"], [1, 2])

    def test_validation_summary_payload_captures_counts_and_task_signature(self):
        payload = schedule_router._validation_summary_payload(
            {
                "status": "PASSED",
                "hard_error_count": 0,
                "warning_count": 2,
            },
            task_signature="task-sig-001",
        )

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "PASSED")
        self.assertEqual(payload["hard_error_count"], 0)
        self.assertEqual(payload["warning_count"], 2)
        self.assertEqual(payload["validator_version"], "preplan-validation-v1")
        self.assertEqual(payload["task_signature"], "task-sig-001")
        self.assertIn("validated_at", payload)

    def test_validation_summary_payload_captures_publishable_contract(self):
        payload = schedule_router._validation_summary_payload(
            {
                "status": "FAILED",
                "publishable": False,
                "hard_error_count": 1,
                "publish_blocker_count": 1,
                "warning_count": 0,
                "info_count": 1,
            },
            task_signature="task-sig-002",
        )

        self.assertFalse(payload["valid"])
        self.assertFalse(payload["publishable"])
        self.assertEqual(payload["publish_blocker_count"], 1)
        self.assertEqual(payload["info_count"], 1)

    def test_validation_contract_counts_publish_blockers_warnings_and_info(self):
        items = [
            schedule_router._validation_item(
                "warning",
                "late_order",
                "订单晚于交期。",
                level="warning",
            ),
            schedule_router._validation_item(
                "warning",
                "solver_gap",
                "求解器未证明最优。",
                level="info",
            ),
            schedule_router._validation_item(
                "error",
                "maintenance_overlap",
                "维护窗口冲突。",
                level="publish_blocker",
            ),
        ]

        summary = schedule_router._validation_result_payload(run_id=42, items=items)

        self.assertEqual(summary["status"], "FAILED")
        self.assertFalse(summary["publishable"])
        self.assertEqual(summary["hard_error_count"], 1)
        self.assertEqual(summary["publish_blocker_count"], 1)
        self.assertEqual(summary["warning_count"], 1)
        self.assertEqual(summary["info_count"], 1)
        self.assertEqual(items[0]["severity"], "warning")
        self.assertEqual(items[1]["severity"], "info")
        self.assertEqual(items[2]["severity"], "error")

    def test_unpublishable_validation_gate_uses_publishable_flag(self):
        validation = {
            "status": "FAILED",
            "publishable": False,
            "hard_error_count": 0,
            "publish_blocker_count": 1,
            "warning_count": 0,
            "items": [],
        }

        with self.assertRaises(schedule_router.HTTPException) as ctx:
            schedule_router._raise_if_unpublishable(validation)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不能发布", ctx.exception.detail["message"])
        self.assertIs(ctx.exception.detail["validation"], validation)

    def test_continuous_run_diagnostic_maps_to_publish_blocker_validation_item(self):
        items = schedule_router._diagnostic_validation_items([
            {
                "entity_type": "machine",
                "entity_id": "LINE-01",
                "severity": "critical",
                "level": "publish_blocker",
                "category": "maintenance",
                "code": "maintenance.continuous_run_cleaning_required",
                "root_cause": "LINE-01 连续运行超过上限。",
            }
        ])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], "publish_blocker")
        self.assertEqual(items[0]["severity"], "error")
        self.assertEqual(items[0]["code"], "maintenance.continuous_run_cleaning_required")
        self.assertIn("LINE-01", items[0]["message"])

    def test_experimental_disabled_continuous_run_diagnostic_maps_to_publish_blocker_validation_item(self):
        items = schedule_router._diagnostic_validation_items([
            {
                "entity_type": "schedule",
                "entity_id": "continuous_run",
                "severity": "critical",
                "level": "publish_blocker",
                "category": "maintenance",
                "code": "maintenance.continuous_run_experimental_disabled",
                "root_cause": "连续运行清场规则处于实验禁用模式，草案不得正式发布。",
            }
        ])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], "publish_blocker")
        self.assertEqual(items[0]["severity"], "error")
        self.assertEqual(items[0]["code"], "maintenance.continuous_run_experimental_disabled")
        self.assertIn("实验禁用", items[0]["message"])

    def test_unplaced_solver_failed_orders_map_to_publish_blockers(self):
        items = schedule_router._unplaced_solver_failed_validation_items([
            {
                "order_id": "ORD-MUST",
                "reason": "required_order_unplaced",
                "message": "Required order was not placed by the solver.",
            }
        ])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["level"], "publish_blocker")
        self.assertEqual(items[0]["severity"], "error")
        self.assertEqual(items[0]["code"], "required_order_unplaced")
        self.assertEqual(items[0]["order_id"], "ORD-MUST")
        self.assertIn("Required order", items[0]["message"])

    def test_validation_summary_rejects_missing_invalid_or_mismatched_summary(self):
        validation = {
            "status": "PASSED",
            "hard_error_count": 0,
            "warning_count": 1,
        }
        valid_summary = {
            "valid": True,
            "status": "PASSED",
            "hard_error_count": 0,
            "warning_count": 1,
            "validator_version": "preplan-validation-v1",
            "task_signature": "task-sig-001",
        }

        self.assertIsNone(
            schedule_router._validation_summary_mismatch(
                valid_summary,
                validation,
                current_task_signature="task-sig-001",
            )
        )
        self.assertIn(
            "重新校验",
            schedule_router._validation_summary_mismatch(
                None,
                validation,
                current_task_signature="task-sig-001",
            ),
        )
        self.assertIn(
            "已失效",
            schedule_router._validation_summary_mismatch(
                {**valid_summary, "valid": False, "invalid_reason": "manual_adjustment"},
                validation,
                current_task_signature="task-sig-001",
            ),
        )
        self.assertIn(
            "任务已变化",
            schedule_router._validation_summary_mismatch(
                valid_summary,
                validation,
                current_task_signature="task-sig-002",
            ),
        )


if __name__ == "__main__":
    unittest.main()
