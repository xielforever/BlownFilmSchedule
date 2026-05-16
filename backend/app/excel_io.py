from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .models import (
    ConstraintAuditRow,
    IssueSeverity,
    Machine,
    OrderJob,
    ScheduleAssignment,
    ScheduleException,
    ScheduleResult,
    ValidationIssue,
)
from .spec_parser import parse_spec


ORDER_COLUMNS = [
    "job_id",
    "order_date",
    "planner",
    "plan_finish_time",
    "formula",
    "batch_no",
    "material_code",
    "spec_raw",
    "order_qty",
    "unit_weight_g",
    "batch_kg",
    "work_hours",
    "urgency",
    "customer",
    "clean_level",
    "is_medical",
    "color",
    "allow_split",
]


REQUIRED_ORDER_COLUMNS = [
    "job_id",
    "plan_finish_time",
    "formula",
    "batch_no",
    "material_code",
    "spec_raw",
    "batch_kg",
]

MAX_ORDER_DUE_SLACK_DAYS = 14
MAX_SAME_DUE_FORMULA_JOBS = 4
MIN_REASONABLE_RATE_KG_H = 10
MAX_REASONABLE_RATE_KG_H = 250
BATCH_QTY_TOLERANCE = 0.15


def load_orders_from_excel(path: Path) -> tuple[list[OrderJob], list[ValidationIssue]]:
    issues: list[ValidationIssue] = []
    try:
        df = pd.read_excel(path, sheet_name="orders")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0)

    df = df.rename(columns={str(col).strip(): str(col).strip() for col in df.columns})

    missing = [col for col in REQUIRED_ORDER_COLUMNS if col not in df.columns]
    for col in missing:
        issues.append(
            ValidationIssue(
                field=col,
                severity=IssueSeverity.ERROR,
                message=f"订单表缺少必填列: {col}",
            )
        )
    if missing:
        return [], issues

    orders: list[OrderJob] = []
    for index, row in df.iterrows():
        raw = _clean_dict(row.to_dict())
        job_id = str(raw.get("job_id") or raw.get("batch_no") or f"ROW-{index + 2}").strip()
        parsed = parse_spec(raw.get("spec_raw"))
        if parsed.parse_status != "ok":
            issues.append(
                ValidationIssue(
                    job_id=job_id,
                    field="spec_raw",
                    severity=IssueSeverity.ERROR,
                    message=parsed.parse_message or "规格解析失败",
                )
            )

        try:
            order = OrderJob(
                job_id=job_id,
                order_date=_as_datetime(raw.get("order_date")),
                planner=_as_str(raw.get("planner")),
                plan_finish_time=_as_datetime(raw.get("plan_finish_time")),
                formula=_as_str(raw.get("formula")),
                batch_no=_as_str(raw.get("batch_no")),
                material_code=_as_str(raw.get("material_code")),
                spec_raw=_as_str(raw.get("spec_raw")) or "",
                order_qty=_as_float(raw.get("order_qty")),
                unit_weight_g=_as_float(raw.get("unit_weight_g")),
                batch_kg=_as_float(raw.get("batch_kg")),
                work_hours=_as_float(raw.get("work_hours")),
                urgency=_as_str(raw.get("urgency")),
                customer=_as_str(raw.get("customer")),
                clean_level=_as_str(raw.get("clean_level")),
                is_medical=_as_bool(raw.get("is_medical")),
                color=_as_str(raw.get("color")),
                allow_split=_as_bool(raw.get("allow_split")),
                parsed_spec=parsed,
            )
            orders.append(order)
        except Exception as exc:
            issues.append(
                ValidationIssue(
                    job_id=job_id,
                    severity=IssueSeverity.ERROR,
                    message=f"订单行无法读取: {exc}",
                )
            )

    _append_order_quality_issues(orders, issues)
    return orders, issues


