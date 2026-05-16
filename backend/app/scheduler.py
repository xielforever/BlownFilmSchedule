from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import inf

from .models import (
    ConstraintAuditRow,
    IssueSeverity,
    Machine,
    MachineLoad,
    MachineInsight,
    OrderJob,
    ScheduleAssignment,
    ScheduleCandidateAudit,
    ScheduleException,
    ScheduleInsight,
    ScheduleResult,
    ScheduleRunConfig,
    ScheduleSummary,
    ValidationIssue,
)


@dataclass(frozen=True)
class CandidateSlot:
    machine: Machine
    start_time: datetime
    production_start_time: datetime
    end_time: datetime
    previous: ScheduleAssignment | None
    score: float
    reason: str
    production_hours: float
    changeover_hours: float
    changeover_detail: str | None
    fit_level: str


@dataclass(frozen=True)
class Changeover:
    hours: float
    label: str
    detail: str | None


@dataclass(frozen=True)
class MachineFit:
    machine: Machine
    passed: bool
    level: str
    penalty: float
    messages: list[str]


FIT_LABELS = {
    "best": "最佳",
    "recommended": "推荐",
    "marginal": "可做边界",
    "blocked": "禁止",
}

FIT_RANK = {"best": 0, "recommended": 1, "marginal": 2, "blocked": 3}
LONG_IDLE_GAP_HOURS = 4
LARGE_DUE_SLACK_HOURS = 72
SAME_DUE_SPREAD_HOURS = 4
HIGH_LOAD_THRESHOLD = 80.0
LOW_LOAD_THRESHOLD = 25.0
HIGH_CHANGEOVER_RATIO = 0.2


def preview_schedule(
    orders: list[OrderJob],
    machines: list[Machine],
    validation_issues: list[ValidationIssue] | None = None,
) -> tuple[ScheduleSummary, list[ConstraintAuditRow], list[ValidationIssue]]:
    validation_issues = list(validation_issues or [])
    audit: list[ConstraintAuditRow] = []

    for order in orders:
        for machine in machines:
            fit = evaluate_machine_fit(order, machine)
            audit.append(
                ConstraintAuditRow(
                    job_id=order.job_id,
                    machine_id=machine.machine_id,
                    check_name="machine_feasibility",
                    passed=fit.passed,
                    fit_level=fit.level,
                    message="; ".join(fit.messages),
                )
            )

    summary = ScheduleSummary(
        total_jobs=len(orders),
        scheduled_jobs=0,
        unplanned_jobs=0,
        late_jobs=0,
        machine_count=len(machines),
    )
    return summary, audit, validation_issues


def run_schedule(
    orders: list[OrderJob],
    machines: list[Machine],
    validation_issues: list[ValidationIssue] | None = None,
    config: ScheduleRunConfig | None = None,
) -> ScheduleResult:
    config = config or ScheduleRunConfig()
    validation_issues = list(validation_issues or [])
    timeline: dict[str, list[ScheduleAssignment]] = {machine.machine_id: [] for machine in machines}
    audit: list[ConstraintAuditRow] = []
    candidate_audit: list[ScheduleCandidateAudit] = []
    exceptions: list[ScheduleException] = []
    machine_eligible_orders: dict[str, set[str]] = {machine.machine_id: set() for machine in machines}
    scheduled_job_ids: set[str] = set()
    schedule_start = _resolve_schedule_start(orders, config)

    ordered_jobs = sorted(orders, key=_order_sort_key)
    for order in ordered_jobs:
        readiness_error = _job_readiness_error(order, machines)
        if readiness_error:
            exceptions.append(readiness_error)
            continue

        feasible_machines: list[MachineFit] = []
        for machine in machines:
            fit = evaluate_machine_fit(order, machine)
            audit.append(
                ConstraintAuditRow(
                    job_id=order.job_id,
                    machine_id=machine.machine_id,
                    check_name="machine_feasibility",
                    passed=fit.passed,
                    fit_level=fit.level,
                    message="; ".join(fit.messages),
                )
            )
            if fit.passed:
                feasible_machines.append(fit)
                machine_eligible_orders[machine.machine_id].add(order.job_id)

        if not feasible_machines:
            exceptions.append(
                ScheduleException(
                    job_id=order.job_id,
                    severity=IssueSeverity.ERROR,
                    reason="无候选机台",
                    detail="订单规格、配方或特殊规则不满足任何内置机台",
                )
            )
            continue

        best, candidate_slots = _find_best_slot(order, feasible_machines, timeline, config, schedule_start)
        if not best:
            exceptions.append(
                ScheduleException(
                    job_id=order.job_id,
                    severity=IssueSeverity.ERROR,
                    reason="时间窗不足",
                    detail="候选机台没有可插入窗口",
                )
            )
            continue
        candidate_audit.extend(_build_candidate_audit_rows(order, best, candidate_slots))

        assignment = _build_assignment(
            order=order,
            machine_id=best.machine.machine_id,
            start_time=best.start_time,
            production_start_time=best.production_start_time,
            end_time=best.end_time,
            production_hours=best.production_hours,
            changeover_hours=best.changeover_hours,
            changeover_detail=best.changeover_detail,
            fit_level=best.fit_level,
            score=best.score,
            reason=best.reason,
            previous=best.previous,
        )
        timeline[best.machine.machine_id].append(assignment)
        timeline[best.machine.machine_id].sort(key=lambda item: item.start_time)
        scheduled_job_ids.add(order.job_id)

    assignments = [item for machine_id in sorted(timeline) for item in sorted(timeline[machine_id], key=lambda x: x.start_time)]
    _assign_sequences(assignments)

    validation_issues.extend(_validate_no_overlaps(timeline))
    machine_loads = _build_machine_loads(timeline, assignments, schedule_start, config)
    machine_insights = _build_machine_insights(machines, machine_loads, assignments, audit, machine_eligible_orders)
    active_loads = [load for load in machine_loads if load.job_count > 0]
    late_jobs = sum(1 for item in assignments if item.is_late)
    summary = ScheduleSummary(
        total_jobs=len(orders),
        scheduled_jobs=len(assignments),
        unplanned_jobs=len({exception.job_id for exception in exceptions if exception.severity == IssueSeverity.ERROR}),
        late_jobs=late_jobs,
        machine_count=len(machines),
        total_production_hours=round(sum(item.production_hours for item in assignments), 3),
        total_changeover_hours=round(sum(item.changeover_hours for item in assignments), 3),
        total_idle_hours=round(sum(load.idle_hours for load in active_loads), 3),
        marginal_jobs=sum(1 for item in assignments if item.fit_level == "marginal"),
        average_load_pct=round(sum(load.load_pct for load in active_loads) / len(active_loads), 1) if active_loads else 0,
    )
    schedule_insights = _build_schedule_insights(assignments)

    return ScheduleResult(
        summary=summary,
        assignments=assignments,
        exceptions=exceptions,
        audit=audit,
        validation_issues=validation_issues,
        machine_loads=machine_loads,
        schedule_insights=schedule_insights,
        candidate_audit=candidate_audit,
        machine_insights=machine_insights,
    )


