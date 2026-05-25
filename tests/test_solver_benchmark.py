import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.solver_benchmark import (
    BenchmarkCase,
    PROFILE_ACCEPTANCE_DEFAULTS,
    build_sprint5_baseline_cases,
    main,
    run_benchmark_suite,
)


class TestSolverBenchmark(unittest.TestCase):
    def test_sprint5_baseline_cases_cover_scale_targets_and_profiles(self):
        cases = build_sprint5_baseline_cases(
            order_counts=[50, 100, 200, 300],
            profiles=["fast", "standard"],
            machine_count=4,
            max_wall_time_seconds=90.0,
        )

        self.assertEqual(
            [case.name for case in cases],
            [
                "sprint5-fast-50-baseline",
                "sprint5-fast-100-baseline",
                "sprint5-fast-200-baseline",
                "sprint5-fast-300-baseline",
                "sprint5-standard-50-baseline",
                "sprint5-standard-100-baseline",
                "sprint5-standard-200-baseline",
                "sprint5-standard-300-baseline",
            ],
        )
        self.assertEqual([case.order_count for case in cases], [50, 100, 200, 300, 50, 100, 200, 300])
        self.assertEqual({case.machine_count for case in cases}, {4})
        self.assertEqual({case.max_wall_time_seconds for case in cases}, {90.0})
        self.assertTrue(all(case.comparison_group is None for case in cases))
        self.assertTrue(all(not case.arc_pruning_enabled for case in cases))

    def test_benchmark_suite_returns_pass_fail_summary(self):
        summary = run_benchmark_suite([
            BenchmarkCase(name="tiny", order_count=3, machine_count=1, max_wall_time_seconds=10.0),
        ])

        self.assertEqual(summary["case_count"], 1)
        self.assertEqual(summary["status"], "PASS")
        self.assertEqual(summary["schema_version"], "solver-benchmark-v1")
        self.assertIn("generated_at", summary)
        self.assertEqual(summary["case_configs"], [{
            "name": "tiny",
            "order_count": 3,
            "machine_count": 1,
            "profile": "fast",
            "max_wall_time_seconds": 10.0,
            "max_gap": None,
            "min_scheduled_ratio": 0.0,
            "max_late_order_count": None,
            "max_weighted_tardiness": None,
            "max_total_setup_time_mins": None,
            "max_pruning_late_order_delta": None,
            "max_pruning_weighted_tardiness_delta": None,
            "max_pruning_setup_time_delta_mins": None,
            "profile_acceptance_policy": {
                "profile": "fast",
                "max_wall_time_seconds": 10.0,
                "max_gap": PROFILE_ACCEPTANCE_DEFAULTS["fast"]["max_gap"],
                "min_scheduled_ratio": 0.0,
                "max_late_order_count": None,
                "max_weighted_tardiness": None,
                "max_total_setup_time_mins": None,
            },
            "arc_pruning_enabled": False,
            "arc_pruning_max_setup_mins": 0,
            "arc_pruning_top_k_per_order": 0,
            "arc_pruning_same_material_family_top_k": 0,
            "arc_pruning_same_cleanroom_top_k": 0,
            "arc_pruning_due_window_mins": 0,
            "arc_pruning_due_window_top_k": 0,
        }])
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
        self.assertIn("deferred_reason_counts", case)
        self.assertIn("machine_load", case)
        self.assertIn("phase_metrics", case)
        self.assertEqual(case["profile_acceptance_policy"], summary["case_configs"][0]["profile_acceptance_policy"])
        self.assertEqual(case["baseline_metrics"], {
            "solver_status": case["solver_status"],
            "wall_time_seconds": case["wall_time_seconds"],
            "gap": case["gap"],
            "late_order_count": case["late_order_count"],
            "weighted_tardiness": case["weighted_tardiness"],
            "total_setup_time_mins": case["total_setup_time_mins"],
            "machine_load": case["machine_load"],
        })
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

    def test_benchmark_command_can_compare_multiple_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "profiles.json")
            exit_code = main([
                "--order-counts", "3",
                "--machine-count", "1",
                "--profiles", "fast,standard",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["case_count"], 2)
        self.assertEqual([case["profile"] for case in summary["cases"]], ["fast", "standard"])
        self.assertEqual([case["order_count"] for case in summary["cases"]], [3, 3])
        self.assertEqual([case["name"] for case in summary["cases"]], ["fast-3", "standard-3"])
        self.assertEqual(summary["profile_acceptance"]["fast"]["case_count"], 1)
        self.assertEqual(summary["profile_acceptance"]["standard"]["case_count"], 1)
        self.assertIn("acceptance_policy", summary["profile_acceptance"]["standard"])
        self.assertIn("max_wall_time_seconds", summary["profile_acceptance"]["standard"])
        self.assertIn("min_scheduled_ratio", summary["profile_acceptance"]["standard"])
        self.assertIn("deferred_reason_counts", summary["profile_acceptance"]["standard"])

    def test_sprint5_baseline_uses_profile_default_thresholds_when_not_overridden(self):
        cases = build_sprint5_baseline_cases(
            order_counts=[50],
            profiles=["fast", "standard", "deep"],
            machine_count=4,
        )

        by_profile = {case.profile: case for case in cases}
        for profile, defaults in PROFILE_ACCEPTANCE_DEFAULTS.items():
            self.assertEqual(by_profile[profile].max_wall_time_seconds, defaults["max_wall_time_seconds"])
            self.assertEqual(by_profile[profile].max_gap, defaults["max_gap"])
            self.assertEqual(by_profile[profile].min_scheduled_ratio, defaults["min_scheduled_ratio"])

    def test_benchmark_summary_records_profile_acceptance_policy_snapshot(self):
        summary = run_benchmark_suite([
            BenchmarkCase(
                name="fast-policy",
                order_count=3,
                machine_count=1,
                profile="fast",
                max_wall_time_seconds=10,
                max_gap=0.5,
                min_scheduled_ratio=0.75,
            ),
            BenchmarkCase(
                name="standard-policy",
                order_count=3,
                machine_count=1,
                profile="standard",
                max_wall_time_seconds=20,
                max_gap=0.2,
                min_scheduled_ratio=0.9,
            ),
        ])

        fast_policy = summary["cases"][0]["profile_acceptance_policy"]
        self.assertEqual(fast_policy["profile"], "fast")
        self.assertEqual(fast_policy["max_wall_time_seconds"], 10)
        self.assertEqual(fast_policy["max_gap"], 0.5)
        self.assertEqual(fast_policy["min_scheduled_ratio"], 0.75)
        self.assertEqual(summary["profile_acceptance"]["fast"]["acceptance_policy"], fast_policy)
        self.assertEqual(summary["profile_acceptance"]["standard"]["acceptance_policy"]["max_wall_time_seconds"], 20)

    def test_benchmark_command_uses_sprint5_baseline_case_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sprint5-baseline.json")
            exit_code = main([
                "--sprint5-baseline",
                "--order-counts", "3,4",
                "--machine-count", "1",
                "--profiles", "fast,standard",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [case["name"] for case in summary["cases"]],
            [
                "sprint5-fast-3-baseline",
                "sprint5-fast-4-baseline",
                "sprint5-standard-3-baseline",
                "sprint5-standard-4-baseline",
            ],
        )
        self.assertEqual(summary["case_count"], 4)
        self.assertEqual(summary["profile_acceptance"]["fast"]["case_count"], 2)
        self.assertEqual(summary["profile_acceptance"]["standard"]["case_count"], 2)

    def test_sprint5_baseline_can_generate_arc_pruning_comparison_matrix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sprint5-compare.json")
            exit_code = main([
                "--sprint5-baseline",
                "--compare-arc-pruning",
                "--order-counts", "3,4",
                "--machine-count", "1",
                "--profiles", "fast,standard",
                "--arc-pruning-max-setup-mins", "999",
                "--arc-pruning-top-k-per-order", "3",
                "--arc-pruning-same-material-family-top-k", "3",
                "--arc-pruning-same-cleanroom-top-k", "3",
                "--arc-pruning-due-window-mins", "1440",
                "--arc-pruning-due-window-top-k", "3",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["case_count"], 8)
        self.assertEqual(len(summary["arc_pruning_comparisons"]), 4)
        self.assertEqual(summary["scale_acceptance"]["3"]["case_count"], 4)
        self.assertEqual(summary["scale_acceptance"]["4"]["case_count"], 4)
        self.assertEqual(summary["scale_acceptance"]["3"]["comparison_count"], 2)
        self.assertEqual(
            [case["name"] for case in summary["cases"][:2]],
            [
                "sprint5-fast-3-pruning-off",
                "sprint5-fast-3-pruning-on",
            ],
        )
        self.assertEqual(summary["cases"][1]["arc_pruning_policy"], {
            "enabled": True,
            "max_setup_time_mins": 999,
            "top_k_per_order": 3,
            "same_material_family_top_k": 3,
            "same_cleanroom_top_k": 3,
            "due_window_mins": 1440,
            "due_window_top_k": 3,
        })

    def test_benchmark_script_runs_directly_from_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "direct-summary.json")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/solver_benchmark.py",
                    "--sprint5-baseline",
                    "--order-counts",
                    "1",
                    "--machine-count",
                    "1",
                    "--profiles",
                    "fast",
                    "--output",
                    path,
                    "--max-wall-time-seconds",
                    "10",
                ],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(os.path.exists(path))

    def test_benchmark_command_passes_arc_pruning_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pruning.json")
            exit_code = main([
                "--order-counts", "1",
                "--machine-count", "1",
                "--arc-pruning-enabled",
                "--arc-pruning-max-setup-mins", "999",
                "--arc-pruning-top-k-per-order", "1",
                "--arc-pruning-same-material-family-top-k", "1",
                "--arc-pruning-same-cleanroom-top-k", "1",
                "--arc-pruning-due-window-mins", "1440",
                "--arc-pruning-due-window-top-k", "2",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        case = summary["cases"][0]
        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_enabled"], True)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_max_setup_mins"], 999)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_top_k_per_order"], 1)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_same_material_family_top_k"], 1)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_same_cleanroom_top_k"], 1)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_due_window_mins"], 1440)
        self.assertEqual(summary["case_configs"][0]["arc_pruning_due_window_top_k"], 2)
        self.assertEqual(case["arc_pruning_policy"], {
            "enabled": True,
            "max_setup_time_mins": 999,
            "top_k_per_order": 1,
            "same_material_family_top_k": 1,
            "same_cleanroom_top_k": 1,
            "due_window_mins": 1440,
            "due_window_top_k": 2,
        })
        self.assertEqual(case["model_size"]["arc_pruning_policy"]["top_k_per_order"], 1)
        self.assertGreaterEqual(case["model_size"]["pruned_arc_count"], 0)

    def test_benchmark_command_compares_arc_pruning_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "compare-pruning.json")
            exit_code = main([
                "--order-counts", "3",
                "--machine-count", "1",
                "--compare-arc-pruning",
                "--arc-pruning-max-setup-mins", "999",
                "--arc-pruning-top-k-per-order", "1",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["case_count"], 2)
        self.assertEqual(
            [case["arc_pruning_policy"]["enabled"] for case in summary["cases"]],
            [False, True],
        )
        self.assertEqual(len(summary["arc_pruning_comparisons"]), 1)
        comparison = summary["arc_pruning_comparisons"][0]
        self.assertEqual(comparison["baseline_case"], "fast-3-pruning-off")
        self.assertEqual(comparison["pruned_case"], "fast-3-pruning-on")
        for key in [
            "wall_time_seconds_delta",
            "late_order_count_delta",
            "weighted_tardiness_delta",
            "total_setup_time_mins_delta",
            "arc_count_delta",
            "pruned_arc_count_delta",
        ]:
            self.assertIn(key, comparison)

    def test_benchmark_command_fails_when_arc_pruning_degrades_quality_beyond_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "compare-pruning-threshold.json")
            exit_code = main([
                "--order-counts", "3",
                "--machine-count", "1",
                "--compare-arc-pruning",
                "--arc-pruning-max-setup-mins", "999",
                "--arc-pruning-top-k-per-order", "1",
                "--max-pruning-setup-time-delta-mins", "-1",
                "--output", path,
                "--max-wall-time-seconds", "10",
            ])
            with open(path, encoding="utf-8") as f:
                summary = json.load(f)

        self.assertEqual(exit_code, 1)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["failed_count"], 1)
        comparison = summary["arc_pruning_comparisons"][0]
        self.assertFalse(comparison["passed"])
        self.assertIn("total_setup_time_mins_delta", comparison["failed_checks"])

    def test_benchmark_command_writes_markdown_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "summary.json")
            report_path = os.path.join(tmp, "benchmark-report.md")
            exit_code = main([
                "--order-counts", "3",
                "--machine-count", "1",
                "--compare-arc-pruning",
                "--arc-pruning-max-setup-mins", "999",
                "--arc-pruning-top-k-per-order", "1",
                "--output", path,
                "--report-md", report_path,
                "--max-wall-time-seconds", "10",
            ])
            with open(report_path, encoding="utf-8") as f:
                report = f.read()

        self.assertEqual(exit_code, 0)
        self.assertIn("# Solver Benchmark Report", report)
        self.assertIn("## Cases", report)
        self.assertIn("## Profile Acceptance", report)
        self.assertIn("Acceptance Policy", report)
        self.assertIn("## Scale Acceptance", report)
        self.assertIn("## Baseline Metrics", report)
        self.assertIn("## Machine Model Sizes", report)
        self.assertIn("Weighted Tardiness", report)
        self.assertIn("Arc Pruning Strategy", report)
        self.assertIn("same_material_family_top_k", report)
        self.assertIn("Eligible Orders | Assignments | Optional Candidates | Arcs | Pruned Arcs | Setup Cache", report)
        self.assertIn("## Deferred Reasons", report)
        self.assertIn("Min Scheduled Ratio | Acceptance Policy | Deferred Reasons | Failed Checks", report)
        self.assertIn("fast-3-pruning-off", report)
        self.assertIn("fast-3-pruning-on", report)
        self.assertIn("## Arc Pruning Comparisons", report)
        self.assertIn("arc_count_delta", report)


if __name__ == "__main__":
    unittest.main()