def _append_order_quality_issues(orders: list[OrderJob], issues: list[ValidationIssue]) -> None:
    by_job_id: dict[str, list[OrderJob]] = defaultdict(list)
    by_due_formula: dict[tuple[datetime, str], list[OrderJob]] = defaultdict(list)

    for order in orders:
        by_job_id[order.job_id].append(order)
        if order.plan_finish_time:
            by_due_formula[(order.plan_finish_time, order.formula or "-")].append(order)

        if not order.plan_finish_time:
            issues.append(
                ValidationIssue(
                    job_id=order.job_id,
                    field="plan_finish_time",
                    severity=IssueSeverity.ERROR,
                    message="订单缺少交期，无法进入交期优先排程。",
                )
            )
        elif order.order_date and order.plan_finish_time < order.order_date:
            issues.append(
                ValidationIssue(
                    job_id=order.job_id,
                    field="plan_finish_time",
                    severity=IssueSeverity.ERROR,
                    message="订单交期早于订单日期，请核对输入时间。",
                )
            )
        elif order.order_date and (order.plan_finish_time - order.order_date).total_seconds() / 86400 > MAX_ORDER_DUE_SLACK_DAYS:
            issues.append(
                ValidationIssue(
                    job_id=order.job_id,
                    field="plan_finish_time",
                    severity=IssueSeverity.WARNING,
                    message=f"订单日期到交期间隔超过 {MAX_ORDER_DUE_SLACK_DAYS} 天，样例或输入可能过松，排程会明显提前完成。",
                )
            )

        if order.batch_kg is None or order.batch_kg <= 0:
            issues.append(
                ValidationIssue(
                    job_id=order.job_id,
                    field="batch_kg",
                    severity=IssueSeverity.ERROR,
                    message="订单缺少有效批量 kg，无法稳定估算生产时长。",
                )
            )
        _validate_quantity_weight(order, issues)
        _validate_work_rate(order, issues)

    for job_id, grouped in by_job_id.items():
        if len(grouped) > 1:
            issues.append(
                ValidationIssue(
                    job_id=job_id,
                    field="job_id",
                    severity=IssueSeverity.ERROR,
                    message=f"订单号重复 {len(grouped)} 行；订单号需要唯一，否则甘特图和导出追踪会混淆。",
                )
            )

    for (due, formula), grouped in by_due_formula.items():
        if len(grouped) >= MAX_SAME_DUE_FORMULA_JOBS:
            job_ids = "/".join(order.job_id for order in grouped[:8])
            if len(grouped) > 8:
                job_ids = f"{job_ids}/..."
            issues.append(
                ValidationIssue(
                    job_id=grouped[0].job_id,
                    field="plan_finish_time",
                    severity=IssueSeverity.WARNING,
                    message=(
                        f"{due.strftime('%Y-%m-%d %H:%M')} 交期下 {formula} 有 {len(grouped)} 单集中到期，"
                        f"涉及 {job_ids}；排程可能分散到多台机以满足可行窗口。"
                    ),
                )
            )


def _validate_quantity_weight(order: OrderJob, issues: list[ValidationIssue]) -> None:
    if not order.order_qty or not order.unit_weight_g or not order.batch_kg:
        return
    expected_kg = order.order_qty * order.unit_weight_g / 1000
    if expected_kg <= 0:
        return
    diff_ratio = abs(order.batch_kg - expected_kg) / expected_kg
    if diff_ratio > BATCH_QTY_TOLERANCE:
        issues.append(
            ValidationIssue(
                job_id=order.job_id,
                field="batch_kg",
                severity=IssueSeverity.WARNING,
                message=f"批量 {order.batch_kg:g}kg 与数量×克重估算 {expected_kg:.1f}kg 偏差超过 {BATCH_QTY_TOLERANCE:.0%}。",
            )
        )