def is_machine_feasible(order: OrderJob, machine: Machine) -> tuple[bool, list[str]]:
    fit = evaluate_machine_fit(order, machine)
    return fit.passed, fit.messages


def evaluate_machine_fit(order: OrderJob, machine: Machine) -> MachineFit:
    messages: list[str] = []
    blocked = False
    level = "best"
    penalty = 0.0

    if not machine.capacity_avg_kg_h:
        blocked = True
        messages.append("机台缺少有效产能")
    else:
        messages.append(f"产能 {machine.capacity_avg_kg_h:g}kg/h")

    if "SF101_ONLY" in machine.rule_tags and (order.formula or "").upper() != "SF101":
        blocked = True
        messages.append("机台仅限 SF101")

    if "HD_ONLY" in machine.rule_tags and not _is_hd_order(order):
        blocked = True
        messages.append("HD专用机台仅接受HD订单")

    parsed = order.parsed_spec
    if not parsed or parsed.parse_status != "ok" or parsed.width_mm is None:
        blocked = True
        messages.append("规格未解析，无法判断宽度")
    else:
        width_level, width_penalty, width_messages, width_blocked = _width_fit(parsed.width_mm, machine)
        messages.extend(width_messages)
        if width_blocked:
            blocked = True
        level = _worse_fit_level(level, width_level)
        penalty += width_penalty

        if parsed.insert_width_mm is not None and not _insert_supported(machine, parsed.insert_width_mm):
            blocked = True
            messages.append(f"插边 {parsed.insert_width_mm:g}mm 不满足机台插边能力")
        elif parsed.insert_width_mm is not None:
            messages.append(f"插边 {parsed.insert_width_mm:g}mm 满足机台能力")

    if blocked:
        return MachineFit(machine=machine, passed=False, level="blocked", penalty=inf, messages=[f"{FIT_LABELS['blocked']}"] + messages)
    return MachineFit(machine=machine, passed=True, level=level, penalty=penalty, messages=[f"{FIT_LABELS[level]}"] + messages)


def _find_best_slot(
    order: OrderJob,
    feasible_machines: list[MachineFit],
    timeline: dict[str, list[ScheduleAssignment]],
    config: ScheduleRunConfig,
    schedule_start: datetime,
) -> tuple[CandidateSlot | None, list[CandidateSlot]]:
    best: CandidateSlot | None = None
    candidate_slots: list[CandidateSlot] = []

    for fit in feasible_machines:
        machine = fit.machine
        production_hours = _production_hours(order, machine)
        if production_hours is None:
            continue
        machine_best: CandidateSlot | None = None
        current = sorted(timeline[machine.machine_id], key=lambda item: item.start_time)
        search_start = config.horizon_start or schedule_start
        windows = _available_windows(current, search_start, config.horizon_end)
        for window_start, window_end, previous in windows:
            start = max(window_start, search_start)
            changeover = _changeover(order, previous)
            production_start = start + timedelta(hours=changeover.hours)
            end = production_start + timedelta(hours=production_hours)
            if window_end is not None and end > window_end:
                continue
            slot = _score_slot(order, fit, start, production_start, end, window_end, previous, production_hours, changeover)
            if _is_better_slot(slot, machine_best):
                machine_best = slot
            if _is_better_slot(slot, best):
                best = slot
        if machine_best is not None:
            candidate_slots.append(machine_best)

    return best, sorted(candidate_slots, key=_slot_sort_key)


