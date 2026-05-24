import unittest

from api.routers.dashboard import _schedule_summary_counts


class TestDashboardSummaryCounts(unittest.TestCase):
    def test_uses_persisted_solver_summary_counts(self):
        counts = _schedule_summary_counts({
            "total_orders": 105,
            "solver_params": {
                "summary": {
                    "input_order_count": 232,
                    "schedulable_order_count": 105,
                    "blocked_order_count": 127,
                    "deferred_order_count": 7,
                    "unplaced_solver_failed_order_count": 2,
                    "deferred_reason_counts": {
                        "candidate_optional_rejected": 5,
                        "planning_window_deferred": 2,
                    },
                }
            },
        })

        self.assertEqual(counts["input_order_count"], 232)
        self.assertEqual(counts["scheduled_order_count"], 105)
        self.assertEqual(counts["schedulable_order_count"], 105)
        self.assertEqual(counts["blocked_order_count"], 127)
        self.assertEqual(counts["deferred_order_count"], 7)
        self.assertEqual(counts["unplaced_solver_failed_order_count"], 2)
        self.assertEqual(counts["deferred_reason_counts"], {
            "candidate_optional_rejected": 5,
            "planning_window_deferred": 2,
        })

    def test_falls_back_to_scheduled_count_without_solver_summary(self):
        counts = _schedule_summary_counts({
            "total_orders": 8,
            "solver_params": None,
        })

        self.assertEqual(counts["input_order_count"], 8)
        self.assertEqual(counts["scheduled_order_count"], 8)
        self.assertEqual(counts["schedulable_order_count"], 8)
        self.assertEqual(counts["blocked_order_count"], 0)
        self.assertEqual(counts["deferred_order_count"], 0)
        self.assertEqual(counts["unplaced_solver_failed_order_count"], 0)
        self.assertEqual(counts["deferred_reason_counts"], {})


if __name__ == "__main__":
    unittest.main()
