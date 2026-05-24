from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.scheduler import AdvancedMedicalAPS
from src.setup_matrices import SetupMatricesManager


PASS_STATUSES = {"OPTIMAL", "FEASIBLE", "PARTIAL", "UNPUBLISHABLE"}


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    order_count: int
    machine_count: int = 2
    profile: str = "fast"
    max_wall_time_seconds: float = 120.0
    max_gap: float | None = None
    min_scheduled_ratio: float = 0.0


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
    passed = (
        result.status in PASS_STATUSES
        and wall_time <= case.max_wall_time_seconds
        and scheduled_ratio >= case.min_scheduled_ratio
    )
    if case.max_gap is not None and gap is not None:
        passed = passed and float(gap) <= case.max_gap

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
        "model_size": result.solver_metrics.get("model_size", {}),
    }


def run_benchmark_suite(cases: Iterable[BenchmarkCase]) -> dict:
    case_results = [run_benchmark_case(case) for case in cases]
    passed = all(item["passed"] for item in case_results)
    return {
        "status": "PASS" if passed else "FAIL",
        "case_count": len(case_results),
        "passed_count": sum(1 for item in case_results if item["passed"]),
        "failed_count": sum(1 for item in case_results if not item["passed"]),
        "cases": case_results,
    }


def _parse_order_counts(value: str) -> List[int]:
    counts = [int(item.strip()) for item in value.split(",") if item.strip()]
    if not counts:
        raise argparse.ArgumentTypeError("at least one order count is required")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run deterministic solver benchmark cases.")
    parser.add_argument("--order-counts", type=_parse_order_counts, default=[50, 100, 200])
    parser.add_argument("--machine-count", type=int, default=2)
    parser.add_argument("--profile", default="fast", choices=["fast", "standard", "deep"])
    parser.add_argument("--max-wall-time-seconds", type=float, default=120.0)
    parser.add_argument("--max-gap", type=float, default=None)
    parser.add_argument("--min-scheduled-ratio", type=float, default=0.0)
    parser.add_argument("--output", default="benchmark-summary.json")
    args = parser.parse_args(argv)

    cases = [
        BenchmarkCase(
            name=f"{args.profile}-{count}",
            order_count=count,
            machine_count=max(1, args.machine_count),
            profile=args.profile,
            max_wall_time_seconds=args.max_wall_time_seconds,
            max_gap=args.max_gap,
            min_scheduled_ratio=max(0.0, float(args.min_scheduled_ratio)),
        )
        for count in args.order_counts
    ]
    summary = run_benchmark_suite(cases)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