def _is_better_slot(candidate: CandidateSlot, current: CandidateSlot | None) -> bool:
    if current is None:
        return True
    if candidate.score < current.score - 0.001:
        return True
    if candidate.score > current.score + 0.001:
        return False
    return (
        candidate.end_time,
        candidate.changeover_hours,
        FIT_RANK.get(candidate.fit_level, 9),
        candidate.start_time,
        candidate.machine.machine_id,
    ) < (
        current.end_time,
        current.changeover_hours,
        FIT_RANK.get(current.fit_level, 9),
        current.start_time,
        current.machine.machine_id,
    )


def _slot_sort_key(slot: CandidateSlot) -> tuple:
    return (
        round(slot.score, 3),
        slot.end_time,
        slot.changeover_hours,
        FIT_RANK.get(slot.fit_level, 9),
        slot.start_time,
        slot.machine.machine_id,
    )


def _resolve_schedule_start(orders: list[OrderJob], config: ScheduleRunConfig) -> datetime:
    if config.horizon_start:
        return config.horizon_start

    order_dates = [order.order_date for order in orders if order.order_date]
    if order_dates:
        return min(order_dates).replace(minute=0, second=0, microsecond=0)

    return datetime.now().replace(minute=0, second=0, microsecond=0)


def _available_windows(
    assignments: list[ScheduleAssignment],
    search_start: datetime,
    horizon_end: datetime | None,
) -> list[tuple[datetime, datetime | None, ScheduleAssignment | None]]:
    windows: list[tuple[datetime, datetime | None, ScheduleAssignment | None]] = []
    previous: ScheduleAssignment | None = None
    cursor = search_start

    for item in sorted(assignments, key=lambda assignment: assignment.start_time):
        if item.end_time <= search_start:
            previous = item
            cursor = max(cursor, item.end_time)
            continue
        if cursor < item.start_time:
            windows.append((cursor, item.start_time, previous))
        previous = item
        cursor = max(cursor, item.end_time)

    if horizon_end is None or cursor < horizon_end:
        windows.append((cursor, horizon_end, previous))
    return windows


def _score_slot(
    order: OrderJob,
    fit: MachineFit,
    start_time: datetime,
    production_start_time: datetime,
    end_time: datetime,
    window_end: datetime | None,
    previous: ScheduleAssignment | None,
    production_hours: float,
    changeover: "Changeover",
) -> CandidateSlot:
    machine = fit.machine
    late_hours = _late_hours(order, end_time)
    late_penalty = late_hours * 10000
    material_change_penalty = 0 if not previous or previous.formula == order.formula else 100
    width_diff = abs((previous.width_mm or 0) - (order.parsed_spec.width_mm or 0)) if previous and order.parsed_spec else 0
    thickness_diff = (
        abs((previous.thickness_mm or 0) - (order.parsed_spec.thickness_mm or 0))
        if previous and order.parsed_spec
        else 0
    )
    setup_penalty = width_diff * 0.1 + thickness_diff * 50
    idle_gap_hours = 0
    if window_end is not None:
        idle_gap_hours = max(0, (window_end - end_time).total_seconds() / 3600)
    idle_gap_penalty = idle_gap_hours * 10
    changeover_penalty = changeover.hours * 80
    score = late_penalty + material_change_penalty + setup_penalty + idle_gap_penalty + changeover_penalty + fit.penalty

    reason_parts = ["最早可行", f"{machine.machine_id} {FIT_LABELS[fit.level]}"]
    if changeover.hours > 0:
        reason_parts.append(f"{changeover.label} {changeover.hours:.1f}h")
    elif previous:
        reason_parts.append("同配方衔接")
        reason_parts.append("规格延续")
    else:
        reason_parts.append("机台首单")
    if late_hours > 0:
        reason_parts.append(f"延期 {late_hours:.1f}h")
    return CandidateSlot(
        machine=machine,
        start_time=start_time,
        production_start_time=production_start_time,
        end_time=end_time,
        previous=previous,
        score=score,
        reason="；".join(reason_parts),
        production_hours=production_hours,
        changeover_hours=changeover.hours,
        changeover_detail=changeover.detail,
        fit_level=fit.level,
    )


