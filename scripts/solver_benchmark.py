from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.scheduler import AdvancedMedicalAPS
from src.setup_matrices import SetupMatricesManager


PASS_STATUSES = {"OPTIMAL", "FEASIBLE", "PARTIAL", "UNPUBLISHABLE"}
SUMMARY_SCHEMA_VERSION = "solver-benchmark-v1"
PROFILE_ACCEPTANCE_DEFAULTS = {
    "fast": {
        "max_wall_time_seconds": 60.0,
        "max_gap": None,
        "min_scheduled_ratio": 1.0,
        "max_late_order_count": None,
        "max_weighted_tardiness": None,
        "max_total_setup_time_mins": None,
    },
    "standard": {
        "max_wall_time_seconds": 120.0,
        "max_gap": None,
        "min_scheduled_ratio": 1.0,
        "max_late_order_count": None,
        "max_weighted_tardiness": None,
        "max_total_setup_time_mins": None,
    },
    "deep": {
        "max_wall_time_seconds": 300.0,
        "max_gap": None,
        "min_scheduled_ratio": 1.0,
        "max_late_order_count": None,
        "max_weighted_tardiness": None,
        "max_total_setup_time_mins": None,
    },
}


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    order_count: int
    machine_count: int = 2
    profile: str = "fast"
    max_wall_time_seconds: float = 120.0
    solver_time_limit_seconds: float | None = None
    solver_phase1_time_budget_ratio: float | None = None
    solver_phase1_tardiness_weight: int = 10_000
    solver_phase1_late_order_penalty: int = 0
    solver_phase2_tardiness_weight: int = 0
    solver_max_late_order_count: int | None = None
    solver_max_weighted_tardiness: int | None = None
    max_gap: float | None = None
    min_scheduled_ratio: float = 0.0
    candidate_reject_penalty: int = 10_000_000
    candidate_max_deferred_count: int | None = None
    candidate_min_acceptance_ratio: float = 0.0
    candidate_post_solve_late_defer_count: int = 0
    max_late_order_count: int | None = None
    max_weighted_tardiness: int | None = None
    max_total_setup_time_mins: int | None = None
    max_pruning_late_order_delta: int | None = None
    max_pruning_weighted_tardiness_delta: int | None = None
    max_pruning_setup_time_delta_mins: int | None = None
    arc_pruning_enabled: bool = False
    arc_pruning_max_setup_mins: int = 0
    arc_pruning_top_k_per_order: int = 0
    arc_pruning_same_material_family_top_k: int = 0
    arc_pruning_same_cleanroom_top_k: int = 0
    arc_pruning_due_window_mins: int = 0
    arc_pruning_due_window_top_k: int = 0
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
        "solver_time_limit_seconds": _solver_time_limit_seconds(case),
        "solver_phase1_time_budget_ratio": _solver_phase1_time_budget_ratio(case),
        "solver_phase1_tardiness_weight": _solver_phase1_tardiness_weight(case),
        "solver_phase1_late_order_penalty": _solver_phase1_late_order_penalty(case),
        "solver_phase2_tardiness_weight": _solver_phase2_tardiness_weight(case),
        "solver_max_late_order_count": _solver_max_late_order_count(case),
        "solver_max_weighted_tardiness": _solver_max_weighted_tardiness(case),
        "max_gap": case.max_gap,
        "min_scheduled_ratio": case.min_scheduled_ratio,
        "candidate_reject_penalty": _candidate_reject_penalty(case),
        "candidate_max_deferred_count": _candidate_max_deferred_count(case),
        "candidate_min_acceptance_ratio": _candidate_min_acceptance_ratio(case),
        "candidate_post_solve_late_defer_count": _candidate_post_solve_late_defer_count(case),
        "max_late_order_count": case.max_late_order_count,
        "max_weighted_tardiness": case.max_weighted_tardiness,
        "max_total_setup_time_mins": case.max_total_setup_time_mins,
        "max_pruning_late_order_delta": case.max_pruning_late_order_delta,
        "max_pruning_weighted_tardiness_delta": case.max_pruning_weighted_tardiness_delta,
        "max_pruning_setup_time_delta_mins": case.max_pruning_setup_time_delta_mins,
        "profile_acceptance_policy": _profile_acceptance_policy(case),
        "arc_pruning_enabled": case.arc_pruning_enabled,
        "arc_pruning_max_setup_mins": case.arc_pruning_max_setup_mins,
        "arc_pruning_top_k_per_order": case.arc_pruning_top_k_per_order,
        "arc_pruning_same_material_family_top_k": case.arc_pruning_same_material_family_top_k,
        "arc_pruning_same_cleanroom_top_k": case.arc_pruning_same_cleanroom_top_k,
        "arc_pruning_due_window_mins": case.arc_pruning_due_window_mins,
        "arc_pruning_due_window_top_k": case.arc_pruning_due_window_top_k,
    }
    if case.comparison_group:
        config["comparison_group"] = case.comparison_group
    if case.comparison_variant:
        config["comparison_variant"] = case.comparison_variant
    return config


