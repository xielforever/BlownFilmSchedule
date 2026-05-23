import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from api.routers import schedule as schedule_router


class TestQueueTransitions(unittest.TestCase):
    def test_allows_normal_execution_progression(self):
        self.assertIsNone(schedule_router._validate_queue_transition("QUEUED", "READY", ""))
        self.assertIsNone(schedule_router._validate_queue_transition("READY", "IN_PRODUCTION", ""))
        self.assertIsNone(schedule_router._validate_queue_transition("IN_PRODUCTION", "COMPLETED", ""))

    def test_requires_reason_for_hold_and_cancel(self):
        with self.assertRaises(HTTPException) as hold_ctx:
            schedule_router._validate_queue_transition("READY", "ON_HOLD", "")
        self.assertEqual(hold_ctx.exception.status_code, 400)
        self.assertIn("原因", str(hold_ctx.exception.detail))

        with self.assertRaises(HTTPException) as cancel_ctx:
            schedule_router._validate_queue_transition("QUEUED", "CANCELLED", "")
        self.assertEqual(cancel_ctx.exception.status_code, 400)
        self.assertIn("原因", str(cancel_ctx.exception.detail))

        self.assertIsNone(schedule_router._validate_queue_transition("READY", "ON_HOLD", "设备临时保养"))
        self.assertIsNone(schedule_router._validate_queue_transition("QUEUED", "CANCELLED", "客户取消"))

    def test_rejects_invalid_and_terminal_transitions(self):
        with self.assertRaises(HTTPException):
            schedule_router._validate_queue_transition("QUEUED", "COMPLETED", "")
        with self.assertRaises(HTTPException):
            schedule_router._validate_queue_transition("COMPLETED", "READY", "")
        with self.assertRaises(HTTPException):
            schedule_router._validate_queue_transition("CANCELLED", "READY", "")

    def test_maps_queue_status_to_order_status(self):
        self.assertEqual(schedule_router._order_status_for_queue_status("QUEUED"), "SCHEDULED")
        self.assertEqual(schedule_router._order_status_for_queue_status("READY"), "SCHEDULED")
        self.assertEqual(schedule_router._order_status_for_queue_status("IN_PRODUCTION"), "IN_PRODUCTION")
        self.assertEqual(schedule_router._order_status_for_queue_status("COMPLETED"), "COMPLETED")
        self.assertEqual(schedule_router._order_status_for_queue_status("CANCELLED"), "PENDING")

    def test_update_queue_item_progresses_status_and_records_audit(self):
        db = _QueueTransitionDb("QUEUED")
        payload = schedule_router.QueueStatusUpdatePayload(queue_status="READY", reason="备料完成")

        result = schedule_router.update_manufacturing_queue_item(
            queue_id=1,
            payload=payload,
            db=db,
            user=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["queue_status"], "READY")
        self.assertEqual(db.queue["queue_status"], "READY")
        self.assertEqual(db.orders["ORD-Q-001"]["status"], "SCHEDULED")
        self.assertEqual(len(db.schedule_publish_audit), 1)
        audit = db.schedule_publish_audit[0]
        self.assertEqual(audit["event_type"], "QUEUE_STATUS_CHANGE")
        self.assertEqual(audit["details"]["from_status"], "QUEUED")
        self.assertEqual(audit["details"]["to_status"], "READY")
        self.assertEqual(audit["details"]["reason"], "备料完成")
        self.assertTrue(db.committed)

    def test_update_queue_item_syncs_in_progress_and_completed_order_status(self):
        db = _QueueTransitionDb("READY")

        in_progress = schedule_router.update_manufacturing_queue_item(
            queue_id=1,
            payload=schedule_router.QueueStatusUpdatePayload(queue_status="IN_PRODUCTION"),
            db=db,
            user=SimpleNamespace(username="planner"),
        )

        self.assertEqual(in_progress["queue_status"], "IN_PRODUCTION")
        self.assertEqual(db.orders["ORD-Q-001"]["status"], "IN_PRODUCTION")
        self.assertIsNotNone(db.queue["started_at"])

        completed = schedule_router.update_manufacturing_queue_item(
            queue_id=1,
            payload=schedule_router.QueueStatusUpdatePayload(queue_status="COMPLETED"),
            db=db,
            user=SimpleNamespace(username="planner"),
        )

        self.assertEqual(completed["queue_status"], "COMPLETED")
        self.assertEqual(db.orders["ORD-Q-001"]["status"], "COMPLETED")
        self.assertIsNotNone(db.queue["completed_at"])

    def test_update_queue_item_rejects_cancel_without_reason_before_audit(self):
        db = _QueueTransitionDb("QUEUED")

        with self.assertRaises(HTTPException) as ctx:
            schedule_router.update_manufacturing_queue_item(
                queue_id=1,
                payload=schedule_router.QueueStatusUpdatePayload(queue_status="CANCELLED"),
                db=db,
                user=SimpleNamespace(username="planner"),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(db.schedule_publish_audit, [])
        self.assertFalse(db.committed)


class _QueueTransitionCursor:
    def __init__(self, db):
        self.db = db
        self._rows = []
        self.rowcount = 0

    @staticmethod
    def _unwrap(value):
        return getattr(value, "adapted", getattr(value, "obj", value))

    def execute(self, sql, params=None):
        params = list(params or [])
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0

        if normalized.startswith("alter table"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists"):
            self._rows = []
            return
        if normalized.startswith("insert into schedule_settings"):
            self._rows = []
            return
        if normalized.startswith("update schedule_runs set lifecycle_status='confirmed'"):
            self._rows = []
            return

        if "from manufacturing_queue q" in normalized and "where q.id=%s" in normalized:
            queue_id = params[0]
            if queue_id == self.db.queue["id"]:
                self._rows = [{
                    **self.db.queue,
                    "is_active": self.db.run["is_active"],
                    "lifecycle_status": self.db.run["lifecycle_status"],
                    "product_type": "Film-A",
                    "target_width": 520,
                    "target_thickness": 35,
                    "total_quantity_kg": 1200,
                    "order_class": "NORMAL",
                }]
            else:
                self._rows = []
            return

        if normalized.startswith("update manufacturing_queue"):
            target_status = params[0]
            queue_id = params[-1]
            if queue_id == self.db.queue["id"]:
                self.db.queue["queue_status"] = target_status
                if target_status == "IN_PRODUCTION" and not self.db.queue["started_at"]:
                    self.db.queue["started_at"] = datetime.now(timezone.utc)
                if target_status == "COMPLETED":
                    self.db.queue["completed_at"] = datetime.now(timezone.utc)
                self.rowcount = 1
            self._rows = []
            return

        if normalized.startswith("update production_orders"):
            status, order_id = params[0], params[1]
            if order_id in self.db.orders:
                self.db.orders[order_id]["status"] = status
                self.rowcount = 1
            self._rows = []
            return

        if normalized.startswith("insert into schedule_publish_audit"):
            details = self._unwrap(params[6])
            self.db.schedule_publish_audit.append({
                "run_id": params[0],
                "event_type": params[1],
                "actor": params[2],
                "selected_order_count": params[3],
                "warning_count": params[4],
                "queue_row_count": params[5],
                "details": details,
            })
            self.rowcount = 1
            self._rows = []
            return

        raise AssertionError(f"Unexpected SQL: {normalized}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _QueueTransitionDb:
    def __init__(self, queue_status):
        self.run = {"run_id": 77, "is_active": True, "lifecycle_status": "CONFIRMED"}
        self.queue = {
            "id": 1,
            "run_id": 77,
            "scheduled_task_id": 501,
            "order_id": "ORD-Q-001",
            "machine_id": "BF-01",
            "sequence_index": 1,
            "planned_start_time": datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc),
            "planned_end_time": datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc),
            "queue_status": queue_status,
            "released_by": "planner",
            "released_at": datetime(2026, 5, 23, 7, 0, tzinfo=timezone.utc),
            "started_at": datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc) if queue_status == "IN_PRODUCTION" else None,
            "completed_at": None,
        }
        self.orders = {"ORD-Q-001": {"status": "SCHEDULED"}}
        self.schedule_publish_audit = []
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return _QueueTransitionCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


if __name__ == "__main__":
    unittest.main()