def _build_assignment(
    order: OrderJob,
    machine_id: str,
    start_time: datetime,
    production_start_time: datetime,
    end_time: datetime,
    production_hours: float,
    changeover_hours: float,
    changeover_detail: str | None,
    fit_level: str | None,
    score: float | None,
    reason: str,
    previous: ScheduleAssignment | None,
) -> ScheduleAssignment:
    duration_hours = (end_time - start_time).total_seconds() / 3600
    late_hours = _late_hours(order, end_time)
    parsed = order.parsed_spec
    return ScheduleAssignment(
        job_id=order.job_id,
        machine_id=machine_id,
        formula=order.formula,
        spec_raw=order.spec_raw,
        start_time=start_time,
        production_start_time=production_start_time,
        end_time=end_time,
        plan_finish_time=order.plan_finish_time,
        duration_hours=round(duration_hours, 3),
        production_hours=round(production_hours, 3),
        changeover_hours=round(changeover_hours, 3),
        changeover_detail=changeover_detail,
        fit_level=fit_level,
        is_late=late_hours > 0,
        late_hours=round(late_hours, 3),
        score=round(score, 3) if score is not None else None,
        audit_status="scheduled",
        reason=reason,
        priority_reason=_priority_reason(order),
        idle_before_hours=round(_idle_before_hours(previous, start_time), 3),
        idle_before_reason=_idle_before_reason(previous, start_time),
        previous_job_id=previous.job_id if previous else None,
        previous_formula=previous.formula if previous else None,
        width_mm=parsed.width_mm if parsed else None,
        thickness_mm=parsed.thickness_mm if parsed else None,
        insert_width_mm=parsed.insert_width_mm if parsed else None,
    )


def _build_candidate_audit_rows(order: OrderJob, best: CandidateSlot, candidate_slots: list[CandidateSlot]) -> list[ScheduleCandidateAudit]:
    rows: list[ScheduleCandidateAudit] = []
    for index, slot in enumerate(sorted(candidate_slots, key=_slot_sort_key)[:5], start=1):
        selected = slot.machine.machine_id == best.machine.machine_id and abs(slot.score - best.score) < 0.001
        rows.append(
            ScheduleCandidateAudit(
                job_id=order.job_id,
                machine_id=slot.machine.machine_id,
                selected=selected,
                rank=index,
                fit_level=slot.fit_level,
                score=round(slot.score, 3),
                score_delta=round(slot.score - best.score, 3),
                start_time=slot.start_time,
                production_start_time=slot.production_start_time,
                end_time=slot.end_time,
                production_hours=round(slot.production_hours, 3),
                changeover_hours=round(slot.changeover_hours, 3),
                late_hours=round(_late_hours(order, slot.end_time), 3),
                previous_job_id=slot.previous.job_id if slot.previous else None,
                reason=slot.reason,
                decision_reason="最终选择：候选机台中综合评分最低。" if selected else _not_selected_reason(order, slot, best),
            )
        )
    return rows


def _not_selected_reason(order: OrderJob, slot: CandidateSlot, best: CandidateSlot) -> str:
    score_delta = slot.score - best.score
    parts = [f"未选：评分高 {score_delta:.1f}" if score_delta > 0.05 else "未选：评分相同但同分排序靠后"]
    finish_delta = (slot.end_time - best.end_time).total_seconds() / 3600
    if finish_delta > 0.05:
        parts.append(f"预计完成晚 {finish_delta:.1f}h")
    start_delta = (slot.start_time - best.start_time).total_seconds() / 3600
    if start_delta > 0.05:
        parts.append(f"可开工晚 {start_delta:.1f}h")
    changeover_delta = slot.changeover_hours - best.changeover_hours
    if changeover_delta > 0.05:
        parts.append(f"换型多 {changeover_delta:.1f}h")
    late_delta = _late_hours(order, slot.end_time) - _late_hours(order, best.end_time)
    if late_delta > 0.05:
        parts.append(f"延期多 {late_delta:.1f}h")
    if FIT_RANK.get(slot.fit_level, 9) > FIT_RANK.get(best.fit_level, 9):
        parts.append(f"适配等级低于 {best.machine.machine_id}")
    return "；".join(parts)


def _priority_reason(order: OrderJob) -> str:
    parts: list[str] = []
    if order.plan_finish_time:
        parts.append(f"交期 {order.plan_finish_time.strftime('%Y-%m-%d %H:%M')}")
    if order.urgency:
        parts.append(f"急度 {order.urgency}")
    if order.batch_kg:
        parts.append(f"批量 {order.batch_kg:g}kg")
    elif order.work_hours:
        parts.append(f"工时 {order.work_hours:g}h")
    return "，".join(parts) or "未提供交期/急度/批量"


def _idle_before_hours(previous: ScheduleAssignment | None, start_time: datetime) -> float:
    if not previous or start_time <= previous.end_time:
        return 0
    return (start_time - previous.end_time).total_seconds() / 3600


def _idle_before_reason(previous: ScheduleAssignment | None, start_time: datetime) -> str | None:
    gap_hours = _idle_before_hours(previous, start_time)
    if gap_hours <= 0:
        return None
    return (
        f"距前单 {previous.job_id} 空档 {gap_hours:.1f}h；"
        "该任务按交期/急度/批量排序后进入本机可行窗口，空档不计入换料或调机。"
    )