def _validate_work_rate(order: OrderJob, issues: list[ValidationIssue]) -> None:
    if not order.batch_kg or not order.work_hours or order.work_hours <= 0:
        return
    rate = order.batch_kg / order.work_hours
    if rate < MIN_REASONABLE_RATE_KG_H or rate > MAX_REASONABLE_RATE_KG_H:
        issues.append(
            ValidationIssue(
                job_id=order.job_id,
                field="work_hours",
                severity=IssueSeverity.WARNING,
                message=(
                    f"批量/工时折算产能为 {rate:.1f}kg/h，超出常规校验区间 "
                    f"{MIN_REASONABLE_RATE_KG_H}-{MAX_REASONABLE_RATE_KG_H}kg/h，请核对批量或工时。"
                ),
            )
        )


def machines_to_dataframe(machines: list[Machine]) -> pd.DataFrame:
    return pd.DataFrame([machine.model_dump(mode="json") for machine in machines])


def write_schedule_outputs(result: ScheduleResult, output_dir: Path, export_id: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    schedule_path = output_dir / f"{export_id}_schedule_result.xlsx"
    audit_path = output_dir / f"{export_id}_constraint_audit.xlsx"
    report_path = output_dir / f"{export_id}_schedule_report.md"

    assignments = [assignment.model_dump(mode="json") for assignment in result.assignments]
    exceptions = [exception.model_dump(mode="json") for exception in result.exceptions]
    audit = [row.model_dump(mode="json") for row in result.audit]
    machine_loads = [load.model_dump(mode="json") for load in result.machine_loads]
    schedule_insights = [insight.model_dump(mode="json") for insight in result.schedule_insights]
    candidate_audit = [row.model_dump(mode="json") for row in result.candidate_audit]

    with pd.ExcelWriter(schedule_path, engine="openpyxl") as writer:
        pd.DataFrame(assignments).to_excel(writer, sheet_name="schedule", index=False)
        pd.DataFrame(machine_loads).to_excel(writer, sheet_name="machine_loads", index=False)
        pd.DataFrame(schedule_insights).to_excel(writer, sheet_name="schedule_insights", index=False)
        pd.DataFrame(candidate_audit).to_excel(writer, sheet_name="candidate_audit", index=False)
        pd.DataFrame(exceptions).to_excel(writer, sheet_name="exceptions", index=False)

    with pd.ExcelWriter(audit_path, engine="openpyxl") as writer:
        pd.DataFrame(audit).to_excel(writer, sheet_name="audit", index=False)
        pd.DataFrame([issue.model_dump(mode="json") for issue in result.validation_issues]).to_excel(
            writer, sheet_name="validation_issues", index=False
        )

    report_path.write_text(_build_markdown_report(result), encoding="utf-8")
    return {"schedule": schedule_path, "audit": audit_path, "report": report_path}


def _build_markdown_report(result: ScheduleResult) -> str:
    lines = [
        "# 吹膜排程报告",
        "",
        "## 汇总",
        "",
        f"- 总订单: {result.summary.total_jobs}",
        f"- 已排订单: {result.summary.scheduled_jobs}",
        f"- 未排订单: {result.summary.unplanned_jobs}",
        f"- 延期订单: {result.summary.late_jobs}",
        f"- 生产小时: {result.summary.total_production_hours:.1f}h",
        f"- 换型小时: {result.summary.total_changeover_hours:.1f}h",
        f"- 边界适配订单: {result.summary.marginal_jobs}",
        f"- 活跃机台平均负荷: {result.summary.average_load_pct:.1f}%",
        f"- 排程解释项: {len(result.schedule_insights)}",
        f"- 候选机台审计项: {len(result.candidate_audit)}",
        "",
        "## 机台负荷",
        "",
        "| 机台 | 订单 | 生产 | 换型 | 占用 | 空档 | 负荷 | 边界适配 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for load in [item for item in result.machine_loads if item.job_count > 0]:
        lines.append(
            f"| {load.machine_id} | {load.job_count} | {load.production_hours:.1f}h | {load.changeover_hours:.1f}h | "
            f"{load.occupied_hours:.1f}h | {load.idle_hours:.1f}h | {load.load_pct:.1f}% | {load.marginal_jobs} |"
        )
    lines.extend(["", "## 排程解释", ""])
    if result.schedule_insights:
        lines.append("| 类型 | 级别 | 订单 | 关联订单 | 机台 | 指标 | 说明 |")
        lines.append("|---|---|---|---|---|---:|---|")
        for item in result.schedule_insights:
            lines.append(
                "| {title} | {severity} | {job} | {related} | {machine} | {metric} | {message} |".format(
                    title=item.title.replace("|", "/"),
                    severity=item.severity.value,
                    job=item.job_id or "-",
                    related=item.related_job_id or "-",
                    machine=item.machine_id or "-",
                    metric=f"{item.metric_hours:.1f}h" if item.metric_hours is not None else "-",
                    message=item.message.replace("|", "/"),
                )
            )
    else:
        lines.append("暂无需要特别解释的长空档、同交期分散、交期余量或边界适配。")
    lines.extend(["", "## 候选机台审计", ""])
    if result.candidate_audit:
        lines.append("| 订单 | 排名 | 机台 | 选中 | 适配 | 评分 | 差值 | 开始 | 完成 | 生产 | 换型 | 决策说明 |")
        lines.append("|---|---:|---|---|---|---:|---:|---|---|---:|---:|---|")
        for item in result.candidate_audit:
            lines.append(
                "| {job} | {rank} | {machine} | {selected} | {fit} | {score:.1f} | {delta:.1f} | {start} | {end} | {production:.1f}h | {changeover:.1f}h | {decision} |".format(
                    job=item.job_id,
                    rank=item.rank,
                    machine=item.machine_id,
                    selected="是" if item.selected else "否",
                    fit=item.fit_level or "-",
                    score=item.score,
                    delta=item.score_delta,
                    start=item.start_time.strftime("%Y-%m-%d %H:%M"),
                    end=item.end_time.strftime("%Y-%m-%d %H:%M"),
                    production=item.production_hours,
                    changeover=item.changeover_hours,
                    decision=item.decision_reason.replace("|", "/"),
                )
            )
    else:
        lines.append("暂无候选机台审计。")
    lines.extend(
        [
            "",
            "## 机台排程",
            "",
        ]
    )
    for machine_id in sorted({item.machine_id for item in result.assignments}):
        lines.append(f"### {machine_id}")
        lines.append("")
        lines.append("| 顺序 | 订单 | 适配 | 排序依据 | 前序空档 | 换型开始 | 生产开始 | 结束 | 生产 | 换型 | 延期 | 说明 |")
        lines.append("|---:|---|---|---|---:|---|---|---|---:|---:|---:|---|")
        for item in [x for x in result.assignments if x.machine_id == machine_id]:
            lines.append(
                "| {seq} | {job} | {fit} | {priority} | {idle:.1f}h | {start} | {production_start} | {end} | {production:.1f}h | {changeover:.1f}h | {late:.1f}h | {reason} |".format(
                    seq=item.sequence_no,
                    job=item.job_id,
                    fit=item.fit_level or "-",
                    priority=(item.priority_reason or "-").replace("|", "/"),
                    idle=item.idle_before_hours,
                    start=item.start_time.strftime("%Y-%m-%d %H:%M"),
                    production_start=item.production_start_time.strftime("%Y-%m-%d %H:%M"),
                    end=item.end_time.strftime("%Y-%m-%d %H:%M"),
                    production=item.production_hours,
                    changeover=item.changeover_hours,
                    late=item.late_hours,
                    reason=item.reason.replace("|", "/"),
                )
            )
        lines.append("")

    lines.append("## 异常清单")
    lines.append("")
    if result.exceptions:
        lines.append("| 订单 | 严重程度 | 原因 | 详情 |")
        lines.append("|---|---|---|---|")
        for item in result.exceptions:
            lines.append(f"| {item.job_id} | {item.severity.value} | {item.reason} | {item.detail or ''} |")
    else:
        lines.append("无未排异常。")
    lines.append("")
    return "\n".join(lines)


def _clean_dict(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: None if pd.isna(value) else value for key, value in raw.items()}


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "是"}


def _as_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        parsed = pd.to_datetime(value)
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()
    except Exception:
        return None
