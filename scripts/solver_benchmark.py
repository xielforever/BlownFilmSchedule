from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, List

from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.scheduler import AdvancedMedicalAPS
from src.setup_matrices import SetupMatricesManager


PASS_STATUSES = {"OPTIMAL", "FEASIBLE", "PARTIAL", "UNPUBLISHABLE"}
SUMMARY_SCHEMA_VERSION = "solver-benchmark-v1"


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    order_count: int
    machine_count: int = 2
    profile: str = "fast"
    max_wall_time_seconds: float = 120.0
    max_gap: float | None = None
    min_scheduled_ratio: float = 0.0
    max_late_order_count: int | None = None
    max_weighted_tardiness: int | None = None
    max_total_setup_time_mins: int | None = None
    max_pruning_late_order_delta: int | None = None
    max_pruning_weighted_tardiness_delta: int | None = None
    max_pruning_setup_time_delta_mins: int | None = None
    arc_pruning_enabled: bool = False
    arc_pruning_max_setup_mins: int = 0
    arc_pruning_top_k_per_order: int = 0
    comparison_group: str | None = None
    comparison_variant: str | None = None


def _make_setup_mgr() -> SetupMatricesManager:
    mgr = SetupMatricesManager()
    mgr.same_material_time = 30
    mgr.material_switch_matrix[("Standard_Med_LDPE", "Borealis_LE6601-PH")] = 120
    mgr.width_up_rules = [(999, 0)]
    mgr.width_down_rules = [(999, 0)]
    mgr.thickness_rules = [(999, 0)]
    mgr.corona_switch_time = 0
    mgr.core_size_switch_time = 0
    return mgr


def _case_config(case: BenchmarkCase) -> dict:
    config = {
        "name": case.name,
        "order_count": case.order_count,
        "machine_count": case.machine_count,
        "profile": case.profile,
        "max_wall_time_seconds": case.max_wall_time_seconds,
        "max_gap": case.max_gap,
        "min_scheduled_ratio": case.min_scheduled_ratio,
        "max_late_order_count": case.max_late_order_count,
        "max_weighted_tardiness": case.max_weighted_tardiness,
        "max_total_setup_time_mins": case.max_total_setup_time_mins,
        "max_pruning_late_order_delta": case.max_pruning_late_order_delta,
        "max_pruning_weighted_tardiness_delta": case.max_pruning_weighted_tardiness_delta,
        "max_pruning_setup_time_delta_mins": case.max_pruning_setup_time_delta_mins,
        "arc_pruning_enabled": case.arc_pruning_enabled,
        "arc_pruning_max_setup_mins": case.arc_pruning_max_setup_mins,
        "arc_pruning_top_k_per_order": case.arc_pruning_top_k_per_order,
    }
    if case.comparison_group:
        config["comparison_group"] = case.comparison_group
    if case.comparison_variant:
        config["comparison_variant"] = case.comparison_variant
    return config


def _make_machine(index: int) -> BlownFilmMachineModel:
    return BlownFilmMachineModel.from_dict({
        "machineId": f"LINE-B{index + 1:02d}",
        "name": f"Benchmark Line {index + 1}",
        "cleanroomLevel": "Class_10K",
        "layerStructure": 5,
        "dieDiameterMm": 300,
        "minWidth": 200,
        "maxWidth": 800,
        "minThickness": 20,
        "maxThickness": 100,
        "hourlyOutputKg": 60,
        "maxSlittingLanes": 4,
        "initialMaterialLanes": ["Standard_Med_LDPE"] * 5,
        "initialWidth": 300,
        "initialThickness": 40,
        "forbiddenCalendar": [],
    })


def _make_order(index: int) -> ProductionOrderModel:
    bucket = "candidate" if index % 5 == 4 else "must_schedule"
    return ProductionOrderModel.from_dict({
        "orderId": f"BENCH-{index + 1:04d}",
        "productType": "BenchmarkFilm",
        "targetWidth": 300,
        "targetThickness": 40,
        "totalQuantityKg": 60,
        "cleanroomReq": "Class_10K",
        "customerClass": "STANDARD",
        "orderClass": "NORMAL",
        "coronaReq": "NO",
        "coreSizeInch": 3,
        "dueDateMins": 5_000,
        "recipeMaterialsSequence": ["Borealis_LE6601-PH"] * 5,
        "planningBucket": bucket,
    })