def _build_machine_loads(
    timeline: dict[str, list[ScheduleAssignment]],
    assignments: list[ScheduleAssignment],
    schedule_start: datetime,
    config: ScheduleRunConfig,
) -> list[MachineLoad]:
    if assignments:
        horizon_start = config.horizon_start or min(item.start_time for item in assignments)
        horizon_end = config.horizon_end or max(item.end_time for item in assignments)
    else:
        horizon_start = config.horizon_start or schedule_start
        horizon_end = config.horizon_end or horizon_start
    span_hours = max(0, (horizon_end - horizon_start).total_seconds() / 3600)

    loads: list[MachineLoad] = []
    for machine_id in sorted(timeline):
        items = sorted(timeline[machine_id], key=lambda item: item.start_time)
        production_hours = sum(item.production_hours for item in items)
        changeover_hours = sum(item.changeover_hours for item in items)
        occupied_hours = sum(item.duration_hours for item in items)
        idle_hours = max(0, span_hours - occupied_hours)
        fit_counts = {
            "best": sum(1 for item in items if item.fit_level == "best"),
            "recommended": sum(1 for item in items if item.fit_level == "recommended"),
            "marginal": sum(1 for item in items if item.fit_level == "marginal"),
        }
        loads.append(
            MachineLoad(
                machine_id=machine_id,
                job_count=len(items),
                first_start=items[0].start_time if items else None,
                last_end=items[-1].end_time if items else None,
                production_hours=round(production_hours, 3),
                changeover_hours=round(changeover_hours, 3),
                occupied_hours=round(occupied_hours, 3),
                idle_hours=round(idle_hours, 3),
                load_pct=round((occupied_hours / span_hours) * 100, 1) if span_hours else 0,
                best_jobs=fit_counts["best"],
                recommended_jobs=fit_counts["recommended"],
                marginal_jobs=fit_counts["marginal"],
                late_jobs=sum(1 for item in items if item.is_late),
            )
        )
    return loads


def _build_machine_insights(
    machines: list[Machine],
    machine_loads: list[MachineLoad],
    assignments: list[ScheduleAssignment],
    audit: list[ConstraintAuditRow],
    machine_eligible_orders: dict[str, set[str]],
) -> list[MachineInsight]:
    load_map = {item.machine_id: item for item in machine_loads}
    selected_counts = {machine.machine_id: 0 for machine in machines}
    for assignment in assignments:
        selected_counts[assignment.machine_id] = selected_counts.get(assignment.machine_id, 0) + 1

    audit_by_machine: dict[str, list[ConstraintAuditRow]] = {machine.machine_id: [] for machine in machines}
    for row in audit:
        if row.machine_id:
            audit_by_machine.setdefault(row.machine_id, []).append(row)

    insights: list[MachineInsight] = []

    active_loads = [load for load in machine_loads if load.job_count > 0]
    for load in sorted(active_loads, key=lambda item: item.load_pct, reverse=True)[:3]:
        ratio = (load.changeover_hours / load.occupied_hours) if load.occupied_hours else 0
        severity = IssueSeverity.WARNING if load.load_pct >= HIGH_LOAD_THRESHOLD else IssueSeverity.INFO
        message = f"本批承担 {load.job_count} 单，占用 {load.occupied_hours:.1f}h，负荷 {load.load_pct:.1f}%"
        if ratio >= HIGH_CHANGEOVER_RATIO:
            message += f"，换型占占用 {ratio * 100:.1f}%"
        if load.late_jobs:
            message += f"，其中 {load.late_jobs} 单延期"
        insights.append(
            MachineInsight(
                machine_id=load.machine_id,
                kind="high_load",
                severity=severity,
                title="高负荷机台",
                message=message,
                load_pct=load.load_pct,
                job_count=load.job_count,
                production_hours=load.production_hours,
                changeover_hours=load.changeover_hours,
                changeover_ratio=round(ratio, 3) if load.occupied_hours else None,
                eligible_orders=len(machine_eligible_orders.get(load.machine_id, set())),
                selected_orders=selected_counts.get(load.machine_id, 0),
            )
        )

    low_load_candidates = [load for load in active_loads if load.load_pct <= LOW_LOAD_THRESHOLD]
    for load in sorted(low_load_candidates, key=lambda item: (item.load_pct, item.job_count, item.machine_id))[:3]:
        eligible_orders = sorted(machine_eligible_orders.get(load.machine_id, set()))
        message = f"本批仅分配 {load.job_count} 单，负荷 {load.load_pct:.1f}%"
        if len(eligible_orders) > load.job_count:
            message += f"，可行订单 {len(eligible_orders)} 单，但更多订单被更优机台分流"
        elif len(eligible_orders) <= 1:
            message += "，本批订单池对该机台的适配订单较少"
        insights.append(
            MachineInsight(
                machine_id=load.machine_id,
                kind="low_load",
                severity=IssueSeverity.INFO,
                title="低负荷机台",
                message=message,
                load_pct=load.load_pct,
                job_count=load.job_count,
                production_hours=load.production_hours,
                changeover_hours=load.changeover_hours,
                changeover_ratio=round(load.changeover_hours / load.occupied_hours, 3) if load.occupied_hours else None,
                eligible_orders=len(eligible_orders),
                selected_orders=selected_counts.get(load.machine_id, 0),
                example_orders=eligible_orders[:3],
            )
        )

    changeover_heavy = [
        load
        for load in active_loads
        if load.job_count >= 2 and load.occupied_hours > 0 and (load.changeover_hours / load.occupied_hours) >= HIGH_CHANGEOVER_RATIO
    ]
    for load in sorted(changeover_heavy, key=lambda item: (item.changeover_hours / item.occupied_hours if item.occupied_hours else 0), reverse=True)[:3]:
        ratio = load.changeover_hours / load.occupied_hours if load.occupied_hours else 0
        insights.append(
            MachineInsight(
                machine_id=load.machine_id,
                kind="changeover_heavy",
                severity=IssueSeverity.WARNING if ratio >= 0.3 else IssueSeverity.INFO,
                title="换型占比高",
                message=f"换型占占用 {ratio * 100:.1f}%（换型 {load.changeover_hours:.1f}h / 占用 {load.occupied_hours:.1f}h），频繁切换会压缩有效产能。",
                load_pct=load.load_pct,
                job_count=load.job_count,
                production_hours=load.production_hours,
                changeover_hours=load.changeover_hours,
                changeover_ratio=round(ratio, 3),
                eligible_orders=len(machine_eligible_orders.get(load.machine_id, set())),
                selected_orders=selected_counts.get(load.machine_id, 0),
            )
        )

    unused_loads = [load for load in machine_loads if load.job_count == 0]
    unused_loads.sort(
        key=lambda item: (
            -len(machine_eligible_orders.get(item.machine_id, set())),
            load_map[item.machine_id].machine_id,
        )
    )
    for load in unused_loads[:6]:
        eligible_orders = sorted(machine_eligible_orders.get(load.machine_id, set()))
        audit_rows = audit_by_machine.get(load.machine_id, [])
        if load_map[load.machine_id] and next((machine for machine in machines if machine.machine_id == load.machine_id), None) and next(
            (machine for machine in machines if machine.machine_id == load.machine_id),
            None,
        ).capacity_avg_kg_h is None:
            title = "未用机台：能力缺失"
            message = "本批没有启用，因为本地机台表缺少有效产能，未进入可比选候选。"
        elif not eligible_orders:
            title = "未用机台：无可行订单"
            message = f"本批 订单中没有任何一单通过该机台的规格/配方/规则校验，主要阻塞原因：{_machine_block_reason(audit_rows)}。"
        else:
            title = "未用机台：候选未胜出"
            example_orders = "/".join(eligible_orders[:4])
            if len(eligible_orders) > 4:
                example_orders = f"{example_orders}/..."
            message = f"有 {len(eligible_orders)} 单可行候选（如 {example_orders}），但最终没有订单选中该机台；综合评分未胜出。"
        insights.append(
            MachineInsight(
                machine_id=load.machine_id,
                kind="unused",
                severity=IssueSeverity.WARNING if eligible_orders else IssueSeverity.INFO,
                title=title,
                message=message,
                load_pct=load.load_pct,
                job_count=load.job_count,
                production_hours=load.production_hours,
                changeover_hours=load.changeover_hours,
                changeover_ratio=round(load.changeover_hours / load.occupied_hours, 3) if load.occupied_hours else None,
                eligible_orders=len(eligible_orders),
                selected_orders=selected_counts.get(load.machine_id, 0),
                example_orders=eligible_orders[:4],
            )
        )

    return insights[:18]


