import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from api.routers import schedule as schedule_router


class CountingSchemaCursor:
    def __init__(self):
        self.execute_count = 0

    def execute(self, *_args, **_kwargs):
        self.execute_count += 1


class CountingSchemaDb:
    def __init__(self):
        self.cursor_instance = CountingSchemaCursor()
        self.commit_count = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_count += 1

    def get_dsn_parameters(self):
        return {
            "host": "localhost",
            "port": "5432",
            "dbname": "aps_test_schema_cache",
            "user": "aps_test",
        }


class FailingAdjustmentCursor:
    def __init__(self):
        self.execute_count = 0

    def execute(self, sql, *_args, **_kwargs):
        self.execute_count += 1
        if "FROM scheduled_tasks t" in sql:
            raise RuntimeError("forced scheduled task lookup failure")

    def fetchone(self):
        return {"run_id": 7, "lifecycle_status": "DRAFT"}


class FailingAdjustmentDb:
    def __init__(self):
        self.cursor_instance = FailingAdjustmentCursor()
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class TestManualAdjustmentTransaction(unittest.TestCase):
    def test_planning_schema_is_cached_per_database_connection_target(self):
        db = CountingSchemaDb()
        original_cache = set(schedule_router._PLANNING_SCHEMA_READY)
        schedule_router._PLANNING_SCHEMA_READY.clear()
        try:
            schedule_router._ensure_planning_schema(db)
            first_execute_count = db.cursor_instance.execute_count
            first_commit_count = db.commit_count

            schedule_router._ensure_planning_schema(db)

            self.assertGreater(first_execute_count, 0)
            self.assertEqual(db.cursor_instance.execute_count, first_execute_count)
            self.assertEqual(db.commit_count, first_commit_count)
        finally:
            schedule_router._PLANNING_SCHEMA_READY.clear()
            schedule_router._PLANNING_SCHEMA_READY.update(original_cache)

    def test_manual_adjustment_rolls_back_unexpected_database_errors(self):
        db = FailingAdjustmentDb()
        payload = schedule_router.ManualAdjustmentPayload(
            order_id="ORD-ROLLBACK",
            machine_id="BF-01",
            start_time=datetime(2026, 5, 24, 8, 0),
            end_time=datetime(2026, 5, 24, 8, 0) + timedelta(hours=2),
            reason_text="rollback regression",
        )
        settings = {
            **schedule_router.POLICY_DEFAULTS,
            "manual_adjust_reason_required": False,
        }

        with patch.object(schedule_router, "_get_schedule_settings", return_value=settings):
            with self.assertRaises(RuntimeError):
                schedule_router.apply_manual_adjustment(
                    run_id=7,
                    payload=payload,
                    db=db,
                    user=SimpleNamespace(username="planner"),
                )

        self.assertEqual(db.rollback_count, 1)
        self.assertEqual(db.commit_count, 0)


if __name__ == "__main__":
    unittest.main()