def build_benchmark_dataset(case: BenchmarkCase) -> tuple[List[ProductionOrderModel], List[BlownFilmMachineModel], SetupMatricesManager]:
    orders = [_make_order(index) for index in range(case.order_count)]
    machines = [_make_machine(index) for index in range(case.machine_count)]
    return orders, machines, _make_setup_mgr()


def _machine_load(tasks) -> dict:
    load = {}
    for task in tasks:
        machine_id = task.machine.machine_id
        item = load.setdefault(machine_id, {
            "task_count": 0,
            "production_mins": 0,
            "setup_mins": 0,
        })
        item["task_count"] += 1
        item["production_mins"] += max(0, task.end_mins - task.start_mins)
        item["setup_mins"] += max(0, task.setup_time)
    return load


def _deferred_reason_counts(deferred_orders) -> dict[str, int]:
    counts: dict[str, int] = {}
    for order in deferred_orders or []:
        reason = order.get("deferred_reason_code") or order.get("reason") or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def run_benchmark_case(case: BenchmarkCase) -> dict:
    orders, machines, setup_mgr = build_benchmark_dataset(case)
    aps = AdvancedMedicalAPS(
        setup_mgr,
        solver_profile_policy={
            "profile": case.profile,
            "time_limit_seconds": case.max_wall_time_seconds,
            "relative_gap_limit": case.max_gap or 0.0,
            "random_seed": 0,
            "num_workers": 8,
            "log_search_progress": False,
        },
        candidate_acceptance_policy={"reject_penalty": 10_000_000},
        arc_pruning_policy={
            "enabled": case.arc_pruning_enabled,
            "max_setup_time_mins": case.arc_pruning_max_setup_mins,
            "top_k_per_order": case.arc_pruning_top_k_per_order,
        },
    )
    result = aps.run(orders, machines)
    phase_metrics = result.solver_metrics.get("phase_1") or {}
    wall_time = sum(
        float(metrics.get("wall_time") or 0.0)
        for key, metrics in result.solver_metrics.items()
        if key.startswith("phase_")
    )
    gap = phase_metrics.get("gap")
    scheduled_ratio = len(result.tasks) / max(1, case.order_count)
    late_order_count = sum(1 for task in result.tasks if task.end_mins > task.order.due_date_mins)
    weighted_tardiness = sum(
        max(0, task.end_mins - task.order.due_date_mins)
        * AdvancedMedicalAPS._tardiness_weight(task.order)
        for task in result.tasks
    )
    total_setup_time_mins = sum(max(0, task.setup_time) for task in result.tasks)
    failed_checks = []
    if result.status not in PASS_STATUSES:
        failed_checks.append("solver_status")
    if wall_time > case.max_wall_time_seconds:
        failed_checks.append("wall_time_seconds")
    if scheduled_ratio < case.min_scheduled_ratio:
        failed_checks.append("scheduled_ratio")
    if case.max_gap is not None and gap is not None and float(gap) > case.max_gap:
        failed_checks.append("gap")
    if case.max_late_order_count is not None and late_order_count > case.max_late_order_count:
        failed_checks.append("late_order_count")
    if case.max_weighted_tardiness is not None and weighted_tardiness > case.max_weighted_tardiness:
        failed_checks.append("weighted_tardiness")
    if (
        case.max_total_setup_time_mins is not None
        and total_setup_time_mins > case.max_total_setup_time_mins
    ):
        failed_checks.append("total_setup_time_mins")
    passed = (
        not failed_checks
    )

    deferred_orders = getattr(result, "deferred_orders", [])
    return {
        "name": case.name,
        "order_count": case.order_count,
        "machine_count": case.machine_count,
        "profile": case.profile,
        "comparison_group": case.comparison_group,
        "comparison_variant": case.comparison_variant,
        "solver_status": result.status,
        "passed": bool(passed),
        "scheduled_order_count": len(result.tasks),
        "deferred_order_count": len(deferred_orders),
        "deferred_reason_counts": _deferred_reason_counts(deferred_orders),
        "blocked_order_count": getattr(result, "blocked_order_count", 0),
        "scheduled_ratio": scheduled_ratio,
        "min_scheduled_ratio": case.min_scheduled_ratio,
        "wall_time_seconds": wall_time,
        "gap": gap,
        "late_order_count": late_order_count,
        "weighted_tardiness": weighted_tardiness,
        "total_setup_time_mins": total_setup_time_mins,
        "quality_thresholds": {
            "max_late_order_count": case.max_late_order_count,
            "max_weighted_tardiness": case.max_weighted_tardiness,
            "max_total_setup_time_mins": case.max_total_setup_time_mins,
            "max_pruning_late_order_delta": case.max_pruning_late_order_delta,
            "max_pruning_weighted_tardiness_delta": case.max_pruning_weighted_tardiness_delta,
            "max_pruning_setup_time_delta_mins": case.max_pruning_setup_time_delta_mins,
        },
        "arc_pruning_policy": {
            "enabled": case.arc_pruning_enabled,
            "max_setup_time_mins": case.arc_pruning_max_setup_mins,
            "top_k_per_order": case.arc_pruning_top_k_per_order,
        },
        "failed_checks": failed_checks,
        "machine_load": _machine_load(result.tasks),
        "phase_metrics": {
            key: value
            for key, value in result.solver_metrics.items()
            if key.startswith("phase_")
        },
        "model_size": result.solver_metrics.get("model_size", {}),
    }