def _machine_block_reason(audit_rows: list[ConstraintAuditRow]) -> str:
    if not audit_rows:
        return "规则或规格不匹配"
    messages = [row.message for row in audit_rows if not row.passed]
    if any("机台缺少有效产能" in message for message in messages):
        return "能力表缺少有效产能"
    if any("机台仅限 SF101" in message for message in messages):
        return "仅限 SF101，当前订单池其他配方偏多"
    if any("HD专用机台仅接受HD订单" in message for message in messages):
        return "HD 专用机台，当前订单池不是 HD 订单"
    if any("规格未解析" in message or "规格无法解析" in message for message in messages):
        return "规格解析失败"
    if any("插边" in message for message in messages):
        return "插边能力不匹配"
    if any("宽度" in message for message in messages):
        return "宽度能力不匹配"
    return "规则或规格不匹配"


def _build_schedule_insights(assignments: list[ScheduleAssignment]) -> list[ScheduleInsight]:
    insights: list[ScheduleInsight] = []
    insights.extend(_long_idle_gap_insights(assignments))
    insights.extend(_same_due_spread_insights(assignments))
    insights.extend(_due_slack_insights(assignments))
    insights.extend(_marginal_fit_insights(assignments))
    return insights[:24]


def _long_idle_gap_insights(assignments: list[ScheduleAssignment]) -> list[ScheduleInsight]:
    items = sorted((item for item in assignments if item.idle_before_hours >= LONG_IDLE_GAP_HOURS), key=lambda item: item.idle_before_hours, reverse=True)
    insights: list[ScheduleInsight] = []
    for item in items[:8]:
        previous = f"距前单 {item.previous_job_id} " if item.previous_job_id else ""
        insights.append(
            ScheduleInsight(
                code="long_idle_gap",
                severity=IssueSeverity.WARNING,
                title="前序空档偏长",
                job_id=item.job_id,
                related_job_id=item.previous_job_id,
                machine_id=item.machine_id,
                metric_hours=round(item.idle_before_hours, 3),
                message=(
                    f"{item.machine_id} 上 {previous}空档 {item.idle_before_hours:.1f}h；"
                    "这是交期、急度、批量、机台适配和可行窗口共同评分后的结果，不属于换料或调机时间。"
                ),
            )
        )
    return insights


