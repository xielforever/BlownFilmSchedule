import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from api.routers import machines as machines_router
from api.routers.machines import _continuous_run_mins_after_schedule
from src.config import MANDATORY_CLEANING_DURATION_MINUTES


def dt(hour):
    return datetime(2026, 5, 19, hour, 0)


class TestMachineStateHelpers(unittest.TestCase):
    def test_continuous_run_adds_schedule_span_to_initial_state(self):
        tasks = [{
            "setup_start_time": dt(8),
            "start_time": dt(9),
            "end_time": dt(11),
        }]

        self.assertEqual(_continuous_run_mins_after_schedule(30, tasks), 210)

    def test_continuous_run_resets_after_cleaning_sized_gap(self):
        first_end = dt(10)
        second_setup = first_end + timedelta(minutes=MANDATORY_CLEANING_DURATION_MINUTES)
        tasks = [
            {
                "setup_start_time": dt(8),
                "start_time": dt(9),
                "end_time": first_end,
            },
            {
                "setup_start_time": second_setup,
                "start_time": second_setup + timedelta(minutes=30),
                "end_time": second_setup + timedelta(minutes=90),
            },
        ]

        self.assertEqual(_continuous_run_mins_after_schedule(120, tasks), 90)

    def test_machine_capability_update_marks_screening_cache_stale(self):
        class Cursor:
            def __init__(self):
                self.rowcount = 0
                self.sql = []

            def execute(self, sql, params=None):
                self.sql.append(" ".join(sql.split()).lower())
                if self.sql[-1].startswith("update machines"):
                    self.rowcount = 1

        class Db:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.commit_count = 0

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.commit_count += 1

        db = Db()

        with patch.object(machines_router, "_mark_order_screening_cache_stale") as mark_stale:
            result = machines_router.update_machine(
                "LINE-01",
                machines_router.MachineUpdate(max_width=1800),
                db=db,
                _=SimpleNamespace(username="planner"),
            )

        self.assertEqual(result, {"machine_id": "LINE-01", "updated": ["max_width"]})
        mark_stale.assert_called_once_with(db.cursor_obj, reason="machine_capability_changed")
        self.assertEqual(db.commit_count, 1)

    def test_machine_state_update_marks_screening_cache_stale(self):
        class Cursor:
            def __init__(self):
                self.rowcount = 0
                self.sql = []

            def execute(self, sql, params=None):
                self.sql.append(" ".join(sql.split()).lower())
                if self.sql[-1].startswith("update machine_current_state"):
                    self.rowcount = 1

        class Db:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.commit_count = 0

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.commit_count += 1

        db = Db()

        with patch.object(machines_router, "_mark_order_screening_cache_stale") as mark_stale:
            result = machines_router.update_machine(
                "LINE-01",
                machines_router.MachineUpdate(current_materials=["A", "B", "A"]),
                db=db,
                _=SimpleNamespace(username="planner"),
            )

        self.assertEqual(result, {"machine_id": "LINE-01", "updated": ["current_materials"]})
        mark_stale.assert_called_once_with(db.cursor_obj, reason="machine_state_changed")
        self.assertEqual(db.commit_count, 1)

    def test_apply_schedule_end_state_marks_screening_cache_stale(self):
        class Cursor:
            def __init__(self):
                self.rows = []

            def execute(self, sql, params=None):
                normalized = " ".join(sql.split()).lower()
                if normalized.startswith("select run_id from schedule_runs"):
                    self.rows = [{"run_id": 7}]
                    return
                if normalized.startswith("select machine_id, coalesce(continuous_run_mins"):
                    self.rows = [{"machine_id": "LINE-01", "continuous_run_mins": 0, "last_order_id": None}]
                    return
                if "returning machine_id, current_material_lanes" in normalized:
                    self.rows = [{
                        "machine_id": "LINE-01",
                        "current_material_lanes": ["A", "B", "A"],
                        "current_width": 500,
                        "current_thickness": 35,
                        "current_corona": True,
                        "current_core_size": 3,
                        "last_order_id": "ORD-001",
                    }]
                    return
                if normalized.startswith("select t.machine_id, t.setup_start_time"):
                    self.rows = []
                    return
                self.rows = []

            def fetchone(self):
                return self.rows[0] if self.rows else None

            def fetchall(self):
                return list(self.rows)

        class Db:
            def __init__(self):
                self.cursor_obj = Cursor()
                self.commit_count = 0

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.commit_count += 1

        db = Db()

        with patch.object(machines_router, "_mark_order_screening_cache_stale") as mark_stale:
            result = machines_router.apply_schedule_end_state(
                run_id=7,
                db=db,
                _=SimpleNamespace(username="planner"),
            )

        self.assertEqual(result["run_id"], 7)
        self.assertEqual(result["applied_count"], 1)
        mark_stale.assert_called_once_with(db.cursor_obj, reason="machine_state_changed")
        self.assertEqual(db.commit_count, 1)


if __name__ == "__main__":
    unittest.main()
