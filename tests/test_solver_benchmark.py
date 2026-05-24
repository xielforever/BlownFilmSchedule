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

    def test_benchmark_command_writes_summary_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.json")
            exit_code = main([
                "--order-counts", "3",
                "--machine-count", "1",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["cases"][0]["order_count"], 3)
        self.assertIn("status", summary)


if __name__ == "__main__":
    unittest.main()