def _same_due_spread_insights(assignments: list[ScheduleAssignment]) -> list[ScheduleInsight]:
    groups: dict[tuple[datetime, str], list[ScheduleAssignment]] = {}
    for item in assignments:
        if not item.plan_finish_time:
            continue
        groups.setdefault((item.plan_finish_time, item.formula or "-"), []).append(item)

    insights: list[ScheduleInsight] = []
    for (due, formula), items in groups.items():
        if len(items) < 2:
            continue
        ordered = sorted(items, key=lambda item: item.start_time)
        spread_hours = (ordered[-1].start_time - ordered[0].start_time).total_seconds() / 3600
        if spread_hours < SAME_DUE_SPREAD_HOURS:
            continue
        machines = "/".join(sorted({item.machine_id for item in ordered}))
        jobs = "/".join(item.job_id for item in ordered[:8])
        if len(ordered) > 8:
            jobs = f"{jobs}/..."
        insights.append(
            ScheduleInsight(
                code="same_due_spread",
                severity=IssueSeverity.INFO,
                title="同交期订单分散排产",
                job_id=ordered[0].job_id,
                related_job_id=ordered[-1].job_id,
                machine_id=machines,
                metric_hours=round(spread_hours, 3),
                message=(
                    f"{formula} 在 {due.strftime('%Y-%m-%d %H:%M')} 交期下共有 {len(ordered)} 单，"
                    f"首末开工相差 {spread_hours:.1f}h，分布在 {machines}；"
                    f"涉及订单 {jobs}；"
                    "系统按交期、急度、批量、机台适配、换料和调机综合评分，不按输入顺序强制连排。"
                ),
            )
        )
    return sorted(insights, key=lambda item: item.metric_hours or 0, reverse=True)[:8]


def _due_slack_insights(assignments: list[ScheduleAssignment]) -> list[ScheduleInsight]:
    slack_rows: list[tuple[float, ScheduleAssignment]] = []
    for item in assignments:
        if not item.plan_finish_time:
            continue
        slack_hours = (item.plan_finish_time - item.end_time).total_seconds() / 3600
        if slack_hours >= LARGE_DUE_SLACK_HOURS:
            slack_rows.append((slack_hours, item))

    insights: list[ScheduleInsight] = []
    for slack_hours, item in sorted(slack_rows, key=lambda row: row[0], reverse=True)[:8]:
        insights.append(
            ScheduleInsight(
                code="large_due_slack",
                severity=IssueSeverity.INFO,
                title="交期余量较大",
                job_id=item.job_id,
                machine_id=item.machine_id,
                metric_hours=round(slack_hours, 3),
                message=(
                    f"{item.job_id} 计划完成早于交期 {slack_hours / 24:.1f} 天；"
                    "当前订单池交期较松或产能窗口充足时，算法会提前排入可行机台。"
                ),
            )
        )
    return insights


def _marginal_fit_insights(assignments: list[ScheduleAssignment]) -> list[ScheduleInsight]:
    return [
        ScheduleInsight(
            code="marginal_fit",
            severity=IssueSeverity.WARNING,
            title="边界适配",
            job_id=item.job_id,
            machine_id=item.machine_id,
            message=f"{item.job_id} 在 {item.machine_id} 属于边界适配；建议核对规格 {item.spec_raw} 与本地机台能力表。",
        )
        for item in assignments
        if item.fit_level == "marginal"
    ][:8]


def _job_readiness_error(order: OrderJob, machines: list[Machine]) -> ScheduleException | None:
    if not order.parsed_spec or order.parsed_spec.parse_status != "ok":
        return ScheduleException(
            job_id=order.job_id,
            severity=IssueSeverity.ERROR,
            reason="规格无法解析",
            detail=order.parsed_spec.parse_message if order.parsed_spec else "规格为空",
        )
    if not machines:
        return ScheduleException(
            job_id=order.job_id,
            severity=IssueSeverity.ERROR,
            reason="缺少机台",
            detail="未配置可用于排程的机台能力表",
        )
    if order.work_hours is None and not any(_production_hours(order, machine) is not None for machine in machines):
        return ScheduleException(
            job_id=order.job_id,
            severity=IssueSeverity.ERROR,
            reason="缺少工时",
            detail="订单未提供工时，且无法用批量和产能估算",
        )
    return None


def _changeover(order: OrderJob, previous: ScheduleAssignment | None) -> Changeover:
    if not previous or not order.parsed_spec:
        return Changeover(hours=0, label="无需换型", detail=None)

    parts: list[tuple[str, float]] = []
    if previous.formula != order.formula:
        parts.append(("换料", 0.75))

    width_diff = abs((previous.width_mm or 0) - (order.parsed_spec.width_mm or 0))
    if width_diff > 0:
        parts.append(("调宽", min(1.5, 0.25 + width_diff / 600)))

    thickness_diff = abs((previous.thickness_mm or 0) - (order.parsed_spec.thickness_mm or 0))
    if thickness_diff >= 0.005:
        parts.append(("调厚", 0.25))

    previous_insert = previous.insert_width_mm or 0
    current_insert = order.parsed_spec.insert_width_mm or 0
    if abs(previous_insert - current_insert) > 0:
        parts.append(("调插边", 0.25))

    hours = min(sum(hours for _, hours in parts), 3.0)
    if hours <= 0:
        return Changeover(hours=0, label="无需换型", detail=None)

    has_material = any(label == "换料" for label, _ in parts)
    has_setup = any(label != "换料" for label, _ in parts)
    if has_material and has_setup:
        summary_label = "换料/调机"
    elif has_material:
        summary_label = "换料"
    else:
        summary_label = "调机"
    detail = " + ".join(f"{label} {hours:.2f}h" for label, hours in parts)
    if hours == 3.0 and sum(item_hours for _, item_hours in parts) > 3.0:
        detail = f"{detail}，封顶 3.00h"
    return Changeover(hours=hours, label=summary_label, detail=detail)