def _profile_defaults(profile: str) -> dict:
    return dict(PROFILE_ACCEPTANCE_DEFAULTS.get(profile) or PROFILE_ACCEPTANCE_DEFAULTS["standard"])


def _profile_acceptance_policy(case: BenchmarkCase) -> dict:
    defaults = _profile_defaults(case.profile)
    return {
        "profile": case.profile,
        "max_wall_time_seconds": case.max_wall_time_seconds,
        "max_gap": case.max_gap if case.max_gap is not None else defaults["max_gap"],
        "min_scheduled_ratio": case.min_scheduled_ratio,
        "max_late_order_count": case.max_late_order_count,
        "max_weighted_tardiness": case.max_weighted_tardiness,
        "max_total_setup_time_mins": case.max_total_setup_time_mins,
    }


def _candidate_reject_penalty(case: BenchmarkCase) -> int:
    return max(0, int(case.candidate_reject_penalty))


def _candidate_max_deferred_count(case: BenchmarkCase) -> int | None:
    if case.candidate_max_deferred_count is None:
        return None
    return max(0, int(case.candidate_max_deferred_count))


def _candidate_min_acceptance_ratio(case: BenchmarkCase) -> float:
    return min(1.0, max(0.0, float(case.candidate_min_acceptance_ratio)))


def _candidate_post_solve_late_defer_count(case: BenchmarkCase) -> int:
    return max(0, int(case.candidate_post_solve_late_defer_count))


def _candidate_acceptance_policy(case: BenchmarkCase) -> dict:
    return {
        "reject_penalty": _candidate_reject_penalty(case),
        "max_deferred_count": _candidate_max_deferred_count(case),
        "min_acceptance_ratio": _candidate_min_acceptance_ratio(case),
        "post_solve_late_defer_count": _candidate_post_solve_late_defer_count(case),
    }


def _solver_time_limit_seconds(case: BenchmarkCase) -> float:
    if case.solver_time_limit_seconds is not None:
        return max(0.1, float(case.solver_time_limit_seconds))
    return max(0.1, float(case.max_wall_time_seconds) * 0.95)


def _solver_phase1_time_budget_ratio(case: BenchmarkCase) -> float:
    if case.solver_phase1_time_budget_ratio is not None:
        return min(0.95, max(0.05, float(case.solver_phase1_time_budget_ratio)))
    return 0.5


def _solver_phase1_tardiness_weight(case: BenchmarkCase) -> int:
    return max(1, int(case.solver_phase1_tardiness_weight))


def _solver_phase1_late_order_penalty(case: BenchmarkCase) -> int:
    return max(0, int(case.solver_phase1_late_order_penalty))


def _solver_phase2_tardiness_weight(case: BenchmarkCase) -> int:
    return max(0, int(case.solver_phase2_tardiness_weight))


def _solver_max_late_order_count(case: BenchmarkCase) -> int | None:
    if case.solver_max_late_order_count is None:
        return None
    return max(0, int(case.solver_max_late_order_count))


def _solver_max_weighted_tardiness(case: BenchmarkCase) -> int | None:
    if case.solver_max_weighted_tardiness is None:
        return None
    return max(0, int(case.solver_max_weighted_tardiness))


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


