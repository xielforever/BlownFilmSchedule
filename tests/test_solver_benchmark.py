import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.solver_benchmark import BenchmarkCase, main, run_benchmark_suite


class TestSolverBenchmark(unittest.TestCase):
    def test_benchmark_suite_returns_pass_fail_summary(self):
        summary = run_benchmark_suite([
            BenchmarkCase(name="tiny", order_count=3, machine_count=1, max_wall_time_seconds=10.0),
        ])

        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["status"], "PASS")
        case = summary["cases"][0]
        self.assertEqual(case["name"], "tiny")
        self.assertEqual(case["order_count"], 3)
        self.assertIn("passed", case)
        self.assertIn("solver_status", case)
        self.assertIn("model_size", case)
        self.assertIn("wall_time_seconds", case)
        self.assertIn("scheduled_ratio", case)
        self.assertIn("late_order_count", case)
        self.assertIn("weighted_tardiness", case)
        self.assertIn("total_setup_time_mins", case)
        self.assertIn("machine_load", case)
        self.assertIn("phase_metrics", case)
        self.assertIsInstance(case["machine_load"], dict)

    def test_benchmark_case_fails_when_scheduled_ratio_is_below_threshold(self):
        summary = run_benchmark_suite([
            BenchmarkCase(
                name="ratio-threshold",
                order_count=3,
                machine_count=1,
                max_wall_time_seconds=10.0,
                min_scheduled_ratio=1.1,
            ),
        ])

        self.assertEqual(summary["status"], "FAIL")
        self.assertFalse(summary["cases"][0]["passed"])
        self.assertLess(summary["cases"][0]["scheduled_ratio"], 1.1)

    def test_benchmark_case_fails_when_business_quality_thresholds_are_exceeded(self):
        summary = run_benchmark_suite([
            BenchmarkCase(
                name="quality-threshold",
                order_count=3,
                machine_count=1,
                max_wall_time_seconds=10.0,
                max_late_order_count=0,
                max_weighted_tardiness=0,
                max_total_setup_time_mins=0,
            ),
        ])

        case = summary["cases"][0]
        self.assertEqual(summary["status"], "FAIL")
        self.assertFalse(case["passed"])
        self.assertIn("quality_thresholds", case)
        self.assertEqual(case["quality_thresholds"]["max_late_order_count"], 0)
        self.assertEqual(case["quality_thresholds"]["max_weighted_tardiness"], 0)
        self.assertEqual(case["quality_thresholds"]["max_total_setup_time_mins"], 0)
        self.assertIn("total_setup_time_mins", case["failed_checks"])

    def test_benchmark_command_writes_summary_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.json")
            exit_code = main([
                "--order-counts", "3",
                "--machine-count", "1",
                "--output", path,
                "--max-wall-time-seconds", "10",
                "--max-late-order-count", "5",
                "--max-weighted-tardiness", "1000",
                "--max-total-setup-time-mins", "1000",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["cases"][0]["order_count"], 3)
        self.assertEqual(summary["cases"][0]["quality_thresholds"]["max_late_order_count"], 5)
        self.assertEqual(summary["cases"][0]["quality_thresholds"]["max_weighted_tardiness"], 1000)
        self.assertEqual(summary["cases"][0]["quality_thresholds"]["max_total_setup_time_mins"], 1000)
        self.assertIn("status", summary)


if __name__ == "__main__":
    unittest.main()
