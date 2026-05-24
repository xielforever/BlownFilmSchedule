"""Computed-only order screening before schedule preplanning."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Optional

from src.diagnostics import (
    Diagnostic,
    DiagnosticEvidence,
    build_infeasible_order_diagnostic,
    evaluate_machine_fit,
)
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.snapshotting import stable_hash


DEFAULT_SCREENING_POLICY = {
    "due_risk_min_slack_mins": 240,
    "due_risk_duration_multiplier": 1.5,
    "allowed_order_statuses": ["PENDING"],
    "prohibited_override_codes": [
        "missing_product",
        "missing_recipe",
        "no_eligible_machine",
        "status_not_pending",
    ],
    "restricted_override_codes": [
        "material_not_ready",
        "due_risk",
    ],
}


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _action(action: str, label: str, href: str, category: str, guidance: str) -> dict:
    return {
        "action": action,
        "label": label,
        "href": href,
        "category": category,
        "guidance": guidance,
    }


def _order_edit_action(order_id: str, *, label: str = "打开订单修订", guidance: str) -> dict:
    return _action(
        "review_order",
        label,
        f"/config?tab=orders&order={order_id}",
        "order",
        guidance,
    )


def _machine_action(*, action: str = "review_machine_capacity", label: str, guidance: str) -> dict:
    return _action(action, label, "/config?tab=machines", "machine", guidance)


def _rules_action(*, action: str = "review_rules", label: str, guidance: str) -> dict:
    return _action(action, label, "/config?tab=rules", "rules", guidance)


def _screening_recommendations(order_id: str, code: str, diagnostic_code: Optional[str] = None) -> list[dict]:
    if code == "status_not_pending":
        return [
            _action(
                "release_or_reopen_order",
                "确认订单是否应回到待排",
                f"/config?tab=orders&order={order_id}",
                "order",
                "若订单需要重新预排，先撤销相关正式排程或取消未开工队列项，再把订单状态恢复为待排。",
            ),
        ]

    if code == "missing_product":
        return [
            _rules_action(
                action="configure_product",
                label="补齐产品主数据",
                guidance="先补齐产品类型及配方入口，否则求解器无法计算材料、层数和换产约束。",
            ),
            _order_edit_action(
                order_id,
                label="修正订单产品类型",
                guidance="如果订单产品类型录入错误，在订单配置中修正后重新初筛。",
            ),
        ]

    if code == "missing_recipe":
        return [
            _rules_action(
                action="configure_recipe",
                label="补齐产品配方",
                guidance="补齐配方层数和材料结构后再预排，避免后续机台层数和材料切换规则失真。",
            ),
            _order_edit_action(
                order_id,
                label="核对订单产品类型",
                guidance="如果产品类型选错，先修订订单产品类型并记录原因。",
            ),
        ]

    if code == "no_eligible_machine":
        if diagnostic_code == "eligibility.cleanroom_mismatch":
            primary = _machine_action(
                action="align_cleanroom_capacity",
                label="调整洁净机台能力",
                guidance="确认是否有满足洁净等级的机台可开放，或修订订单洁净等级要求。",
            )
        elif diagnostic_code == "eligibility.layer_mismatch":
            primary = _machine_action(
                action="align_layer_capacity",
                label="调整机台层数能力",
                guidance="确认是否存在满足配方层数的机台，或补齐/修订产品配方。",
            )
        elif diagnostic_code == "eligibility.combined_constraint_mismatch":
            primary = _machine_action(
                action="review_machine_constraint_mix",
                label="复核机台组合能力",
                guidance="单台机未同时满足洁净、层数、幅宽和厚度要求；需调整机台能力、订单规格或配方。",
            )
        else:
            primary = _machine_action(
                action="expand_machine_capability",
                label="调整机台规格能力",
                guidance="订单规格超出当前可用机台范围；需扩展机台能力配置，或修订订单幅宽/厚度。",
            )
        return [
            primary,
            _order_edit_action(
                order_id,
                label="修订订单规格",
                guidance="如果订单规格录入错误，在订单配置中修正幅宽、厚度、洁净等级或产品类型。",
            ),
        ]

    if code == "material_not_ready":
        return [
            _action(
                "update_material_or_due_date",
                "更新物料齐套或交期",
                f"/config?tab=orders&order={order_id}",
                "material",
                "确认真实到料时间；若无法提前齐套，需要协商交期或拆分订单后重新预排。",
            ),
        ]

    if code == "due_risk":
        return [
            _action(
                "relieve_due_risk",
                "缓解交期风险",
                f"/config?tab=orders&order={order_id}",
                "schedule",
                "优先核对交期、数量和物料时间；必要时拆分订单、协商交期或提高排程优先级。",
            ),
            _machine_action(
                label="复核可用产能",
                guidance="检查是否有更高产能或更早可用机台，减少理论完工时间。",
            ),
            _rules_action(
                label="复核换产约束",
                guidance="检查材料、幅宽、厚度和清场规则是否过严或缺失。",
            ),
        ]

    return [
        _order_edit_action(
            order_id,
            guidance="先检查订单调度关键字段，再重新运行初筛和预排。",
        ),
    ]


def _evidence(**values) -> list[dict]:
    return [
        DiagnosticEvidence(metric, actual).to_dict()
        for metric, actual in values.items()
        if actual is not None
    ]


def _business_bucket(screening_status: str, code: str, diagnostic_code: Optional[str] = None) -> str:
    if screening_status == "ready":
        return "ready"
    if screening_status == "risk":
        return "risk"
    if code in {"missing_product", "missing_recipe", "status_not_pending"}:
        return "blocked_data_error"
    if code == "material_not_ready":
        return "blocked_material"
    if code == "no_eligible_machine" and diagnostic_code == "eligibility.cleanroom_mismatch":
        return "blocked_cleanroom"
    if code == "no_eligible_machine":
        return "blocked_machine_capability"
    if screening_status == "blocked":
        return "blocked_policy"
    return screening_status or "unknown"


def _item(
    order: ProductionOrderModel,
    *,
    screening_status: str,
    code: str,
    severity: str,
    root_cause: str,
    candidate_machine_count: int,
    eligible_machine_count: int,
    evidence: Optional[list[dict]] = None,
    recommendations: Optional[list[dict]] = None,
    diagnostic_code: Optional[str] = None,
    best_duration_mins: Optional[int] = None,
    slack_mins: Optional[int] = None,
    override_policy: Optional[dict] = None,
) -> dict:
    item = {
        "order_id": order.order_id,
        "screening_status": screening_status,
        "business_bucket": _business_bucket(screening_status, code, diagnostic_code),
        "code": code,
        "severity": severity,
        "root_cause": root_cause,
        "product_type": order.product_type,
        "target_width": order.target_width,
        "target_thickness": order.target_thickness,
        "total_quantity_kg": order.total_quantity_kg,
        "cleanroom_req": order.cleanroom_req,
        "order_class": order.order_class,
        "candidate_machine_count": candidate_machine_count,
        "eligible_machine_count": eligible_machine_count,
        "recipe_layers": len(order.recipe_materials),
        "best_duration_mins": best_duration_mins,
        "slack_mins": slack_mins,
        "diagnostic_code": diagnostic_code,
        "evidence": evidence or [],
        "recommendations": recommendations or _screening_recommendations(order.order_id, code, diagnostic_code),
    }
    item["override_decision"] = override_decision_for_screening_item(item, override_policy)
    return item


def _best_duration(order: ProductionOrderModel, machines: list[BlownFilmMachineModel]) -> Optional[int]:
    if not machines:
        return None
    return min(machine.calculate_duration(order) for machine in machines)


def _due_risk_item(
    order: ProductionOrderModel,
    *,
    candidate_machine_count: int,
    eligible_machine_count: int,
    best_duration_mins: int,
    blocked: bool,
    override_policy: Optional[dict] = None,
) -> dict:
    earliest_start = max(order.order_date_mins or 0, order.material_available_mins or 0)
    earliest_finish = earliest_start + best_duration_mins
    slack = order.due_date_mins - earliest_finish
    root = (
        f"订单 {order.order_id} 最短理论完工时间仍晚于交期。"
        if blocked
        else f"订单 {order.order_id} 理论交期余量仅 {slack} 分钟，排程风险较高。"
    )
    return _item(
        order,
        screening_status="blocked" if blocked else "risk",
        code="due_risk",
        severity="critical" if blocked else "warning",
        root_cause=root,
        candidate_machine_count=candidate_machine_count,
        eligible_machine_count=eligible_machine_count,
        best_duration_mins=best_duration_mins,
        slack_mins=slack,
        evidence=_evidence(
            earliest_start_mins=earliest_start,
            best_duration_mins=best_duration_mins,
            earliest_finish_mins=earliest_finish,
            due_date_mins=order.due_date_mins,
            slack_mins=slack,
        ),
        recommendations=_screening_recommendations(order.order_id, "due_risk"),
        override_policy=override_policy,
    )


def _normalize_screening_policy(policy: Optional[dict] = None) -> dict:
    policy = policy or {}
    min_slack = policy.get(
        "due_risk_min_slack_mins",
        DEFAULT_SCREENING_POLICY["due_risk_min_slack_mins"],
    )
    duration_multiplier = policy.get(
        "due_risk_duration_multiplier",
        DEFAULT_SCREENING_POLICY["due_risk_duration_multiplier"],
    )
    allowed_statuses = policy.get(
        "allowed_order_statuses",
        DEFAULT_SCREENING_POLICY["allowed_order_statuses"],
    )
    prohibited_override_codes = policy.get(
        "prohibited_override_codes",
        DEFAULT_SCREENING_POLICY["prohibited_override_codes"],
    )
    restricted_override_codes = policy.get(
        "restricted_override_codes",
        DEFAULT_SCREENING_POLICY["restricted_override_codes"],
    )
    return {
        "due_risk_min_slack_mins": max(0, int(min_slack)),
        "due_risk_duration_multiplier": max(0.0, float(duration_multiplier)),
        "allowed_order_statuses": _normalize_policy_values(
            allowed_statuses,
            transform=str.upper,
        ) or set(DEFAULT_SCREENING_POLICY["allowed_order_statuses"]),
        "prohibited_override_codes": _normalize_policy_values(prohibited_override_codes),
        "restricted_override_codes": _normalize_policy_values(restricted_override_codes),
    }


def _normalize_policy_values(values, *, transform=str.lower) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    return {
        transform(str(value).strip())
        for value in values
        if str(value).strip()
    }


def screen_order(
    order: ProductionOrderModel,
    machines: Iterable[BlownFilmMachineModel],
    *,
    status: str = "PENDING",
    product_exists: bool = True,
    screening_policy: Optional[dict] = None,
) -> dict:
    machine_list = list(machines)
    policy = _normalize_screening_policy(screening_policy)
    candidate_machine_count = len(machine_list)
    fit_results = [evaluate_machine_fit(order, machine) for machine in machine_list]
    eligible_machines = [
        machine
        for machine, fit in zip(machine_list, fit_results)
        if fit.eligible
    ]
    eligible_machine_count = len(eligible_machines)

    normalized_status = (status or "").strip().upper()
    if normalized_status not in policy["allowed_order_statuses"]:
        return _item(
            order,
            screening_status="blocked",
            code="status_not_pending",
            severity="critical",
            root_cause=f"订单 {order.order_id} 当前状态为 {status}，只有待排订单可以进入预排。",
            candidate_machine_count=candidate_machine_count,
            eligible_machine_count=eligible_machine_count,
            evidence=_evidence(order_status=status),
            override_policy=policy,
        )

    if not product_exists:
        return _item(
            order,
            screening_status="blocked",
            code="missing_product",
            severity="critical",
            root_cause=f"订单 {order.order_id} 的产品类型 {order.product_type} 不存在。",
            candidate_machine_count=candidate_machine_count,
            eligible_machine_count=0,
            evidence=_evidence(product_type=order.product_type),
            recommendations=_screening_recommendations(order.order_id, "missing_product"),
            override_policy=policy,
        )

    if not order.recipe_materials:
        return _item(
            order,
            screening_status="blocked",
            code="missing_recipe",
            severity="critical",
            root_cause=f"订单 {order.order_id} 的产品 {order.product_type} 没有可用配方。",
            candidate_machine_count=candidate_machine_count,
            eligible_machine_count=0,
            evidence=_evidence(product_type=order.product_type, recipe_layers=0),
            recommendations=_screening_recommendations(order.order_id, "missing_recipe"),
            override_policy=policy,
        )

    if eligible_machine_count == 0:
        diagnostic: Diagnostic = build_infeasible_order_diagnostic(order, machine_list, fit_results)
        diagnostic_dict = diagnostic.to_dict()
        return _item(
            order,
            screening_status="blocked",
            code="no_eligible_machine",
            severity="critical",
            root_cause=diagnostic.root_cause,
            candidate_machine_count=candidate_machine_count,
            eligible_machine_count=0,
            evidence=diagnostic_dict["evidence"],
            recommendations=_screening_recommendations(order.order_id, "no_eligible_machine", diagnostic.code),
            diagnostic_code=diagnostic.code,
            override_policy=policy,
        )

    if order.material_available_mins and order.material_available_mins > order.due_date_mins:
        return _item(
            order,
            screening_status="blocked",
            code="material_not_ready",
            severity="critical",
            root_cause=f"订单 {order.order_id} 物料齐套时间晚于交期，不能直接进入有效预排。",
            candidate_machine_count=candidate_machine_count,
            eligible_machine_count=eligible_machine_count,
            evidence=_evidence(
                material_available_mins=order.material_available_mins,
                due_date_mins=order.due_date_mins,
            ),
            recommendations=_screening_recommendations(order.order_id, "material_not_ready"),
            override_policy=policy,
        )

    best_duration_mins = _best_duration(order, eligible_machines)
    if best_duration_mins is not None:
        earliest_start = max(order.order_date_mins or 0, order.material_available_mins or 0)
        slack = order.due_date_mins - (earliest_start + best_duration_mins)
        if slack < 0:
            return _due_risk_item(
                order,
                candidate_machine_count=candidate_machine_count,
                eligible_machine_count=eligible_machine_count,
                best_duration_mins=best_duration_mins,
                blocked=True,
                override_policy=policy,
            )
        risk_threshold = max(
            policy["due_risk_min_slack_mins"],
            int(best_duration_mins * policy["due_risk_duration_multiplier"]),
        )
        if slack <= risk_threshold:
            return _due_risk_item(
                order,
                candidate_machine_count=candidate_machine_count,
                eligible_machine_count=eligible_machine_count,
                best_duration_mins=best_duration_mins,
                blocked=False,
                override_policy=policy,
            )

    return _item(
        order,
        screening_status="ready",
        code="ready",
        severity="info",
        root_cause=f"订单 {order.order_id} 满足当前初筛条件，可进入预排程。",
        candidate_machine_count=candidate_machine_count,
        eligible_machine_count=eligible_machine_count,
        best_duration_mins=best_duration_mins,
        evidence=_evidence(
            eligible_machine_count=eligible_machine_count,
            candidate_machine_count=candidate_machine_count,
            best_duration_mins=best_duration_mins,
        ),
        recommendations=[],
        override_policy=policy,
    )


def _summary(items: list[dict]) -> dict:
    return {
        "total_orders": len(items),
        "ready_count": sum(1 for item in items if item["screening_status"] == "ready"),
        "risk_count": sum(1 for item in items if item["screening_status"] == "risk"),
        "blocked_count": sum(1 for item in items if item["screening_status"] == "blocked"),
        "business_bucket_counts": {
            bucket: sum(1 for item in items if item.get("business_bucket") == bucket)
            for bucket in sorted({item.get("business_bucket") for item in items if item.get("business_bucket")})
        },
    }


PROHIBITED_OVERRIDE_CODES = {
    "missing_product",
    "missing_recipe",
    "no_eligible_machine",
    "status_not_pending",
}

RESTRICTED_OVERRIDE_CODES = {
    "material_not_ready",
    "due_risk",
}


def override_decision_for_screening_item(item: dict, screening_policy: Optional[dict] = None) -> dict:
    policy = _normalize_screening_policy(screening_policy)
    prohibited_codes = policy["prohibited_override_codes"]
    restricted_codes = policy["restricted_override_codes"]
    status = item.get("screening_status")
    code = item.get("code")
    if code in prohibited_codes:
        return {
            "allowed": False,
            "policy": "prohibited",
            "requires_reason": False,
            "reason_code": f"prohibited_{code or 'blocked'}",
        }
    if status == "risk":
        return {
            "allowed": True,
            "policy": "restricted",
            "requires_reason": True,
            "reason_code": f"risk_{code or 'screening'}",
        }
    if status == "ready":
        return {
            "allowed": False,
            "policy": "not_required",
            "requires_reason": False,
            "reason_code": "already_schedulable",
        }
    if code in restricted_codes:
        return {
            "allowed": True,
            "policy": "restricted",
            "requires_reason": True,
            "reason_code": f"restricted_{code}",
        }
    if status == "blocked":
        return {
            "allowed": False,
            "policy": "prohibited",
            "requires_reason": False,
            "reason_code": f"prohibited_{code or 'blocked'}",
        }
    return {
        "allowed": False,
        "policy": "unknown",
        "requires_reason": False,
        "reason_code": f"unknown_{code or status or 'screening'}",
    }


def build_screening_snapshot(screening: dict) -> dict:
    items = [
        {
            "order_id": item.get("order_id"),
            "screening_status": item.get("screening_status"),
            "business_bucket": item.get("business_bucket"),
            "code": item.get("code"),
            "diagnostic_code": item.get("diagnostic_code"),
            "eligible_machine_count": item.get("eligible_machine_count"),
        }
        for item in screening.get("items", [])
    ]
    items = sorted(items, key=lambda item: item.get("order_id") or "")
    summary = screening.get("summary") or _summary(items)
    payload = {
        "mode": screening.get("mode"),
        "scope": screening.get("scope"),
        "summary": summary,
        "items": items,
    }
    return {
        **payload,
        "hash": stable_hash(payload),
    }


def screen_orders(
    orders: Iterable[ProductionOrderModel],
    machines: Iterable[BlownFilmMachineModel],
    *,
    status_by_order_id: Optional[dict[str, str]] = None,
    product_exists_by_order_id: Optional[dict[str, bool]] = None,
    generated_at: Optional[str] = None,
    scope: str = "selected",
    screening_policy: Optional[dict] = None,
) -> dict:
    machine_list = list(machines)
    status_map = status_by_order_id or {}
    product_map = product_exists_by_order_id or {}
    items = [
        screen_order(
            order,
            machine_list,
            status=status_map.get(order.order_id, "PENDING"),
            product_exists=product_map.get(order.order_id, True),
            screening_policy=screening_policy,
        )
        for order in orders
    ]
    return {
        "generated_at": generated_at or _utc_now_iso(),
        "mode": "computed",
        "scope": scope,
        "summary": _summary(items),
        "items": items,
    }
