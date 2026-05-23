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
