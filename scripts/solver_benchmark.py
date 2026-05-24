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
    arc_pruning_enabled: bool = False
    arc_pruning_max_setup_mins: int = 0


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
    return {
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
        "arc_pruning_enabled": case.arc_pruning_enabled,
        "arc_pruning_max_setup_mins": case.arc_pruning_max_setup_mins,
    }


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

    return {
        "name": case.name,
        "order_count": case.order_count,
        "machine_count": case.machine_count,
        "profile": case.profile,
        "solver_status": result.status,
        "passed": bool(passed),
        "scheduled_order_count": len(result.tasks),
        "deferred_order_count": len(getattr(result, "deferred_orders", [])),
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
        },
        "arc_pruning_policy": {
            "enabled": case.arc_pruning_enabled,
            "max_setup_time_mins": case.arc_pruning_max_setup_mins,
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


def run_benchmark_suite(cases: Iterable[BenchmarkCase]) -> dict:
    case_list = list(cases)
    case_results = [run_benchmark_case(case) for case in case_list]
    passed = all(item["passed"] for item in case_results)
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if passed else "FAIL",
        "case_count": len(case_results),
        "passed_count": sum(1 for item in case_results if item["passed"]),
        "failed_count": sum(1 for item in case_results if not item["passed"]),
        "case_configs": [_case_config(case) for case in case_list],
        "cases": case_results,
    }


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
    parser.add_argument("--arc-pruning-enabled", action="store_true")
    parser.add_argument("--arc-pruning-max-setup-mins", type=int, default=0)
    parser.add_argument("--output", default="benchmark-summary.json")
    args = parser.parse_args(argv)

    profiles = args.profiles or [args.profile]
    cases = [
        BenchmarkCase(
            name=f"{profile}-{count}",
            order_count=count,
            machine_count=max(1, args.machine_count),
            profile=profile,
            max_wall_time_seconds=args.max_wall_time_seconds,
            max_gap=args.max_gap,
            min_scheduled_ratio=max(0.0, float(args.min_scheduled_ratio)),
            max_late_order_count=(
                None if args.max_late_order_count is None else max(0, int(args.max_late_order_count))
            ),
            max_weighted_tardiness=(
                None if args.max_weighted_tardiness is None else max(0, int(args.max_weighted_tardiness))
            ),
            max_total_setup_time_mins=(
                None if args.max_total_setup_time_mins is None else max(0, int(args.max_total_setup_time_mins))
            ),
            arc_pruning_enabled=bool(args.arc_pruning_enabled),
            arc_pruning_max_setup_mins=max(0, int(args.arc_pruning_max_setup_mins)),
        )
        for profile in profiles
        for count in args.order_counts
    ]
    summary = run_benchmark_suite(cases)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