def _numeric_delta(pruned: dict, baseline: dict, key: str) -> float | int | None:
    left = pruned.get(key)
    right = baseline.get(key)
    if left is None or right is None:
        return None
    return left - right


def _model_size_delta(pruned: dict, baseline: dict, key: str) -> int | None:
    left = (pruned.get("model_size") or {}).get(key)
    right = (baseline.get("model_size") or {}).get(key)
    if left is None or right is None:
        return None
    return int(left) - int(right)


def _comparison_thresholds(baseline: dict, pruned: dict) -> dict:
    thresholds = {}
    for key in [
        "max_pruning_late_order_delta",
        "max_pruning_weighted_tardiness_delta",
        "max_pruning_setup_time_delta_mins",
    ]:
        value = pruned.get("quality_thresholds", {}).get(key)
        if value is None:
            value = baseline.get("quality_thresholds", {}).get(key)
        thresholds[key] = value
    return thresholds


def _failed_comparison_checks(comparison: dict, thresholds: dict) -> list[str]:
    checks = []
    mapping = {
        "late_order_count_delta": "max_pruning_late_order_delta",
        "weighted_tardiness_delta": "max_pruning_weighted_tardiness_delta",
        "total_setup_time_mins_delta": "max_pruning_setup_time_delta_mins",
    }
    for delta_key, threshold_key in mapping.items():
        threshold = thresholds.get(threshold_key)
        delta = comparison.get(delta_key)
        if threshold is not None and delta is not None and delta > threshold:
            checks.append(delta_key)
    return checks


