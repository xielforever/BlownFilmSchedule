"""Structured root-cause diagnostics for scheduling results."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List, Optional

from src.models import BlownFilmMachineModel, ProductionOrderModel


SEVERITIES = {"critical", "warning", "info"}
CONFIDENCES = {"proven", "inferred", "unknown"}


@dataclass
class DiagnosticEvidence:
    metric: str
    actual: Any
    unit: Optional[str] = None
    limit: Optional[Any] = None
    entity_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {"metric": self.metric, "actual": self.actual}
        if self.unit:
            data["unit"] = self.unit
        if self.limit is not None:
            data["limit"] = self.limit
        if self.entity_id:
            data["entity_id"] = self.entity_id
        return data


@dataclass
class DiagnosticRecommendation:
    action: str
    label: str
    href: str

    def to_dict(self) -> Dict[str, str]:
        return {"action": self.action, "label": self.label, "href": self.href}


@dataclass
class Diagnostic:
    entity_type: str
    entity_id: str
    severity: str
    category: str
    code: str
    confidence: str
    root_cause: str
    evidence: List[DiagnosticEvidence] = field(default_factory=list)
    recommendations: List[DiagnosticRecommendation] = field(default_factory=list)
    related_event: Optional[Dict[str, Any]] = None
    run_id: Optional[int] = None
    id: Optional[str] = None
    display_title: Optional[str] = None
    level: Optional[str] = None

    def to_dict(self, run_id: Optional[int] = None) -> Dict[str, Any]:
        effective_run_id = self.run_id if run_id is None else run_id
        data = {
            "id": self.id or diagnostic_id(
                effective_run_id,
                self.entity_type,
                self.entity_id,
                self.code,
            ),
            "run_id": effective_run_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "severity": self.severity if self.severity in SEVERITIES else "info",
            "category": self.category,
            "code": self.code,
            "display_title": self.display_title or self.entity_id,
            "confidence": self.confidence if self.confidence in CONFIDENCES else "unknown",
            "root_cause": self.root_cause,
            "evidence": [item.to_dict() for item in self.evidence],
            "recommendations": [item.to_dict() for item in self.recommendations],
            "related_event": self.related_event,
        }
        if self.level:
            data["level"] = self.level
        return data


@dataclass
class MachineFitIssue:
    code: str
    root_cause: str
    evidence: List[DiagnosticEvidence]


@dataclass
class MachineFitResult:
    machine_id: str
    eligible: bool
    issues: List[MachineFitIssue]


def diagnostic_id(
    run_id: Optional[int],
    entity_type: str,
    entity_id: str,
    code: str,
    suffix: Optional[str] = None,
) -> str:
    run_part = f"run-{run_id}" if run_id is not None else "pending"
    parts = ["diag", run_part, entity_type, entity_id, code]
    if suffix:
        parts.append(suffix)
    return "-".join(_slug(part) for part in parts if part)


def evaluate_machine_fit(
    order: ProductionOrderModel,
    machine: BlownFilmMachineModel,
) -> MachineFitResult:
    """Return hard eligibility blockers for an order-machine pair."""

    issues: List[MachineFitIssue] = []

    if order.cleanroom_req == "Class_10K" and machine.cleanroom_level == "Class_100K":
        issues.append(MachineFitIssue(
            code="eligibility.cleanroom_mismatch",
            root_cause=(
                f"{machine.machine_id} 洁净等级为 {machine.cleanroom_level}，"
                f"不满足订单 {order.order_id} 的 {order.cleanroom_req} 要求。"
            ),
            evidence=[
                DiagnosticEvidence("order_cleanroom", order.cleanroom_req, entity_id=order.order_id),
                DiagnosticEvidence("machine_cleanroom", machine.cleanroom_level, entity_id=machine.machine_id),
            ],
        ))

    if order.target_width < machine.min_width or order.target_width > machine.max_width:
        issues.append(MachineFitIssue(
            code="eligibility.width_out_of_range",
            root_cause=(
                f"{machine.machine_id} 幅宽能力 {machine.min_width}-{machine.max_width}mm，"
                f"不覆盖订单 {order.order_id} 的 {order.target_width}mm。"
            ),
            evidence=[
                DiagnosticEvidence("target_width", order.target_width, "mm", entity_id=order.order_id),
                DiagnosticEvidence(
                    "machine_width_range",
                    f"{machine.min_width}-{machine.max_width}",
                    "mm",
                    entity_id=machine.machine_id,
                ),
            ],
        ))

    if (
        order.target_thickness < machine.min_thickness
        or order.target_thickness > machine.max_thickness
    ):
        issues.append(MachineFitIssue(
            code="eligibility.thickness_out_of_range",
            root_cause=(
                f"{machine.machine_id} 厚度能力 {machine.min_thickness}-{machine.max_thickness}um，"
                f"不覆盖订单 {order.order_id} 的 {order.target_thickness}um。"
            ),
            evidence=[
                DiagnosticEvidence("target_thickness", order.target_thickness, "um", entity_id=order.order_id),
                DiagnosticEvidence(
                    "machine_thickness_range",
                    f"{machine.min_thickness}-{machine.max_thickness}",
                    "um",
                    entity_id=machine.machine_id,
                ),
            ],
        ))

    if len(order.recipe_materials) > machine.layer_structure:
        issues.append(MachineFitIssue(
            code="eligibility.layer_mismatch",
            root_cause=(
                f"{machine.machine_id} 为 {machine.layer_structure} 层机，"
                f"订单 {order.order_id} 需要 {len(order.recipe_materials)} 层配方。"
            ),
            evidence=[
                DiagnosticEvidence("order_layers", len(order.recipe_materials), entity_id=order.order_id),
                DiagnosticEvidence("machine_layers", machine.layer_structure, entity_id=machine.machine_id),
            ],
        ))

    return MachineFitResult(
        machine_id=machine.machine_id,
        eligible=not issues,
        issues=issues,
    )


def build_infeasible_order_diagnostic(
    order: ProductionOrderModel,
    machines: Iterable[BlownFilmMachineModel],
    fit_results: Optional[Iterable[MachineFitResult]] = None,
) -> Diagnostic:
    machine_list = list(machines)
    results = list(fit_results or [evaluate_machine_fit(order, m) for m in machine_list])
    issue_counts: Dict[str, int] = {}
    for result in results:
        for issue in result.issues:
            issue_counts[issue.code] = issue_counts.get(issue.code, 0) + 1

    primary_code = _pick_primary_eligibility_code(order, machine_list, issue_counts)
    evidence = [
        DiagnosticEvidence("candidate_machine_count", len(machine_list)),
        DiagnosticEvidence("eligible_machine_count", 0),
        DiagnosticEvidence("target_width", order.target_width, "mm", entity_id=order.order_id),
        DiagnosticEvidence("target_thickness", order.target_thickness, "um", entity_id=order.order_id),
        DiagnosticEvidence("cleanroom_req", order.cleanroom_req, entity_id=order.order_id),
        DiagnosticEvidence("recipe_layers", len(order.recipe_materials), entity_id=order.order_id),
    ]

    if machine_list:
        evidence.extend([
            DiagnosticEvidence(
                "available_width_range",
                f"{min(m.min_width for m in machine_list)}-{max(m.max_width for m in machine_list)}",
                "mm",
            ),
            DiagnosticEvidence(
                "available_thickness_range",
                f"{min(m.min_thickness for m in machine_list)}-{max(m.max_thickness for m in machine_list)}",
                "um",
            ),
            DiagnosticEvidence(
                "max_machine_layers",
                max(m.layer_structure for m in machine_list),
            ),
        ])

    for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0])):
        evidence.append(DiagnosticEvidence(f"blocker_count:{code}", count))

    strongest_blockers = []
    for fit in results[:5]:
        if fit.issues:
            strongest_blockers.append(
                f"{fit.machine_id}: " + "; ".join(issue.root_cause for issue in fit.issues[:2])
            )
    for blocker in strongest_blockers:
        evidence.append(DiagnosticEvidence("machine_blocker", blocker))

    return Diagnostic(
        entity_type="order",
        entity_id=order.order_id,
        severity="critical",
        category="eligibility",
        code=primary_code,
        confidence="proven",
        root_cause=_eligibility_root_cause(
            order,
            machine_list,
            primary_code,
            issue_counts,
            results,
        ),
        evidence=evidence,
        recommendations=_eligibility_recommendations(order.order_id, primary_code),
        display_title=f"{order.order_id} 无可用机台",
    )


def build_lateness_diagnostic(task: Any) -> Optional[Diagnostic]:
    order = task.order
    tardiness = max(0, task.end_mins - order.due_date_mins)
    if tardiness <= 0:
        return None

    duration = max(1, task.end_mins - task.start_mins)
    if order.material_available_mins and order.material_available_mins > order.due_date_mins:
        code = "material.not_available"
        category = "material"
        confidence = "proven"
        root = (
            f"订单 {order.order_id} 原料齐套时间晚于交期，"
            f"排程无论如何都会逾期 {tardiness} 分钟以上。"
        )
    elif order.material_available_mins and order.material_available_mins + duration > order.due_date_mins:
        code = "lateness.material_wait"
        category = "lateness"
        confidence = "proven"
        root = f"订单 {order.order_id} 受原料齐套时间约束，最早可生产窗口已经压近交期。"
    elif task.setup_time >= max(60, int(duration * 0.25)):
        code = "lateness.setup_burden"
        category = "lateness"
        confidence = "inferred"
        root = f"订单 {order.order_id} 前置换产 {task.setup_time} 分钟，占用关键产能并推高逾期。"
    elif order.order_date_mins + duration + task.setup_time > order.due_date_mins:
        code = "lateness.due_too_tight"
        category = "lateness"
        confidence = "proven"
        root = f"订单 {order.order_id} 从下单到交期的窗口小于理论生产加换产时间。"
    else:
        code = "lateness.machine_bottleneck"
        category = "lateness"
        confidence = "inferred"
        root = f"订单 {order.order_id} 逾期主要来自可用机台产能竞争。"

    return Diagnostic(
        entity_type="order",
        entity_id=order.order_id,
        severity="warning",
        category=category,
        code=code,
        confidence=confidence,
        root_cause=root,
        evidence=[
            DiagnosticEvidence("scheduled_end_mins", task.end_mins, "min"),
            DiagnosticEvidence("due_date_mins", order.due_date_mins, "min"),
            DiagnosticEvidence("tardiness_mins", tardiness, "min"),
            DiagnosticEvidence("material_available_mins", order.material_available_mins, "min"),
            DiagnosticEvidence("setup_time_mins", task.setup_time, "min"),
            DiagnosticEvidence("duration_mins", duration, "min"),
            DiagnosticEvidence("assigned_machine", task.machine.machine_id),
        ],
        recommendations=[
            DiagnosticRecommendation(
                "review_due_or_priority",
                "检查订单交期、等级和原料齐套时间",
                f"/config?tab=orders&order={order.order_id}",
            ),
            DiagnosticRecommendation(
                "review_machine_capacity",
                "检查瓶颈机台能力或状态",
                f"/config?tab=machines&machine={task.machine.machine_id}",
            ),
        ],
        display_title=f"{order.order_id} 逾期 {tardiness} 分钟",
    )


def build_setup_diagnostic(task: Any, previous_order_id: Optional[str]) -> Optional[Diagnostic]:
    duration = max(1, task.end_mins - task.start_mins)
    if task.setup_time <= 0 or task.setup_time < 60 and task.setup_time < int(duration * 0.25):
        return None

    severity = "warning" if task.setup_time >= 120 else "info"
    return Diagnostic(
        entity_type="order",
        entity_id=task.order.order_id,
        severity=severity,
        category="setup",
        code="setup.sequence_changeover",
        confidence="inferred",
        root_cause=(
            f"订单 {task.order.order_id} 前置换产 {task.setup_time} 分钟，"
            "建议复核材料、幅宽、厚度或 GMP 清场规则。"
        ),
        evidence=[
            DiagnosticEvidence("setup_time_mins", task.setup_time, "min"),
            DiagnosticEvidence("duration_mins", duration, "min"),
            DiagnosticEvidence("setup_ratio", round(task.setup_time / duration, 2)),
            DiagnosticEvidence("previous_order_id", previous_order_id or "machine_initial_state"),
            DiagnosticEvidence("machine_id", task.machine.machine_id),
        ],
        recommendations=[
            DiagnosticRecommendation(
                "review_setup_rules",
                "检查换产规则",
                "/config?tab=rules",
            ),
            DiagnosticRecommendation(
                "review_order_sequence_driver",
                "查看订单配置",
                f"/config?tab=orders&order={task.order.order_id}",
            ),
        ],
        display_title=f"{task.order.order_id} 换产 {task.setup_time} 分钟",
    )


def build_machine_diagnostics(
    result: Any,
    orders: Iterable[ProductionOrderModel],
    machines: Iterable[BlownFilmMachineModel],
) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []
    tasks = list(result.tasks)
    machine_list = list(machines)
    order_list = list(orders)
    if not machine_list:
        return diagnostics

    if tasks:
        horizon_start = min(max(0, t.start_mins - t.setup_time) for t in tasks)
        horizon_end = max(t.end_mins for t in tasks)
    else:
        horizon_start = 0
        horizon_end = max((o.due_date_mins for o in order_list), default=1)
    horizon = max(1, horizon_end - horizon_start)

    for machine in machine_list:
        machine_tasks = sorted(
            result.machine_sequences.get(machine.machine_id, []),
            key=lambda t: t.start_mins,
        )
        prod_mins = sum(t.end_mins - t.start_mins for t in machine_tasks)
        setup_mins = sum(t.setup_time for t in machine_tasks)
        load_pct = round(prod_mins / horizon * 100, 1)

        if not machine_tasks:
            diagnostics.append(_unused_machine_diagnostic(machine, order_list))
            continue

        if load_pct >= 80:
            diagnostics.append(Diagnostic(
                entity_type="machine",
                entity_id=machine.machine_id,
                severity="warning",
                category="capacity",
                code="machine.high_load",
                confidence="inferred",
                root_cause=f"{machine.machine_id} 负载达到 {load_pct}%，是当前排程的潜在瓶颈。",
                evidence=[
                    DiagnosticEvidence("load_pct", load_pct, "%"),
                    DiagnosticEvidence("production_mins", prod_mins, "min"),
                    DiagnosticEvidence("horizon_mins", horizon, "min"),
                    DiagnosticEvidence("scheduled_orders", len(machine_tasks)),
                ],
                recommendations=[
                    DiagnosticRecommendation(
                        "review_machine_capacity",
                        "检查机台产能或可替代机台",
                        f"/config?tab=machines&machine={machine.machine_id}",
                    )
                ],
                display_title=f"{machine.machine_id} 高负载 {load_pct}%",
            ))
        elif load_pct <= 20:
            diagnostics.append(Diagnostic(
                entity_type="machine",
                entity_id=machine.machine_id,
                severity="info",
                category="capacity",
                code="machine.low_load",
                confidence="inferred",
                root_cause=f"{machine.machine_id} 负载仅 {load_pct}%，可作为候选缓冲产能。",
                evidence=[
                    DiagnosticEvidence("load_pct", load_pct, "%"),
                    DiagnosticEvidence("production_mins", prod_mins, "min"),
                    DiagnosticEvidence("horizon_mins", horizon, "min"),
                    DiagnosticEvidence("scheduled_orders", len(machine_tasks)),
                ],
                recommendations=[
                    DiagnosticRecommendation(
                        "review_machine_fit",
                        "检查是否有订单可转移到该机台",
                        f"/config?tab=machines&machine={machine.machine_id}",
                    )
                ],
                display_title=f"{machine.machine_id} 低负载 {load_pct}%",
            ))

        occupied_mins = max(1, prod_mins + setup_mins)
        setup_ratio = setup_mins / occupied_mins
        if setup_mins >= 60 and setup_ratio >= 0.2:
            diagnostics.append(Diagnostic(
                entity_type="machine",
                entity_id=machine.machine_id,
                severity="warning",
                category="setup",
                code="machine.changeover_heavy",
                confidence="inferred",
                root_cause=(
                    f"{machine.machine_id} 换产占用 {round(setup_ratio * 100, 1)}%，"
                    "需要检查订单组合或换产规则。"
                ),
                evidence=[
                    DiagnosticEvidence("setup_mins", setup_mins, "min"),
                    DiagnosticEvidence("production_mins", prod_mins, "min"),
                    DiagnosticEvidence("setup_ratio", round(setup_ratio, 2)),
                    DiagnosticEvidence("scheduled_orders", len(machine_tasks)),
                ],
                recommendations=[
                    DiagnosticRecommendation("review_setup_rules", "检查换产规则", "/config?tab=rules"),
                    DiagnosticRecommendation(
                        "review_machine_sequence",
                        "查看机台甘特图",
                        f"/gantt?machine={machine.machine_id}",
                    ),
                ],
                display_title=f"{machine.machine_id} 换产占比 {round(setup_ratio * 100, 1)}%",
            ))

    return diagnostics


def build_result_diagnostics(
    result: Any,
    orders: Iterable[ProductionOrderModel],
    machines: Iterable[BlownFilmMachineModel],
) -> List[Diagnostic]:
    diagnostics: List[Diagnostic] = []

    for task in result.tasks:
        late_diag = build_lateness_diagnostic(task)
        if late_diag:
            diagnostics.append(late_diag)

    for machine_id, tasks in result.machine_sequences.items():
        previous_order_id = None
        for task in sorted(tasks, key=lambda item: item.start_mins):
            setup_diag = build_setup_diagnostic(task, previous_order_id)
            if setup_diag:
                diagnostics.append(setup_diag)
            previous_order_id = task.order.order_id

    diagnostics.extend(build_machine_diagnostics(result, orders, machines))
    return diagnostics


def parse_infeasible_log_diagnostics(text: str) -> List[Dict[str, Any]]:
    """Best-effort fallback for failed child-process logs."""

    diagnostics = []
    if not text:
        return diagnostics

    pattern = re.compile(r"订单\s+([A-Za-z0-9_-]+)\s+无可用机台[:：]?\s*([^\r\n]*)")
    for match in pattern.finditer(text):
        order_id = match.group(1)
        spec = match.group(2).strip()
        evidence = [DiagnosticEvidence("raw_reason", spec or "no eligible machine")]
        for key, value in re.findall(r"([A-Za-z_]+)=([^,\s]+)", spec):
            evidence.append(DiagnosticEvidence(key, value, entity_id=order_id))

        diagnostics.append(Diagnostic(
            entity_type="order",
            entity_id=order_id,
            severity="critical",
            category="eligibility",
            code="eligibility.no_eligible_machine",
            confidence="proven",
            root_cause=f"订单 {order_id} 没有任何可用机台，需检查订单规格、洁净度、层数或机台能力。",
            evidence=evidence,
            recommendations=[
                DiagnosticRecommendation(
                    "review_order",
                    "检查订单配置",
                    f"/config?tab=orders&order={order_id}",
                ),
                DiagnosticRecommendation(
                    "review_machine_capacity",
                    "检查机台能力配置",
                    "/config?tab=machines",
                ),
            ],
        ).to_dict())

    return diagnostics


def diagnostics_to_dicts(
    diagnostics: Iterable[Diagnostic],
    run_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    return [item.to_dict(run_id=run_id) for item in diagnostics]


def _pick_primary_eligibility_code(
    order: ProductionOrderModel,
    machines: List[BlownFilmMachineModel],
    issue_counts: Dict[str, int],
) -> str:
    if not machines:
        return "eligibility.machine_unavailable"

    width_min = min(m.min_width for m in machines)
    width_max = max(m.max_width for m in machines)
    if (
        issue_counts.get("eligibility.width_out_of_range")
        and (order.target_width < width_min or order.target_width > width_max)
    ):
        return "eligibility.width_out_of_range"

    thick_min = min(m.min_thickness for m in machines)
    thick_max = max(m.max_thickness for m in machines)
    if (
        issue_counts.get("eligibility.thickness_out_of_range")
        and (
            order.target_thickness < thick_min
            or order.target_thickness > thick_max
        )
    ):
        return "eligibility.thickness_out_of_range"

    if (
        issue_counts.get("eligibility.cleanroom_mismatch")
        and order.cleanroom_req == "Class_10K"
        and not any(_machine_matches_cleanroom(order, machine) for machine in machines)
    ):
        return "eligibility.cleanroom_mismatch"

    recipe_layers = len(order.recipe_materials)
    if (
        issue_counts.get("eligibility.layer_mismatch")
        and recipe_layers > max(m.layer_structure for m in machines)
    ):
        return "eligibility.layer_mismatch"

    if issue_counts:
        return "eligibility.combined_constraint_mismatch"
    return "eligibility.no_eligible_machine"


def _eligibility_root_cause(
    order: ProductionOrderModel,
    machines: List[BlownFilmMachineModel],
    code: str,
    issue_counts: Optional[Dict[str, int]] = None,
    fit_results: Optional[List[MachineFitResult]] = None,
) -> str:
    if not machines:
        return "当前没有 ACTIVE 机台可参与排程。"

    if code == "eligibility.width_out_of_range":
        width_min = min(m.min_width for m in machines)
        width_max = max(m.max_width for m in machines)
        return (
            f"订单 {order.order_id} 幅宽 {order.target_width}mm 不在可用机台范围 "
            f"{width_min}-{width_max}mm 内。"
        )
    if code == "eligibility.thickness_out_of_range":
        thick_min = min(m.min_thickness for m in machines)
        thick_max = max(m.max_thickness for m in machines)
        return (
            f"订单 {order.order_id} 厚度 {order.target_thickness}um 不在可用机台范围 "
            f"{thick_min}-{thick_max}um 内。"
        )
    if code == "eligibility.cleanroom_mismatch":
        return f"订单 {order.order_id} 洁净度要求 {order.cleanroom_req}，当前候选机台洁净能力不足。"
    if code == "eligibility.layer_mismatch":
        return f"订单 {order.order_id} 配方层数 {len(order.recipe_materials)} 超过可用机台层数能力。"
    if code == "eligibility.combined_constraint_mismatch":
        return _combined_constraint_root_cause(
            order,
            machines,
            issue_counts or {},
            fit_results or [],
        )
    return f"订单 {order.order_id} 没有任何可用机台，需要联合检查订单规格和机台能力。"


def _eligibility_recommendations(order_id: str, code: str) -> List[DiagnosticRecommendation]:
    recs = [
        DiagnosticRecommendation(
            "review_order",
            "检查订单规格和状态",
            f"/config?tab=orders&order={order_id}",
        )
    ]
    if code in {
        "eligibility.width_out_of_range",
        "eligibility.thickness_out_of_range",
        "eligibility.cleanroom_mismatch",
        "eligibility.layer_mismatch",
        "eligibility.combined_constraint_mismatch",
        "eligibility.machine_unavailable",
        "eligibility.no_eligible_machine",
    }:
        recs.append(DiagnosticRecommendation(
            "review_machine_capacity",
            "检查机台能力和状态",
            "/config?tab=machines",
        ))
    return recs


def _machine_matches_cleanroom(
    order: ProductionOrderModel,
    machine: BlownFilmMachineModel,
) -> bool:
    return not (
        order.cleanroom_req == "Class_10K"
        and machine.cleanroom_level == "Class_100K"
    )


def _format_machine_list(machines: List[BlownFilmMachineModel], limit: int = 3) -> str:
    ids = [machine.machine_id for machine in machines[:limit]]
    text = "/".join(ids)
    if len(machines) > limit:
        text += f" 等 {len(machines)} 台"
    return text


def _format_issue_name(code: str) -> str:
    return {
        "eligibility.width_out_of_range": "宽幅不覆盖",
        "eligibility.thickness_out_of_range": "厚度不覆盖",
        "eligibility.cleanroom_mismatch": "洁净度不匹配",
        "eligibility.layer_mismatch": "层数不匹配",
    }.get(code, code)


def _format_issue_counts(issue_counts: Dict[str, int]) -> str:
    parts = []
    for code, count in sorted(issue_counts.items(), key=lambda item: (-item[1], item[0])):
        parts.append(f"{_format_issue_name(code)} {count} 台")
    return "、".join(parts)


def _combined_constraint_root_cause(
    order: ProductionOrderModel,
    machines: List[BlownFilmMachineModel],
    issue_counts: Dict[str, int],
    fit_results: List[MachineFitResult],
) -> str:
    recipe_layers = len(order.recipe_materials)
    requirement = (
        f"{recipe_layers}层、{order.cleanroom_req}、"
        f"{order.target_width}mm 幅宽和 {order.target_thickness}um 厚度"
    )
    parts = [f"订单 {order.order_id} 没有单台机同时满足 {requirement}。"]

    clean_layer_machines = [
        machine for machine in machines
        if _machine_matches_cleanroom(order, machine)
        and recipe_layers <= machine.layer_structure
    ]
    if clean_layer_machines:
        width_min = min(machine.min_width for machine in clean_layer_machines)
        width_max = max(machine.max_width for machine in clean_layer_machines)
        thick_min = min(machine.min_thickness for machine in clean_layer_machines)
        thick_max = max(machine.max_thickness for machine in clean_layer_machines)
        parts.append(
            f"满足洁净度和层数的 {_format_machine_list(clean_layer_machines)} 机台，"
            f"能力范围为宽幅 {width_min}-{width_max}mm、厚度 {thick_min}-{thick_max}um。"
        )

    result_by_machine = {fit.machine_id: fit for fit in fit_results}
    width_capable_machines = [
        machine for machine in machines
        if machine.min_width <= order.target_width <= machine.max_width
    ]
    width_capable_blockers: Dict[str, int] = {}
    for machine in width_capable_machines:
        fit = result_by_machine.get(machine.machine_id)
        if not fit:
            continue
        for issue in fit.issues:
            if issue.code == "eligibility.width_out_of_range":
                continue
            width_capable_blockers[issue.code] = width_capable_blockers.get(issue.code, 0) + 1
    if width_capable_machines and width_capable_blockers:
        parts.append(
            f"宽幅可覆盖的 {_format_machine_list(width_capable_machines)} 机台，"
            f"仍受{_format_issue_counts(width_capable_blockers)}限制。"
        )

    if issue_counts:
        parts.append(f"全体候选机台阻断分布：{_format_issue_counts(issue_counts)}。")

    return "".join(parts)


def _unused_machine_diagnostic(
    machine: BlownFilmMachineModel,
    orders: List[ProductionOrderModel],
) -> Diagnostic:
    feasible_orders = [
        order for order in orders
        if evaluate_machine_fit(order, machine).eligible
    ]
    if not feasible_orders:
        code = "machine.unused_capacity_missing"
        confidence = "proven"
        root = f"{machine.machine_id} 未被使用，因为当前订单池没有满足其能力边界的订单。"
    else:
        ready_orders = [order for order in feasible_orders if order.material_available_mins <= order.due_date_mins]
        if not ready_orders:
            code = "machine.unused_no_ready_orders"
            confidence = "inferred"
            root = f"{machine.machine_id} 有理论可生产订单，但这些订单受原料齐套或交期约束影响。"
        else:
            code = "machine.unused_lost_to_better_choice"
            confidence = "inferred"
            root = f"{machine.machine_id} 有可生产订单，但求解器选择了更优机台组合。"

    return Diagnostic(
        entity_type="machine",
        entity_id=machine.machine_id,
        severity="info",
        category="capacity",
        code=code,
        confidence=confidence,
        root_cause=root,
        evidence=[
            DiagnosticEvidence("feasible_order_count", len(feasible_orders)),
            DiagnosticEvidence("candidate_order_count", len(orders)),
            DiagnosticEvidence("width_range", f"{machine.min_width}-{machine.max_width}", "mm"),
            DiagnosticEvidence("thickness_range", f"{machine.min_thickness}-{machine.max_thickness}", "um"),
            DiagnosticEvidence("layer_structure", machine.layer_structure),
        ],
        recommendations=[
            DiagnosticRecommendation(
                "review_machine_capacity",
                "检查机台能力或状态",
                f"/config?tab=machines&machine={machine.machine_id}",
            ),
            DiagnosticRecommendation(
                "review_orders",
                "检查订单池",
                "/config?tab=orders",
            ),
        ],
        display_title=f"{machine.machine_id} 未使用",
    )


def _slug(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "-", text)
    return text.strip("-") or "item"