def build_sprint5_baseline_cases(
    *,
    order_counts: Iterable[int] = (50, 100, 200, 300),
    profiles: Iterable[str] = ("fast", "standard"),
    machine_count: int = 4,
    max_wall_time_seconds: float | None = None,
    solver_time_limit_seconds: float | None = None,
    solver_phase1_time_budget_ratio: float | None = None,
    max_gap: float | None = None,
    min_scheduled_ratio: float | None = None,
) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    for profile in profiles:
        defaults = _profile_defaults(str(profile))
        for count in order_counts:
            cases.append(BenchmarkCase(
                name=f"sprint5-{profile}-{int(count)}-baseline",
                order_count=int(count),
                machine_count=max(1, int(machine_count)),
                profile=str(profile),
                max_wall_time_seconds=(
                    defaults["max_wall_time_seconds"]
                    if max_wall_time_seconds is None
                    else max_wall_time_seconds
                ),
                solver_time_limit_seconds=solver_time_limit_seconds,
                solver_phase1_time_budget_ratio=solver_phase1_time_budget_ratio,
                max_gap=defaults["max_gap"] if max_gap is None else max_gap,
                min_scheduled_ratio=(
                    defaults["min_scheduled_ratio"]
                    if min_scheduled_ratio is None
                    else min_scheduled_ratio
                ),
                arc_pruning_enabled=False,
            ))
    return cases


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


def _cleaning_diagnostics(diagnostics) -> dict[str, int]:
    counts = {
        "required_count": 0,
        "disabled_count": 0,
    }
    for diagnostic in diagnostics or []:
        code = getattr(diagnostic, "code", "")
        if code == "maintenance.continuous_run_cleaning_required":
            counts["required_count"] += 1
        elif code == "maintenance.continuous_run_experimental_disabled":
            counts["disabled_count"] += 1
    return counts