def _width_fit(width_mm: float, machine: Machine) -> tuple[str, float, list[str], bool]:
    hard_max = machine.max_width_mm
    if hard_max is None:
        if "NON_BLOW_RATIO_RULE" in machine.rule_tags:
            return (
                "marginal",
                220,
                ["非吹胀比机台无完整宽度表，按可做边界处理"],
                False,
            )
        return "blocked", inf, ["机台缺少宽度能力"], True

    if width_mm > hard_max:
        return "blocked", inf, [f"宽度 {width_mm:g}mm 超过机台硬上限 {hard_max:g}mm"], True

    best_max = _best_width_limit(machine)
    recommended_max = _recommended_width_limit(machine)
    if best_max is not None and width_mm <= best_max:
        return "best", 0, [f"宽度 {width_mm:g}mm 在最佳区间 ≤ {best_max:g}mm"], False
    if recommended_max is not None and width_mm <= recommended_max:
        return "recommended", 60, [f"宽度 {width_mm:g}mm 在推荐区间 ≤ {recommended_max:g}mm"], False
    return "marginal", 220, [f"宽度 {width_mm:g}mm 可做但接近上限 {hard_max:g}mm"], False


def _best_width_limit(machine: Machine) -> float | None:
    values = [
        machine.width_recommend_br2,
        machine.width_hd_br3,
        machine.width_recommend_br1_5,
        machine.width_hd_br2,
        machine.width_limit_br1,
        machine.width_hd_limit,
    ]
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _recommended_width_limit(machine: Machine) -> float | None:
    values = [
        machine.width_recommend_br2_5,
        machine.width_hd_br5,
        machine.width_hd_br4,
        _best_width_limit(machine),
    ]
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _worse_fit_level(current: str, candidate: str) -> str:
    return candidate if FIT_RANK[candidate] > FIT_RANK[current] else current


def _production_hours(order: OrderJob, machine: Machine) -> float | None:
    if order.batch_kg and machine.capacity_avg_kg_h:
        return order.batch_kg / machine.capacity_avg_kg_h
    if order.work_hours and order.work_hours > 0:
        return order.work_hours
    return None


def _order_sort_key(order: OrderJob) -> tuple:
    due = order.plan_finish_time or datetime.max
    urgency_score = _urgency_score(order.urgency)
    workload = order.work_hours or order.batch_kg or 0
    return (due, -urgency_score, -workload)


def _urgency_score(urgency: str | None) -> int:
    if not urgency:
        return 0
    mapping = {"急": 3, "高": 2, "中": 1, "低": 0}
    return max((score for token, score in mapping.items() if token in urgency), default=0)


def _late_hours(order: OrderJob, end_time: datetime) -> float:
    if not order.plan_finish_time or end_time <= order.plan_finish_time:
        return 0
    return (end_time - order.plan_finish_time).total_seconds() / 3600


def _is_hd_order(order: OrderJob) -> bool:
    text = " ".join(filter(None, [order.formula, order.material_code, order.spec_raw])).upper()
    return "HD" in text or "SF151" in text or "SF152" in text


def _insert_supported(machine: Machine, insert_width: float) -> bool:
    if not machine.insert_size_mm:
        return insert_width <= (machine.max_width_mm or inf)
    values = [float(x) for x in __import__("re").findall(r"\d+(?:\.\d+)?", machine.insert_size_mm)]
    if not values:
        return True
    if len(values) >= 2:
        return min(values) <= insert_width <= max(values) * (2 if "*2" in machine.insert_size_mm else 1)
    return insert_width <= values[0]


def _assign_sequences(assignments: list[ScheduleAssignment]) -> None:
    counters: dict[str, int] = {}
    for item in sorted(assignments, key=lambda x: (x.machine_id, x.start_time)):
        counters[item.machine_id] = counters.get(item.machine_id, 0) + 1
        item.sequence_no = counters[item.machine_id]


def _validate_no_overlaps(timeline: dict[str, list[ScheduleAssignment]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for machine_id, items in timeline.items():
        ordered = sorted(items, key=lambda item: item.start_time)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.end_time > current.start_time:
                issues.append(
                    ValidationIssue(
                        job_id=current.job_id,
                        machine_id=machine_id,
                        severity=IssueSeverity.ERROR,
                        message=f"机台时间重叠: {previous.job_id} 与 {current.job_id}",
                    )
                )
    return issues
