import unittest
from datetime import datetime, timedelta

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


if __name__ == "__main__":
    unittest.main()