def _deferred_reason_counts(deferred_orders) -> dict[str, int]:
    counts: dict[str, int] = {}
    for order in deferred_orders or []:
        reason = order.get("deferred_reason_code") or order.get("reason") or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def run_benchmark_case(case: BenchmarkCase) -> dict:
    orders, machines, setup_mgr = build_benchmark_dataset(case)
    profile_acceptance_policy = _profile_acceptance_policy(case)
    candidate_acceptance_policy = _candidate_acceptance_policy(case)
    solver_profile_policy = {
        "profile": case.profile,
        "time_limit_seconds": _solver_time_limit_seconds(case),
        "phase1_time_budget_ratio": _solver_phase1_time_budget_ratio(case),
        "relative_gap_limit": profile_acceptance_policy["max_gap"] or 0.0,
        "random_seed": 0,
        "num_workers": 8,
        "log_search_progress": False,
    }
    solver_quality_policy = {
        "phase2_feasible_tardiness_tolerance_mins": 0,
        "phase1_tardiness_weight": _solver_phase1_tardiness_weight(case),
        "phase1_late_order_penalty": _solver_phase1_late_order_penalty(case),
        "phase2_tardiness_weight": _solver_phase2_tardiness_weight(case),
        "max_late_order_count": _solver_max_late_order_count(case),
        "max_weighted_tardiness": _solver_max_weighted_tardiness(case),
    }
    aps = AdvancedMedicalAPS(
        setup_mgr,
        solver_profile_policy=solver_profile_policy,
        solver_quality_policy=solver_quality_policy,
        candidate_acceptance_policy=candidate_acceptance_policy,
        arc_pruning_policy={
            "enabled": case.arc_pruning_enabled,
            "max_setup_time_mins": case.arc_pruning_max_setup_mins,
            "top_k_per_order": case.arc_pruning_top_k_per_order,
            "same_material_family_top_k": case.arc_pruning_same_material_family_top_k,
            "same_cleanroom_top_k": case.arc_pruning_same_cleanroom_top_k,
            "due_window_mins": case.arc_pruning_due_window_mins,
            "due_window_top_k": case.arc_pruning_due_window_top_k,
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
        * aps._tardiness_weight(task.order)
        for task in result.tasks
    )
    total_setup_time_mins = sum(max(0, task.setup_time) for task in result.tasks)
    machine_load = _machine_load(result.tasks)
    cleaning_diagnostics = _cleaning_diagnostics(result.diagnostics)
    baseline_metrics = {
        "solver_status": result.status,
        "wall_time_seconds": wall_time,
        "gap": gap,
        "late_order_count": late_order_count,
        "weighted_tardiness": weighted_tardiness,
        "total_setup_time_mins": total_setup_time_mins,
        "cleaning_diagnostics": cleaning_diagnostics,
        "machine_load": machine_load,
    }
    failed_checks = []
    if result.status not in PASS_STATUSES:
        failed_checks.append("solver_status")
    if wall_time > case.max_wall_time_seconds:
        failed_checks.append("wall_time_seconds")
    if scheduled_ratio < case.min_scheduled_ratio:
        failed_checks.append("scheduled_ratio")
    if (
        profile_acceptance_policy["max_gap"] is not None
        and gap is not None
        and float(gap) > profile_acceptance_policy["max_gap"]
    ):
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
        "cleaning_diagnostics": cleaning_diagnostics,
        "quality_thresholds": {
            "max_late_order_count": case.max_late_order_count,
            "max_weighted_tardiness": case.max_weighted_tardiness,
            "max_total_setup_time_mins": case.max_total_setup_time_mins,
            "max_pruning_late_order_delta": case.max_pruning_late_order_delta,
            "max_pruning_weighted_tardiness_delta": case.max_pruning_weighted_tardiness_delta,
            "max_pruning_setup_time_delta_mins": case.max_pruning_setup_time_delta_mins,
        },
        "profile_acceptance_policy": profile_acceptance_policy,
        "solver_quality_policy": solver_quality_policy,
        "candidate_acceptance_policy": candidate_acceptance_policy,
        "solver_profile_policy": solver_profile_policy,
        "arc_pruning_policy": {
            "enabled": case.arc_pruning_enabled,
            "max_setup_time_mins": case.arc_pruning_max_setup_mins,
            "top_k_per_order": case.arc_pruning_top_k_per_order,
            "same_material_family_top_k": case.arc_pruning_same_material_family_top_k,
            "same_cleanroom_top_k": case.arc_pruning_same_cleanroom_top_k,
            "due_window_mins": case.arc_pruning_due_window_mins,
            "due_window_top_k": case.arc_pruning_due_window_top_k,
        },
        "failed_checks": failed_checks,
        "machine_load": machine_load,
        "baseline_metrics": baseline_metrics,
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
    if not comparison.get("baseline_case_passed", False):
        checks.append("baseline_case_failed")
    if not comparison.get("pruned_case_passed", False):
        checks.append("pruned_case_failed")
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
            "baseline_case_passed": bool(baseline.get("passed")),
            "pruned_case_passed": bool(pruned.get("passed")),
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
            "acceptance_policy": cases[0].get("profile_acceptance_policy") or {},
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


def _scale_acceptance(case_results: list[dict], arc_pruning_comparisons: list[dict]) -> dict[str, dict]:
    grouped: dict[int, list[dict]] = {}
    for case in case_results:
        grouped.setdefault(int(case.get("order_count") or 0), []).append(case)

    comparison_counts: dict[int, int] = {}
    for item in arc_pruning_comparisons:
        group = str(item.get("comparison_group") or "")
        parts = group.split("-")
        try:
            order_count = int(parts[-1])
        except (TypeError, ValueError):
            continue
        comparison_counts[order_count] = comparison_counts.get(order_count, 0) + 1

    acceptance = {}
    for order_count, cases in sorted(grouped.items()):
        acceptance[str(order_count)] = {
            "order_count": order_count,
            "case_count": len(cases),
            "passed_count": sum(1 for case in cases if case.get("passed")),
            "failed_count": sum(1 for case in cases if not case.get("passed")),
            "comparison_count": comparison_counts.get(order_count, 0),
            "max_wall_time_seconds": max((float(case.get("wall_time_seconds") or 0.0) for case in cases), default=0.0),
            "min_scheduled_ratio": min((float(case.get("scheduled_ratio") or 0.0) for case in cases), default=0.0),
            "max_arc_count": max((int((case.get("model_size") or {}).get("arc_count") or 0) for case in cases), default=0),
            "max_pruned_arc_count": max(
                (int((case.get("model_size") or {}).get("pruned_arc_count") or 0) for case in cases),
                default=0,
            ),
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
        "scale_acceptance": _scale_acceptance(case_results, arc_pruning_comparisons),
    }


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _fmt_arc_pruning_policy(policy: dict | None) -> str:
    if not policy:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in sorted(policy.items()))


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
        "| Case | Status | Passed | Scheduled | Deferred | Late | Weighted Tardiness | Setup Mins | Wall Time | Solver Budget | Arc Count | Pruned Arcs | Arc Pruning Strategy |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in summary.get("cases", []):
        model_size = case.get("model_size") or {}
        lines.append(
            "| {name} | {status} | {passed} | {scheduled} | {deferred} | {late} | {weighted} | {setup} | {wall} | {budget} | {arcs} | {pruned} | {strategy} |".format(
                name=case.get("name"),
                status=case.get("solver_status"),
                passed=case.get("passed"),
                scheduled=case.get("scheduled_order_count"),
                deferred=case.get("deferred_order_count"),
                late=case.get("late_order_count"),
                weighted=_fmt(case.get("weighted_tardiness")),
                setup=_fmt(case.get("total_setup_time_mins")),
                wall=_fmt(case.get("wall_time_seconds")),
                budget=_fmt((case.get("solver_profile_policy") or {}).get("time_limit_seconds")),
                arcs=_fmt(model_size.get("arc_count")),
                pruned=_fmt(model_size.get("pruned_arc_count")),
                strategy=_fmt_arc_pruning_policy(case.get("arc_pruning_policy")),
            )
        )

    lines.extend([
        "",
        "## Baseline Metrics",
        "",
        "| Case | Solver Status | Wall Time | Gap | Late | Weighted Tardiness | Setup Mins | Cleaning Required | Cleaning Disabled | Machines |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for case in summary.get("cases", []):
        metrics = case.get("baseline_metrics") or {}
        machine_load = metrics.get("machine_load") or {}
        cleaning = metrics.get("cleaning_diagnostics") or {}
        lines.append(
            "| {name} | {status} | {wall} | {gap} | {late} | {weighted} | {setup} | {cleaning_required} | {cleaning_disabled} | {machines} |".format(
                name=case.get("name"),
                status=metrics.get("solver_status"),
                wall=_fmt(metrics.get("wall_time_seconds")),
                gap=_fmt(metrics.get("gap")),
                late=_fmt(metrics.get("late_order_count")),
                weighted=_fmt(metrics.get("weighted_tardiness")),
                setup=_fmt(metrics.get("total_setup_time_mins")),
                cleaning_required=_fmt(cleaning.get("required_count")),
                cleaning_disabled=_fmt(cleaning.get("disabled_count")),
                machines=len(machine_load),
            )
        )

    machine_model_rows = []
    for case in summary.get("cases", []):
        for machine_id, metrics in ((case.get("model_size") or {}).get("machine_model_sizes") or {}).items():
            machine_model_rows.append((case.get("name"), machine_id, metrics))
    lines.extend([
        "",
        "## Machine Model Sizes",
        "",
    ])
    if machine_model_rows:
        lines.extend([
            "| Case | Machine | Eligible Orders | Assignments | Optional Candidates | Arcs | Pruned Arcs | Setup Cache |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for case_name, machine_id, metrics in machine_model_rows:
            lines.append(
                "| {case} | {machine} | {eligible} | {assignments} | {optional} | {arcs} | {pruned} | {cache} |".format(
                    case=case_name,
                    machine=machine_id,
                    eligible=_fmt(metrics.get("eligible_order_count")),
                    assignments=_fmt(metrics.get("assignment_count")),
                    optional=_fmt(metrics.get("optional_candidate_count")),
                    arcs=_fmt(metrics.get("arc_count")),
                    pruned=_fmt(metrics.get("pruned_arc_count")),
                    cache=_fmt(metrics.get("setup_cache_size")),
                )
            )
    else:
        lines.append("No per-machine model size telemetry was produced by these benchmark cases.")

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
            "| Profile | Cases | Passed | Failed | Max Wall Time | Max Gap | Min Scheduled Ratio | Acceptance Policy | Deferred Reasons | Failed Checks |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ])
        for profile, item in sorted(profile_acceptance.items()):
            deferred_reasons = ", ".join(
                f"{reason}:{count}"
                for reason, count in (item.get("deferred_reason_counts") or {}).items()
            ) or "-"
            lines.append(
                "| {profile} | {cases} | {passed} | {failed} | {wall} | {gap} | {ratio} | {policy} | {deferred} | {checks} |".format(
                    profile=profile,
                    cases=item.get("case_count"),
                    passed=item.get("passed_count"),
                    failed=item.get("failed_count"),
                    wall=_fmt(item.get("max_wall_time_seconds")),
                    gap=_fmt(item.get("max_gap")),
                    ratio=_fmt(item.get("min_scheduled_ratio")),
                    policy=_fmt_arc_pruning_policy(item.get("acceptance_policy")),
                    deferred=deferred_reasons,
                    checks=", ".join(item.get("failed_checks") or []) or "-",
                )
            )

    scale_acceptance = summary.get("scale_acceptance") or {}
    if scale_acceptance:
        lines.extend([
            "",
            "## Scale Acceptance",
            "",
            "| Orders | Cases | Comparisons | Passed | Failed | Max Wall Time | Min Scheduled Ratio | Max Arcs | Max Pruned Arcs | Failed Checks |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for order_count, item in sorted(scale_acceptance.items(), key=lambda pair: int(pair[0])):
            lines.append(
                "| {orders} | {cases} | {comparisons} | {passed} | {failed} | {wall} | {ratio} | {arcs} | {pruned} | {checks} |".format(
                    orders=order_count,
                    cases=item.get("case_count"),
                    comparisons=item.get("comparison_count"),
                    passed=item.get("passed_count"),
                    failed=item.get("failed_count"),
                    wall=_fmt(item.get("max_wall_time_seconds")),
                    ratio=_fmt(item.get("min_scheduled_ratio")),
                    arcs=_fmt(item.get("max_arc_count")),
                    pruned=_fmt(item.get("max_pruned_arc_count")),
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


def _common_case_options(args, profile: str, count: int) -> dict:
    defaults = _profile_defaults(profile)
    return {
        "order_count": count,
        "machine_count": max(1, args.machine_count),
        "profile": profile,
        "max_wall_time_seconds": (
            defaults["max_wall_time_seconds"]
            if args.max_wall_time_seconds is None
            else args.max_wall_time_seconds
        ),
        "solver_time_limit_seconds": (
            None
            if args.solver_time_limit_seconds is None
            else max(0.1, float(args.solver_time_limit_seconds))
        ),
        "solver_phase1_time_budget_ratio": (
            None
            if args.solver_phase1_time_budget_ratio is None
            else min(0.95, max(0.05, float(args.solver_phase1_time_budget_ratio)))
        ),
        "solver_phase1_tardiness_weight": max(1, int(args.solver_phase1_tardiness_weight)),
        "solver_phase1_late_order_penalty": max(0, int(args.solver_phase1_late_order_penalty)),
        "solver_phase2_tardiness_weight": max(0, int(args.solver_phase2_tardiness_weight)),
        "solver_max_late_order_count": (
            None if args.solver_max_late_order_count is None else max(0, int(args.solver_max_late_order_count))
        ),
        "solver_max_weighted_tardiness": (
            None if args.solver_max_weighted_tardiness is None else max(0, int(args.solver_max_weighted_tardiness))
        ),
        "max_gap": defaults["max_gap"] if args.max_gap is None else args.max_gap,
        "min_scheduled_ratio": (
            defaults["min_scheduled_ratio"]
            if args.min_scheduled_ratio is None
            else max(0.0, float(args.min_scheduled_ratio))
        ),
        "candidate_reject_penalty": max(0, int(args.candidate_reject_penalty)),
        "candidate_max_deferred_count": (
            None
            if args.candidate_max_deferred_count is None
            else max(0, int(args.candidate_max_deferred_count))
        ),
        "candidate_min_acceptance_ratio": min(
            1.0,
            max(0.0, float(args.candidate_min_acceptance_ratio)),
        ),
        "candidate_post_solve_late_defer_count": max(
            0,
            int(args.candidate_post_solve_late_defer_count),
        ),
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
        "arc_pruning_same_material_family_top_k": max(
            0,
            int(args.arc_pruning_same_material_family_top_k),
        ),
        "arc_pruning_same_cleanroom_top_k": max(0, int(args.arc_pruning_same_cleanroom_top_k)),
        "arc_pruning_due_window_mins": max(0, int(args.arc_pruning_due_window_mins)),
        "arc_pruning_due_window_top_k": max(0, int(args.arc_pruning_due_window_top_k)),
    }


def _append_pruning_comparison_cases(cases: list[BenchmarkCase], *, group: str, common: dict) -> None:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic solver benchmark cases.")
    parser.add_argument("--order-counts", type=_parse_order_counts, default=[50, 100, 200])
    parser.add_argument("--machine-count", type=int, default=2)
    parser.add_argument("--profile", default="fast", choices=["fast", "standard", "deep"])
    parser.add_argument("--profiles", type=_parse_profiles, default=None)
    parser.add_argument("--max-wall-time-seconds", type=float, default=None)
    parser.add_argument("--solver-time-limit-seconds", type=float, default=None)
    parser.add_argument("--solver-phase1-time-budget-ratio", type=float, default=None)
    parser.add_argument("--solver-phase1-tardiness-weight", type=int, default=10_000)
    parser.add_argument("--solver-phase1-late-order-penalty", type=int, default=0)
    parser.add_argument("--solver-phase2-tardiness-weight", type=int, default=0)
    parser.add_argument("--solver-max-late-order-count", type=int, default=None)
    parser.add_argument("--solver-max-weighted-tardiness", type=int, default=None)
    parser.add_argument("--max-gap", type=float, default=None)
    parser.add_argument("--min-scheduled-ratio", type=float, default=None)
    parser.add_argument("--candidate-reject-penalty", type=int, default=10_000_000)
    parser.add_argument("--candidate-max-deferred-count", type=int, default=None)
    parser.add_argument("--candidate-min-acceptance-ratio", type=float, default=0.0)
    parser.add_argument("--candidate-post-solve-late-defer-count", type=int, default=0)
    parser.add_argument("--max-late-order-count", type=int, default=None)
    parser.add_argument("--max-weighted-tardiness", type=int, default=None)
    parser.add_argument("--max-total-setup-time-mins", type=int, default=None)
    parser.add_argument("--max-pruning-late-order-delta", type=int, default=None)
    parser.add_argument("--max-pruning-weighted-tardiness-delta", type=int, default=None)
    parser.add_argument("--max-pruning-setup-time-delta-mins", type=int, default=None)
    parser.add_argument("--arc-pruning-enabled", action="store_true")
    parser.add_argument("--arc-pruning-max-setup-mins", type=int, default=0)
    parser.add_argument("--arc-pruning-top-k-per-order", type=int, default=0)
    parser.add_argument("--arc-pruning-same-material-family-top-k", type=int, default=0)
    parser.add_argument("--arc-pruning-same-cleanroom-top-k", type=int, default=0)
    parser.add_argument("--arc-pruning-due-window-mins", type=int, default=0)
    parser.add_argument("--arc-pruning-due-window-top-k", type=int, default=0)
    parser.add_argument("--compare-arc-pruning", action="store_true")
    parser.add_argument("--sprint5-baseline", action="store_true")
    parser.add_argument("--output", default="benchmark-summary.json")
    parser.add_argument("--report-md", default=None)
    args = parser.parse_args(argv)

    profiles = args.profiles or [args.profile]
    if args.sprint5_baseline and not args.compare_arc_pruning:
        cases = build_sprint5_baseline_cases(
            order_counts=args.order_counts,
            profiles=profiles,
            machine_count=max(1, args.machine_count),
            max_wall_time_seconds=args.max_wall_time_seconds,
            solver_time_limit_seconds=args.solver_time_limit_seconds,
            solver_phase1_time_budget_ratio=args.solver_phase1_time_budget_ratio,
            max_gap=args.max_gap,
            min_scheduled_ratio=(
                None if args.min_scheduled_ratio is None else max(0.0, float(args.min_scheduled_ratio))
            ),
        )
    else:
        cases = []
        for profile in profiles:
            for count in args.order_counts:
                common = _common_case_options(args, profile, count)
                if args.compare_arc_pruning:
                    prefix = "sprint5-" if args.sprint5_baseline else ""
                    _append_pruning_comparison_cases(cases, group=f"{prefix}{profile}-{count}", common=common)
                else:
                    prefix = "sprint5-" if args.sprint5_baseline else ""
                    suffix = "-baseline" if args.sprint5_baseline else ""
                    cases.append(BenchmarkCase(
                        name=f"{prefix}{profile}-{count}{suffix}",
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