def _arc_pruning_comparisons(case_results: list[dict]) -> list[dict]:
    grouped: dict[str, dict[str, dict]] = {}
    for case in case_results:
        group = case.get("comparison_group")
        variant = case.get("comparison_variant")
        if not group or variant not in {"pruning_off", "pruning_on"}:
            continue
        grouped.setdefault(group, {})[variant] = case

    comparisons = []
    for group, variants in grouped.items():
        baseline = variants.get("pruning_off")
        pruned = variants.get("pruning_on")
        if not baseline or not pruned:
            continue
        thresholds = _comparison_thresholds(baseline, pruned)
        comparison = {
            "comparison_group": group,
            "baseline_case": baseline["name"],
            "pruned_case": pruned["name"],
            "wall_time_seconds_delta": _numeric_delta(pruned, baseline, "wall_time_seconds"),
            "late_order_count_delta": _numeric_delta(pruned, baseline, "late_order_count"),
            "weighted_tardiness_delta": _numeric_delta(pruned, baseline, "weighted_tardiness"),
            "total_setup_time_mins_delta": _numeric_delta(pruned, baseline, "total_setup_time_mins"),
            "arc_count_delta": _model_size_delta(pruned, baseline, "arc_count"),
            "pruned_arc_count_delta": _model_size_delta(pruned, baseline, "pruned_arc_count"),
            "quality_thresholds": thresholds,
        }
        failed_checks = _failed_comparison_checks(comparison, thresholds)
        comparison["failed_checks"] = failed_checks
        comparison["passed"] = not failed_checks
        comparisons.append(comparison)
    return comparisons


def _profile_acceptance(case_results: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for case in case_results:
        grouped.setdefault(case.get("profile") or "unknown", []).append(case)

    acceptance = {}
    for profile, cases in sorted(grouped.items()):
        gaps = [float(case["gap"]) for case in cases if case.get("gap") is not None]
        deferred_reason_counts: dict[str, int] = {}
        for case in cases:
            for reason, count in (case.get("deferred_reason_counts") or {}).items():
                deferred_reason_counts[reason] = deferred_reason_counts.get(reason, 0) + int(count or 0)
        acceptance[profile] = {
            "case_count": len(cases),
            "passed_count": sum(1 for case in cases if case.get("passed")),
            "failed_count": sum(1 for case in cases if not case.get("passed")),
            "max_wall_time_seconds": max((float(case.get("wall_time_seconds") or 0.0) for case in cases), default=0.0),
            "max_gap": max(gaps) if gaps else None,
            "min_scheduled_ratio": min((float(case.get("scheduled_ratio") or 0.0) for case in cases), default=0.0),
            "deferred_reason_counts": dict(sorted(deferred_reason_counts.items(), key=lambda item: (-item[1], item[0]))),
            "failed_checks": sorted({
                check
                for case in cases
                for check in (case.get("failed_checks") or [])
            }),
        }
    return acceptance


def run_benchmark_suite(cases: Iterable[BenchmarkCase]) -> dict:
    case_list = list(cases)
    case_results = [run_benchmark_case(case) for case in case_list]
    arc_pruning_comparisons = _arc_pruning_comparisons(case_results)
    failed_comparison_count = sum(1 for item in arc_pruning_comparisons if not item["passed"])
    passed = all(item["passed"] for item in case_results) and failed_comparison_count == 0
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if passed else "FAIL",
        "case_count": len(case_results),
        "passed_count": sum(1 for item in case_results if item["passed"]),
        "failed_count": sum(1 for item in case_results if not item["passed"]) + failed_comparison_count,
        "case_configs": [_case_config(case) for case in case_list],
        "cases": case_results,
        "profile_acceptance": _profile_acceptance(case_results),
        "arc_pruning_comparisons": arc_pruning_comparisons,
    }


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown_report(summary: dict) -> str:
    lines = [
        "# Solver Benchmark Report",
        "",
        f"- Status: {summary.get('status')}",
        f"- Generated at: {summary.get('generated_at')}",
        f"- Cases: {summary.get('case_count')} total, {summary.get('passed_count')} passed, {summary.get('failed_count')} failed",
        "",
        "## Cases",
        "",
        "| Case | Status | Passed | Scheduled | Deferred | Late | Weighted Tardiness | Setup Mins | Wall Time | Arc Count | Pruned Arcs |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in summary.get("cases", []):
        model_size = case.get("model_size") or {}
        lines.append(
            "| {name} | {status} | {passed} | {scheduled} | {deferred} | {late} | {weighted} | {setup} | {wall} | {arcs} | {pruned} |".format(
                name=case.get("name"),
                status=case.get("solver_status"),
                passed=case.get("passed"),
                scheduled=case.get("scheduled_order_count"),
                deferred=case.get("deferred_order_count"),
                late=case.get("late_order_count"),
                weighted=_fmt(case.get("weighted_tardiness")),
                setup=_fmt(case.get("total_setup_time_mins")),
                wall=_fmt(case.get("wall_time_seconds")),
                arcs=_fmt(model_size.get("arc_count")),
                pruned=_fmt(model_size.get("pruned_arc_count")),
            )
        )

    deferred_reason_rows = []
    for case in summary.get("cases", []):
        for reason, count in (case.get("deferred_reason_counts") or {}).items():
            deferred_reason_rows.append((case.get("name"), reason, count))
    lines.extend([
        "",
        "## Deferred Reasons",
        "",
    ])
    if deferred_reason_rows:
        lines.extend([
            "| Case | Reason | Count |",
            "| --- | --- | ---: |",
        ])
        for case_name, reason, count in deferred_reason_rows:
            lines.append(f"| {case_name} | {reason} | {count} |")
    else:
        lines.append("No deferred orders were produced by these benchmark cases.")

    profile_acceptance = summary.get("profile_acceptance") or {}
    if profile_acceptance:
        lines.extend([
            "",
            "## Profile Acceptance",
            "",
            "| Profile | Cases | Passed | Failed | Max Wall Time | Max Gap | Min Scheduled Ratio | Deferred Reasons | Failed Checks |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ])
        for profile, item in sorted(profile_acceptance.items()):
            deferred_reasons = ", ".join(
                f"{reason}:{count}"
                for reason, count in (item.get("deferred_reason_counts") or {}).items()
            ) or "-"
            lines.append(
                "| {profile} | {cases} | {passed} | {failed} | {wall} | {gap} | {ratio} | {deferred} | {checks} |".format(
                    profile=profile,
                    cases=item.get("case_count"),
                    passed=item.get("passed_count"),
                    failed=item.get("failed_count"),
                    wall=_fmt(item.get("max_wall_time_seconds")),
                    gap=_fmt(item.get("max_gap")),
                    ratio=_fmt(item.get("min_scheduled_ratio")),
                    deferred=deferred_reasons,
                    checks=", ".join(item.get("failed_checks") or []) or "-",
                )
            )

    comparisons = summary.get("arc_pruning_comparisons") or []
    if comparisons:
        lines.extend([
            "",
            "## Arc Pruning Comparisons",
            "",
            "| Group | Passed | Baseline | Pruned | wall_time_seconds_delta | late_order_count_delta | weighted_tardiness_delta | total_setup_time_mins_delta | arc_count_delta | pruned_arc_count_delta | Failed Checks |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for item in comparisons:
            lines.append(
                "| {group} | {passed} | {baseline} | {pruned} | {wall} | {late} | {weighted} | {setup} | {arcs} | {pruned_arcs} | {failed} |".format(
                    group=item.get("comparison_group"),
                    passed=item.get("passed"),
                    baseline=item.get("baseline_case"),
                    pruned=item.get("pruned_case"),
                    wall=_fmt(item.get("wall_time_seconds_delta")),
                    late=_fmt(item.get("late_order_count_delta")),
                    weighted=_fmt(item.get("weighted_tardiness_delta")),
                    setup=_fmt(item.get("total_setup_time_mins_delta")),
                    arcs=_fmt(item.get("arc_count_delta")),
                    pruned_arcs=_fmt(item.get("pruned_arc_count_delta")),
                    failed=", ".join(item.get("failed_checks") or []) or "-",
                )
            )
    lines.append("")
    return "\n".join(lines)


def _parse_order_counts(value: str) -> List[int]:
    counts = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not counts:
        raise argparse.ArgumentTypeError("at least one order count is required")
    return counts


def _parse_profiles(value: str) -> List[str]:
    profiles = [item.strip() for item in value.split(",") if item.strip()]
    if not profiles:
        raise argparse.ArgumentTypeError("at least one profile is required")
    invalid = [profile for profile in profiles if profile not in {"fast", "standard", "deep"}]
    if invalid:
        raise argparse.ArgumentTypeError(f"invalid profiles: {', '.join(invalid)}")
    return profiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic solver benchmark cases.")
    parser.add_argument("--order-counts", type=_parse_order_counts, default=[50, 100, 200])
    parser.add_argument("--machine-count", type=int, default=2)
    parser.add_argument("--profile", default="fast", choices=["fast", "standard", "deep"])
    parser.add_argument("--profiles", type=_parse_profiles, default=None)
    parser.add_argument("--max-wall-time-seconds", type=float, default=120.0)
    parser.add_argument("--max-gap", type=float, default=None)
    parser.add_argument("--min-scheduled-ratio", type=float, default=0.0)
    parser.add_argument("--max-late-order-count", type=int, default=None)
    parser.add_argument("--max-weighted-tardiness", type=int, default=None)
    parser.add_argument("--max-total-setup-time-mins", type=int, default=None)
    parser.add_argument("--max-pruning-late-order-delta", type=int, default=None)
    parser.add_argument("--max-pruning-weighted-tardiness-delta", type=int, default=None)
    parser.add_argument("--max-pruning-setup-time-delta-mins", type=int, default=None)
    parser.add_argument("--arc-pruning-enabled", action="store_true")
    parser.add_argument("--arc-pruning-max-setup-mins", type=int, default=0)
    parser.add_argument("--arc-pruning-top-k-per-order", type=int, default=0)
    parser.add_argument("--compare-arc-pruning", action="store_true")
    parser.add_argument("--output", default="benchmark-summary.json")
    parser.add_argument("--report-md", default=None)
    args = parser.parse_args(argv)

    profiles = args.profiles or [args.profile]
    cases = []
    for profile in profiles:
        for count in args.order_counts:
            common = {
                "order_count": count,
                "machine_count": max(1, args.machine_count),
                "profile": profile,
                "max_wall_time_seconds": args.max_wall_time_seconds,
                "max_gap": args.max_gap,
                "min_scheduled_ratio": max(0.0, float(args.min_scheduled_ratio)),
                "max_late_order_count": (
                    None if args.max_late_order_count is None else max(0, int(args.max_late_order_count))
                ),
                "max_weighted_tardiness": (
                    None if args.max_weighted_tardiness is None else max(0, int(args.max_weighted_tardiness))
                ),
                "max_total_setup_time_mins": (
                    None if args.max_total_setup_time_mins is None else max(0, int(args.max_total_setup_time_mins))
                ),
                "max_pruning_late_order_delta": (
                    None if args.max_pruning_late_order_delta is None else int(args.max_pruning_late_order_delta)
                ),
                "max_pruning_weighted_tardiness_delta": (
                    None
                    if args.max_pruning_weighted_tardiness_delta is None
                    else int(args.max_pruning_weighted_tardiness_delta)
                ),
                "max_pruning_setup_time_delta_mins": (
                    None
                    if args.max_pruning_setup_time_delta_mins is None
                    else int(args.max_pruning_setup_time_delta_mins)
                ),
                "arc_pruning_max_setup_mins": max(0, int(args.arc_pruning_max_setup_mins)),
                "arc_pruning_top_k_per_order": max(0, int(args.arc_pruning_top_k_per_order)),
            }
            if args.compare_arc_pruning:
                group = f"{profile}-{count}"
                cases.extend([
                    BenchmarkCase(
                        name=f"{group}-pruning-off",
                        arc_pruning_enabled=False,
                        comparison_group=group,
                        comparison_variant="pruning_off",
                        **common,
                    ),
                    BenchmarkCase(
                        name=f"{group}-pruning-on",
                        arc_pruning_enabled=True,
                        comparison_group=group,
                        comparison_variant="pruning_on",
                        **common,
                    ),
                ])
            else:
                cases.append(BenchmarkCase(
                    name=f"{profile}-{count}",
                    arc_pruning_enabled=bool(args.arc_pruning_enabled),
                    **common,
                ))
    summary = run_benchmark_suite(cases)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.report_md:
        report_path = Path(args.report_md)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown_report(summary), encoding="utf-8")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
