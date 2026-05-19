"""Schedule, run history, and Gantt API."""
from datetime import datetime
import json
import locale
from math import ceil
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user, require_role
from api.deps import get_db
from src.diagnostics import (
    Diagnostic,
    DiagnosticEvidence,
    DiagnosticRecommendation,
    parse_infeasible_log_diagnostics,
)

router = APIRouter(prefix="/api/schedule", tags=["Schedule"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_JOB_LOCK = threading.Lock()
_CURRENT_JOB = {
    "job_id": None,
    "state": "idle",
    "message": "No schedule job has been triggered in this API process.",
    "triggered_by": None,
    "started_at": None,
    "finished_at": None,
    "return_code": None,
    "active_run_id_before": None,
    "active_run_id_after": None,
    "stdout_tail": "",
    "stderr_tail": "",
    "diagnostics": [],
}


def _utc_now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _tail(text: str, limit: int = 6000) -> str:
    text = text or ""
    return text[-limit:]


def _decode_child_output(data: bytes) -> str:
    if not data:
        return ""

    encodings = [
        "utf-8-sig",
        "utf-8",
        "gb18030",
        "gbk",
        "cp936",
        locale.getpreferredencoding(False) or "",
    ]
    seen = set()
    for encoding in encodings:
        if not encoding or encoding in seen:
            continue
        seen.add(encoding)
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _child_env():
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _get_active_run_id():
    from src.database import DatabaseManager

    with DatabaseManager() as manager:
        with manager.conn.cursor() as cur:
            cur.execute(
                "SELECT run_id FROM schedule_runs "
                "WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1"
            )
            row = cur.fetchone()
            return row[0] if row else None


def _snapshot_job():
    with _JOB_LOCK:
        job = dict(_CURRENT_JOB)
    try:
        job["active_run_id"] = _get_active_run_id()
    except Exception as exc:
        job["active_run_id"] = None
        job["status_warning"] = str(exc)
    return job


def _iso(value):
    return value.isoformat() if value else None


def _duration_mins(start, end):
    return max(1, int(round((end - start).total_seconds() / 60)))


def _clip_interval(start, end, horizon_start, horizon_end):
    if not start:
        return None
    if end is None:
        end = horizon_end
    if not end:
        return None
    if horizon_start and horizon_end:
        if end <= horizon_start or start >= horizon_end:
            return None
        start = max(start, horizon_start)
        end = min(end, horizon_end)
    if end <= start:
        return None
    return start, end


def _event_label(event):
    if not event:
        return "scheduled event"
    kind = event.get("kind")
    if kind == "maintenance":
        detail = event.get("type") or event.get("reason") or "planned"
        return f"maintenance window ({detail})"
    if kind == "downtime":
        detail = event.get("event_type") or event.get("severity") or event.get("reason") or "event"
        return f"downtime event ({detail})"
    if kind == "setup":
        return f"setup for {event.get('order_id', 'next order')}"
    if kind == "production":
        return f"order {event.get('order_id', 'production')}"
    return "scheduled event"


def _human_duration(minutes):
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours} 小时 {mins} 分钟" if mins else f"{hours} 小时"


def _event_detail(event):
    if not event:
        return None
    kind = event.get("kind")
    if kind == "maintenance":
        details = []
        if event.get("type"):
            details.append(f"类型={event['type']}")
        if event.get("reason"):
            details.append(f"原因={event['reason']}")
        return "，".join(details) or "计划维护窗口"
    if kind == "downtime":
        details = []
        if event.get("event_type"):
            details.append(f"事件={event['event_type']}")
        if event.get("severity"):
            details.append(f"等级={event['severity']}")
        if event.get("reason"):
            details.append(f"根因={event['reason']}")
        return "，".join(details) or "非计划停机"
    if kind == "production":
        return f"订单={event.get('order_id')}"
    if kind == "setup":
        return f"订单={event.get('order_id')}"
    return None


def _load_idle_order_context(cur, run_id):
    cur.execute("""
        SELECT machine_id, status, cleanroom_level, layer_structure,
            min_width, max_width, min_thickness, max_thickness, hourly_output_kg
        FROM machines
        WHERE status <> 'OFFLINE'
    """)
    machines = {r["machine_id"]: dict(r) for r in cur.fetchall()}

    cur.execute("""
        SELECT o.order_id, o.product_type, o.target_width, o.target_thickness,
            o.total_quantity_kg, o.cleanroom_req, o.order_class, o.due_date,
            o.material_available_time, o.status,
            COALESCE(recipe_layers.layer_count, 1) AS layer_count,
            t.machine_id AS assigned_machine, t.start_time AS assigned_start,
            t.end_time AS assigned_end, t.duration_mins
        FROM production_orders o
        LEFT JOIN (
            SELECT product_type, COUNT(*) AS layer_count
            FROM recipes
            GROUP BY product_type
        ) recipe_layers ON recipe_layers.product_type = o.product_type
        LEFT JOIN scheduled_tasks t
            ON t.order_id = o.order_id AND t.run_id = %s
        WHERE o.status IN ('PENDING', 'SCHEDULED', 'IN_PRODUCTION')
        ORDER BY o.due_date, o.order_id
    """, (run_id,))
    orders = [dict(r) for r in cur.fetchall()]
    return {"machines": machines, "orders": orders}


def _order_machine_blockers(order, machine):
    if not machine:
        return [("machine_missing", "机台主数据缺失")]

    blockers = []
    machine_id = machine.get("machine_id")
    order_id = order.get("order_id")
    status = machine.get("status")
    if status != "ACTIVE":
        blockers.append(("machine_status", f"{machine_id} 状态为 {status}"))

    width = order.get("target_width")
    min_width = machine.get("min_width")
    max_width = machine.get("max_width")
    if width is not None and min_width is not None and max_width is not None:
        if width < min_width or width > max_width:
            blockers.append((
                "width",
                f"{order_id} 幅宽 {width}mm 不在 {machine_id} 的 {min_width}-{max_width}mm 范围内",
            ))

    thickness = order.get("target_thickness")
    min_thickness = machine.get("min_thickness")
    max_thickness = machine.get("max_thickness")
    if thickness is not None and min_thickness is not None and max_thickness is not None:
        if thickness < min_thickness or thickness > max_thickness:
            blockers.append((
                "thickness",
                f"{order_id} 厚度 {thickness}um 不在 {machine_id} 的 {min_thickness}-{max_thickness}um 范围内",
            ))

    if order.get("cleanroom_req") == "Class_10K" and machine.get("cleanroom_level") == "Class_100K":
        blockers.append((
            "cleanroom",
            f"{order_id} 需要 Class_10K，{machine_id} 为 Class_100K",
        ))

    layer_count = int(order.get("layer_count") or 1)
    layer_structure = machine.get("layer_structure")
    if layer_structure is not None and layer_count > int(layer_structure):
        blockers.append((
            "layers",
            f"{order_id} 需要 {layer_count} 层，{machine_id} 只有 {layer_structure} 层",
        ))

    return blockers


def _estimate_order_duration_mins(order, machine):
    if order.get("duration_mins"):
        return int(order["duration_mins"])
    hourly_output = machine.get("hourly_output_kg") or 0
    quantity = order.get("total_quantity_kg") or 0
    if hourly_output <= 0 or quantity <= 0:
        return None
    return max(1, int(ceil(float(quantity) * 60 / float(hourly_output))))


def _order_brief(order):
    parts = [order.get("order_id") or "unknown"]
    if order.get("assigned_machine"):
        parts.append(f"已排 {order['assigned_machine']}")
    if order.get("assigned_start"):
        parts.append(f"开始 {order['assigned_start'].isoformat()}")
    if order.get("material_available_time"):
        parts.append(f"齐套 {order['material_available_time'].isoformat()}")
    return "，".join(parts)


def _top_order_examples(orders, limit=3):
    return "；".join(_order_brief(order) for order in orders[:limit])


def _idle_order_pool_analysis(machine_id, start, end, order_context):
    if not order_context:
        return None

    machine = (order_context.get("machines") or {}).get(machine_id)
    orders = order_context.get("orders") or []
    duration = _duration_mins(start, end)
    base_evidence = [
        DiagnosticEvidence("candidate_order_count", len(orders)),
    ]

    if not machine:
        return {
            "code": "idle.machine_context_missing",
            "confidence": "unknown",
            "severity": "info",
            "root_cause": (
                f"{machine_id} 空闲 {_human_duration(duration)}，但 API 没有读到该机台能力主数据，"
                "无法判断是否有订单可以填补。"
            ),
            "evidence": base_evidence,
        }

    hard_fit_orders = []
    blocker_counts = {}
    blocker_examples = []
    for order in orders:
        blockers = _order_machine_blockers(order, machine)
        if blockers:
            for code, _ in blockers:
                blocker_counts[code] = blocker_counts.get(code, 0) + 1
            if len(blocker_examples) < 3:
                blocker_examples.append(f"{order.get('order_id')}: {blockers[0][1]}")
        else:
            hard_fit_orders.append(order)

    ready_by_start = []
    ready_within_gap = []
    material_after_gap = []
    assigned_elsewhere = []
    pending_unassigned = []
    same_machine_orders = []
    window_too_short = []
    fit_duration_orders = []

    for order in hard_fit_orders:
        material_time = order.get("material_available_time")
        if material_time and material_time > end:
            material_after_gap.append(order)
            continue
        if material_time and material_time > start:
            ready_within_gap.append(order)
        else:
            ready_by_start.append(order)

        estimate = _estimate_order_duration_mins(order, machine)
        if estimate and estimate > duration:
            window_too_short.append((order, estimate))
            continue
        fit_duration_orders.append(order)

        assigned_machine = order.get("assigned_machine")
        if assigned_machine and assigned_machine != machine_id:
            assigned_elsewhere.append(order)
        elif assigned_machine == machine_id:
            same_machine_orders.append(order)
        else:
            pending_unassigned.append(order)

    ready_orders = ready_by_start + ready_within_gap
    evidence = base_evidence + [
        DiagnosticEvidence("hard_fit_order_count", len(hard_fit_orders)),
        DiagnosticEvidence("ready_by_gap_start_count", len(ready_by_start)),
        DiagnosticEvidence("ready_within_gap_count", len(ready_within_gap)),
        DiagnosticEvidence("material_after_gap_count", len(material_after_gap)),
        DiagnosticEvidence("fit_gap_duration_count", len(fit_duration_orders)),
        DiagnosticEvidence("assigned_elsewhere_count", len(assigned_elsewhere)),
        DiagnosticEvidence("pending_unassigned_count", len(pending_unassigned)),
    ]

    if blocker_counts:
        summary = ", ".join(f"{code}={count}" for code, count in sorted(blocker_counts.items()))
        evidence.append(DiagnosticEvidence("hard_fit_blockers", summary))
    if blocker_examples:
        evidence.append(DiagnosticEvidence("blocker_examples", "；".join(blocker_examples)))
    if material_after_gap:
        evidence.append(DiagnosticEvidence("material_wait_examples", _top_order_examples(material_after_gap)))
    if assigned_elsewhere:
        evidence.append(DiagnosticEvidence("assigned_elsewhere_examples", _top_order_examples(assigned_elsewhere)))
    if pending_unassigned:
        evidence.append(DiagnosticEvidence("pending_unassigned_examples", _top_order_examples(pending_unassigned)))
    if same_machine_orders:
        evidence.append(DiagnosticEvidence("same_machine_examples", _top_order_examples(same_machine_orders)))
    if window_too_short:
        shortest = min(window_too_short, key=lambda item: item[1])
        evidence.append(DiagnosticEvidence(
            "shortest_ready_order_duration_mins",
            shortest[1],
            "min",
            entity_id=shortest[0].get("order_id"),
        ))

    recommendations = [
        DiagnosticRecommendation("review_gantt", "查看机台甘特图", f"/gantt?machine={machine_id}"),
        DiagnosticRecommendation("review_orders", "检查订单池", "/config?tab=orders"),
    ]

    if not hard_fit_orders:
        blocker_summary = next((item.actual for item in evidence if item.metric == "hard_fit_blockers"), "未找到可解释阻塞")
        return {
            "code": "idle.no_hard_fit_order",
            "confidence": "proven",
            "severity": "info",
            "root_cause": (
                f"{machine_id} 空闲 {_human_duration(duration)}；当前订单池 {len(orders)} 单中，"
                "没有订单同时满足该机台的幅宽、厚度、洁净度、层数和状态约束。"
                f"主要阻塞：{blocker_summary}。"
            ),
            "evidence": evidence,
            "recommendations": recommendations + [
                DiagnosticRecommendation("review_machine_capacity", "检查机台能力配置", f"/config?tab=machines&machine={machine_id}"),
            ],
        }

    if not ready_orders and material_after_gap:
        first_ready = min(
            material_after_gap,
            key=lambda item: item.get("material_available_time") or end,
        )
        return {
            "code": "idle.material_wait",
            "confidence": "proven",
            "severity": "info",
            "root_cause": (
                f"{machine_id} 有 {len(hard_fit_orders)} 单硬能力可生产，但这些订单在该空档结束前没有齐套；"
                f"最早可用订单是 {_order_brief(first_ready)}。"
            ),
            "evidence": evidence,
            "recommendations": recommendations,
        }

    if ready_orders and not fit_duration_orders and window_too_short:
        shortest = min(window_too_short, key=lambda item: item[1])
        return {
            "code": "idle.window_too_short",
            "confidence": "inferred",
            "severity": "info",
            "root_cause": (
                f"{machine_id} 空闲 {_human_duration(duration)}，但已齐套且硬能力可生产的订单预计生产时间"
                f"至少 {_human_duration(shortest[1])}（{shortest[0].get('order_id')}），空档长度不足。"
            ),
            "evidence": evidence,
            "recommendations": recommendations,
        }

    if assigned_elsewhere and not pending_unassigned:
        return {
            "code": "idle.assigned_elsewhere",
            "confidence": "inferred",
            "severity": "info",
            "root_cause": (
                f"{machine_id} 空闲 {_human_duration(duration)}；有 {len(assigned_elsewhere)} 单在能力和时间上可作为候选，"
                f"但已排到其他机台：{_top_order_examples(assigned_elsewhere)}。"
                "这更像是全局交期/换产目标下的机台选择结果，而不是甘特图缺线。"
            ),
            "evidence": evidence,
            "recommendations": recommendations,
        }

    if pending_unassigned:
        return {
            "code": "idle.pending_unassigned_order",
            "confidence": "inferred",
            "severity": "warning",
            "root_cause": (
                f"{machine_id} 空闲 {_human_duration(duration)}；发现 {len(pending_unassigned)} 单未排产订单"
                f"理论上可落入该机台窗口：{_top_order_examples(pending_unassigned)}。"
                "需要检查订单状态、规则约束或排程结果是否遗漏。"
            ),
            "evidence": evidence,
            "recommendations": recommendations,
        }

    if same_machine_orders:
        return {
            "code": "idle.sequence_positioning",
            "confidence": "inferred",
            "severity": "info",
            "root_cause": (
                f"{machine_id} 空闲 {_human_duration(duration)}；可生产订单已经安排在本机台其他时段"
                f"（{_top_order_examples(same_machine_orders)}），空档更可能来自订单顺序、齐套时间或换产组合。"
            ),
            "evidence": evidence,
            "recommendations": recommendations,
        }

    return {
        "code": "idle.optimization_tradeoff",
        "confidence": "inferred",
        "severity": "info",
        "root_cause": (
            f"{machine_id} 空闲 {_human_duration(duration)}；订单池中有 {len(hard_fit_orders)} 单硬能力可生产、"
            f"{len(ready_orders)} 单在空档结束前齐套，但没有发现可直接填入该窗口的未排订单。"
            "这通常是交期、换产和机台选择的全局优化取舍。"
        ),
        "evidence": evidence,
        "recommendations": recommendations,
    }


def _idle_reason(prev_event, next_event):
    if prev_event is None and next_event is None:
        return "No scheduled work in active run"
    if prev_event is None:
        return f"Idle before {_event_label(next_event)}"
    if next_event is None:
        return f"Idle after {_event_label(prev_event)}"
    if next_event.get("kind") == "maintenance":
        return "Idle before maintenance window"
    if prev_event.get("kind") == "maintenance":
        return "Idle after maintenance window"
    if next_event.get("kind") == "downtime":
        return "Idle before downtime event"
    if prev_event.get("kind") == "downtime":
        return "Idle after downtime event"
    return "Idle gap between scheduled orders"


def _event_guidance(code):
    guidance = {
        "idle.before_maintenance": "该空档由计划维护前等待造成，通常不需要修排程；如需压缩，检查维护窗口。",
        "idle.after_maintenance": "该空档发生在维护后，先确认维护结束时间和后续订单齐套状态。",
        "idle.before_downtime": "该空档靠近停机事件，建议先处理停机原因再重新排程。",
        "idle.after_downtime": "该空档发生在停机恢复后，建议确认设备恢复时间和订单可用性。",
        "idle.no_ready_eligible_order": "没有可证明的就绪订单填补该空档，检查订单池、原料齐套和机台能力。",
        "idle.no_hard_fit_order": "当前订单池没有满足该机台硬能力边界的订单，优先检查订单规格或机台能力配置。",
        "idle.material_wait": "可生产订单受原料齐套时间约束，调整齐套时间或交期后重新排程。",
        "idle.assigned_elsewhere": "候选订单已被排到其他机台，查看同订单在其他机台的交期和换产收益。",
        "idle.window_too_short": "空档长度不足以容纳就绪订单，通常无需强行填补。",
        "idle.pending_unassigned_order": "存在理论可填补的未排订单，优先检查订单状态和规则约束。",
        "idle.sequence_positioning": "订单已在本机其他时段生产，查看齐套时间、交期和换产组合。",
        "idle.machine_context_missing": "缺少机台能力主数据，先补齐配置再判断空档原因。",
        "idle.optimization_tradeoff": "求解器可能为交期或换产目标保留空档，当前只能作为推断。",
        "maintenance.planned_window": "计划维护会占用可排产时间，调整维护窗口后需要重新运行排程。",
        "downtime.unplanned_event": "非计划停机会造成甘特图中断，先处理停机根因再评估排程影响。",
        "lateness.order_late": "订单已逾期，检查交期、原料齐套、机台瓶颈和优先级。",
    }
    return guidance.get(code, "查看证据后修改订单、机台或规则配置，并重新运行排程。")


def _diagnostic_for_idle(
    machine_id,
    start,
    end,
    prev_event,
    next_event,
    reason,
    run_id=None,
    order_context=None,
):
    code = "idle.optimization_tradeoff"
    confidence = "inferred"
    severity = "info"
    recommendations = [
        DiagnosticRecommendation("review_gantt", "查看机台甘特图", f"/gantt?machine={machine_id}"),
        DiagnosticRecommendation("review_orders", "检查订单池", "/config?tab=orders"),
    ]

    if prev_event is None and next_event is None:
        code = "idle.no_ready_eligible_order"
        confidence = "unknown"
    elif next_event and next_event.get("kind") == "maintenance":
        code = "idle.before_maintenance"
        confidence = "proven"
        recommendations = [
            DiagnosticRecommendation("review_maintenance", "检查维护窗口", "/config?tab=maintenance"),
            DiagnosticRecommendation("review_gantt", "查看机台甘特图", f"/gantt?machine={machine_id}"),
        ]
    elif prev_event and prev_event.get("kind") == "maintenance":
        code = "idle.after_maintenance"
        confidence = "proven"
        recommendations = [
            DiagnosticRecommendation("review_maintenance", "检查维护窗口", "/config?tab=maintenance"),
            DiagnosticRecommendation("review_orders", "检查后续订单齐套", "/config?tab=orders"),
        ]
    elif next_event and next_event.get("kind") == "downtime":
        code = "idle.before_downtime"
        confidence = "proven"
        severity = "warning"
        recommendations = [
            DiagnosticRecommendation("review_downtime", "检查停机事件", f"/gantt?machine={machine_id}"),
            DiagnosticRecommendation("review_machine", "检查机台状态", f"/config?tab=machines&machine={machine_id}"),
        ]
    elif prev_event and prev_event.get("kind") == "downtime":
        code = "idle.after_downtime"
        confidence = "proven"
        severity = "warning"
        recommendations = [
            DiagnosticRecommendation("review_downtime", "检查停机恢复", f"/gantt?machine={machine_id}"),
            DiagnosticRecommendation("review_machine", "检查机台状态", f"/config?tab=machines&machine={machine_id}"),
        ]
    elif reason == "Idle gap between scheduled orders":
        code = "idle.optimization_tradeoff"
        confidence = "inferred"

    order_analysis = None
    if code in {"idle.optimization_tradeoff", "idle.no_ready_eligible_order"}:
        order_analysis = _idle_order_pool_analysis(machine_id, start, end, order_context)
        if order_analysis:
            code = order_analysis["code"]
            confidence = order_analysis["confidence"]
            severity = order_analysis["severity"]
            recommendations = order_analysis.get("recommendations") or recommendations

    related_event = {
        "type": "idle",
        "machine_id": machine_id,
        "start": _iso(start),
        "end": _iso(end),
    }
    duration = _duration_mins(start, end)
    prev_label = _event_label(prev_event) if prev_event else "计划域起点"
    next_label = _event_label(next_event) if next_event else "计划域终点"
    prev_detail = _event_detail(prev_event)
    next_detail = _event_detail(next_event)

    if code == "idle.before_downtime":
        root = (
            f"{machine_id} 在 {prev_label} 后空闲 {_human_duration(duration)}，"
            f"直到 {next_label} 开始；{next_detail or '停机事件缺少根因记录'}。"
            "这段是停机前等待/不可安排窗口，不是甘特图漏画。"
        )
    elif code == "idle.after_downtime":
        root = (
            f"{machine_id} 在 {prev_label} 结束后仍空闲 {_human_duration(duration)}，"
            f"后续接到 {next_label}；{prev_detail or '停机事件缺少恢复说明'}。"
        )
    elif code == "idle.before_maintenance":
        root = (
            f"{machine_id} 在 {prev_label} 后空闲 {_human_duration(duration)}，"
            f"等待 {next_label}；{next_detail or '维护窗口未填写原因'}。"
        )
    elif code == "idle.after_maintenance":
        root = (
            f"{machine_id} 在 {prev_label} 后空闲 {_human_duration(duration)}，"
            f"到 {next_label} 才恢复生产；{prev_detail or '维护窗口未填写原因'}。"
        )
    elif code == "idle.no_ready_eligible_order":
        root = (
            f"{machine_id} 在当前计划域内空闲 {_human_duration(duration)}，"
            "没有生产、换产、维护或停机事件可解释；需要结合机台能力和订单池判断是否未被使用。"
        )
    elif order_analysis:
        root = order_analysis["root_cause"]
    else:
        root = (
            f"{machine_id} 在 {prev_label} 与 {next_label} 之间空闲 {_human_duration(duration)}。"
            "当前只能证明这是求解结果中的空档，具体业务原因需要结合订单齐套和机台候选关系继续分析。"
        )

    evidence = [
        DiagnosticEvidence("idle_duration_mins", duration, "min"),
        DiagnosticEvidence("previous_event", prev_label),
        DiagnosticEvidence("previous_event_detail", prev_detail),
        DiagnosticEvidence("next_event", next_label),
        DiagnosticEvidence("next_event_detail", next_detail),
    ]
    if order_analysis:
        evidence.extend(order_analysis.get("evidence", []))

    return Diagnostic(
        entity_type="event",
        entity_id=f"{machine_id}:{_iso(start)}:{_iso(end)}",
        severity=severity,
        category="idle",
        code=code,
        confidence=confidence,
        root_cause=root,
        evidence=evidence,
        recommendations=recommendations,
        related_event=related_event,
        display_title=f"{machine_id} 空档 {_human_duration(duration)}",
    ).to_dict(run_id)


def _event_diagnostic(kind, machine_id, start, end, code, root_cause, evidence=None, severity="info", run_id=None):
    related_event = {
        "type": kind,
        "machine_id": machine_id,
        "start": _iso(start),
        "end": _iso(end),
    }
    recommendations = [
        DiagnosticRecommendation("review_gantt", "查看机台甘特图", f"/gantt?machine={machine_id}"),
    ]
    if kind == "maintenance":
        recommendations.append(DiagnosticRecommendation(
            "review_maintenance",
            "检查维护窗口",
            "/config?tab=maintenance",
        ))
    if kind == "downtime":
        recommendations.append(DiagnosticRecommendation(
            "review_machine",
            "检查机台状态",
            f"/config?tab=machines&machine={machine_id}",
        ))

    return Diagnostic(
        entity_type="event",
        entity_id=f"{machine_id}:{kind}:{_iso(start)}",
        severity=severity,
        category="maintenance" if kind == "maintenance" else "downtime",
        code=code,
        confidence="proven",
        root_cause=root_cause,
        evidence=evidence or [],
        recommendations=recommendations,
        related_event=related_event,
    ).to_dict(run_id)


def _lateness_event_diagnostic(row, run_id):
    tardiness = row["tardiness_mins"] or 0
    duration = row["duration_mins"] or 0
    setup_mins = row["setup_time_mins"] or 0
    material_time = row.get("material_available_time")
    due_date = row.get("due_date")
    order_date = row.get("order_date")

    if material_time and due_date and material_time > due_date:
        code = "material.not_available"
        category = "material"
        confidence = "proven"
        root = (
            f"订单 {row['order_id']} 的原料齐套时间 {material_time.isoformat()} "
            f"晚于交期 {due_date.isoformat()}，因此该订单在当前数据下必然逾期。"
        )
    elif material_time and row["start_time"] and material_time > row["start_time"]:
        code = "lateness.material_wait"
        category = "lateness"
        confidence = "proven"
        root = (
            f"订单 {row['order_id']} 受原料齐套约束，原料到齐时间为 {material_time.isoformat()}，"
            f"压缩了可排产窗口。"
        )
    elif setup_mins >= max(60, int(duration * 0.25)):
        code = "lateness.setup_burden"
        category = "lateness"
        confidence = "inferred"
        root = (
            f"订单 {row['order_id']} 在 {row['machine_id']} 上前置换产 {setup_mins} 分钟，"
            f"生产本体 {duration} 分钟，换产占生产时长 {round(setup_mins / max(1, duration) * 100, 1)}%。"
        )
    elif order_date and due_date and _duration_mins(order_date, due_date) < duration + setup_mins:
        code = "lateness.due_too_tight"
        category = "lateness"
        confidence = "proven"
        root = (
            f"订单 {row['order_id']} 从下单到交期只有 {_duration_mins(order_date, due_date)} 分钟，"
            f"小于生产 {duration} 分钟 + 换产 {setup_mins} 分钟。"
        )
    else:
        code = "lateness.machine_bottleneck"
        category = "lateness"
        confidence = "inferred"
        root = (
            f"订单 {row['order_id']} 分配到 {row['machine_id']} 后逾期 {tardiness} 分钟；"
            "未发现原料晚于交期或单笔换产主因，优先检查该机台负载和同机台前后订单竞争。"
        )

    return Diagnostic(
        entity_type="order",
        entity_id=row["order_id"],
        severity="warning",
        category=category,
        code=code,
        confidence=confidence,
        root_cause=root,
        evidence=[
            DiagnosticEvidence("tardiness_mins", tardiness, "min"),
            DiagnosticEvidence("machine_id", row["machine_id"]),
            DiagnosticEvidence("setup_time_mins", setup_mins, "min"),
            DiagnosticEvidence("duration_mins", duration, "min"),
            DiagnosticEvidence("prev_order_id", row.get("prev_order_id")),
            DiagnosticEvidence("due_date", _iso(due_date)),
            DiagnosticEvidence("material_available_time", _iso(material_time)),
        ],
        recommendations=[
            DiagnosticRecommendation(
                "review_order",
                "检查订单交期、等级和原料齐套",
                f"/config?tab=orders&order={row['order_id']}",
            ),
            DiagnosticRecommendation(
                "review_machine_sequence",
                "查看该机台前后订单",
                f"/gantt?machine={row['machine_id']}",
            ),
        ],
        related_event={
            "type": "production",
            "machine_id": row["machine_id"],
            "start": _iso(row["start_time"]),
            "end": _iso(row["end_time"]),
        },
        display_title=f"{row['order_id']} 逾期 {_human_duration(tardiness)}",
    ).to_dict(run_id)


def _build_idle_windows(
    machine_ids,
    horizon_start,
    horizon_end,
    tasks,
    maintenance,
    downtime,
    run_id=None,
    order_context=None,
):
    if not horizon_start or not horizon_end or horizon_end <= horizon_start:
        return []

    events_by_machine = {machine_id: [] for machine_id in machine_ids}

    def add_event(machine_id, start, end, kind, **extra):
        clipped = _clip_interval(start, end, horizon_start, horizon_end)
        if not clipped:
            return
        start_dt, end_dt = clipped
        events_by_machine.setdefault(machine_id, []).append({
            "machine_id": machine_id,
            "start": start_dt,
            "end": end_dt,
            "kind": kind,
            **extra,
        })

    for task in tasks:
        machine_id = task["machine_id"]
        if task["setup_start_time"] and task["setup_start_time"] < task["start_time"]:
            add_event(
                machine_id,
                task["setup_start_time"],
                task["start_time"],
                "setup",
                order_id=task["order_id"],
            )
        add_event(
            machine_id,
            task["start_time"],
            task["end_time"],
            "production",
            order_id=task["order_id"],
        )

    for item in maintenance:
        add_event(
            item["machine_id"],
            item["start"],
            item["end"],
            "maintenance",
            reason=item.get("reason"),
            type=item.get("type"),
        )

    for item in downtime:
        add_event(
            item["machine_id"],
            item["start"],
            item["end"],
            "downtime",
            reason=item.get("cause"),
            event_type=item.get("event_type") or item.get("type"),
            severity=item.get("severity"),
        )

    idle = []
    for machine_id in machine_ids:
        events = sorted(
            events_by_machine.get(machine_id, []),
            key=lambda item: (item["start"], item["end"]),
        )
        cursor = horizon_start
        prev_event = None

        for event in events:
            if event["start"] > cursor:
                reason = _idle_reason(prev_event, event)
                diagnostic = _diagnostic_for_idle(
                    machine_id,
                    cursor,
                    event["start"],
                    prev_event,
                    event,
                    reason,
                    run_id,
                    order_context,
                )
                idle.append({
                    "machine_id": machine_id,
                    "start": _iso(cursor),
                    "end": _iso(event["start"]),
                    "duration_mins": _duration_mins(cursor, event["start"]),
                    "reason": reason,
                    "previous_event": _event_label(prev_event) if prev_event else None,
                    "next_event": _event_label(event),
                    "diagnostic_id": diagnostic["id"],
                    "diagnostic": diagnostic,
                    "guidance": _event_guidance(diagnostic["code"]),
                    "confidence": diagnostic["confidence"],
                    "code": diagnostic["code"],
                })
            if event["end"] > cursor:
                cursor = event["end"]
                prev_event = event

        if cursor < horizon_end:
            reason = _idle_reason(prev_event, None)
            diagnostic = _diagnostic_for_idle(
                machine_id,
                cursor,
                horizon_end,
                prev_event,
                None,
                reason,
                run_id,
                order_context,
            )
            idle.append({
                "machine_id": machine_id,
                "start": _iso(cursor),
                "end": _iso(horizon_end),
                "duration_mins": _duration_mins(cursor, horizon_end),
                "reason": reason,
                "previous_event": _event_label(prev_event) if prev_event else None,
                "next_event": None,
                "diagnostic_id": diagnostic["id"],
                "diagnostic": diagnostic,
                "guidance": _event_guidance(diagnostic["code"]),
                "confidence": diagnostic["confidence"],
                "code": diagnostic["code"],
            })

    return idle


@router.get("/gantt")
def get_gantt(run_id: int = None, db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("SELECT machine_id, name, status FROM machines WHERE status <> 'OFFLINE' ORDER BY machine_id")
    machines = [dict(r) for r in cur.fetchall()]
    machine_ids = [m["machine_id"] for m in machines]

    if run_id is None:
        cur.execute(
            "SELECT run_id FROM schedule_runs "
            "WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return {
                "run_id": None,
                "horizon": None,
                "machines": machines,
                "tasks": [],
                "maintenance": [],
                "downtime": [],
                "idle": [],
            }
        run_id = row["run_id"]

    cur.execute("""
        SELECT t.order_id, t.machine_id, t.sequence_index,
            t.setup_start_time, t.start_time, t.end_time,
            t.setup_time_mins, t.duration_mins, t.scrap_kg,
            t.is_late, t.tardiness_mins, t.net_weight_kg,
            o.product_type, o.target_width, o.target_thickness,
            o.order_class, o.order_date, o.due_date,
            o.material_available_time, t.prev_order_id
        FROM scheduled_tasks t
        JOIN production_orders o ON t.order_id = o.order_id
        WHERE t.run_id = %s
        ORDER BY t.machine_id, t.start_time
    """, (run_id,))
    task_rows = cur.fetchall()

    horizon_points = []
    for r in task_rows:
        horizon_points.append(r["setup_start_time"] or r["start_time"])
        horizon_points.append(r["end_time"])
    horizon_start = min(horizon_points) if horizon_points else None
    horizon_end = max(horizon_points) if horizon_points else None

    tasks = []
    for r in task_rows:
        if r["machine_id"] not in machine_ids:
            machine_ids.append(r["machine_id"])
        task_event = {
            "kind": "production",
            "order_id": r["order_id"],
            "machine_id": r["machine_id"],
            "sequence": r["sequence_index"],
            "setup_start": _iso(r["setup_start_time"]),
            "start": _iso(r["start_time"]),
            "end": _iso(r["end_time"]),
            "setup_mins": r["setup_time_mins"],
            "duration_mins": r["duration_mins"],
            "scrap_kg": float(r["scrap_kg"]),
            "product_type": r["product_type"],
            "target_width": r["target_width"],
            "target_thickness": r["target_thickness"],
            "order_class": r["order_class"],
            "due_date": _iso(r["due_date"]),
            "is_late": r["is_late"],
            "tardiness_mins": r["tardiness_mins"],
            "net_weight_kg": r["net_weight_kg"],
        }
        if r["is_late"]:
            diagnostic = _lateness_event_diagnostic(r, run_id)
            task_event["diagnostics"] = [diagnostic]
            task_event["diagnostic_ids"] = [diagnostic["id"]]
            task_event["guidance"] = _event_guidance(diagnostic["code"])
        tasks.append(task_event)

    cur.execute(
        "SELECT machine_id, start_time, end_time, reason, maintenance_type "
        "FROM machine_maintenance_calendar ORDER BY machine_id, start_time"
    )
    maintenance = []
    maintenance_events = []
    for r in cur.fetchall():
        clipped = _clip_interval(r["start_time"], r["end_time"], horizon_start, horizon_end)
        if horizon_start and horizon_end and not clipped:
            continue
        start_dt, end_dt = clipped or (r["start_time"], r["end_time"])
        if r["machine_id"] not in machine_ids:
            machine_ids.append(r["machine_id"])
        event = {
            "machine_id": r["machine_id"],
            "start": _iso(start_dt),
            "end": _iso(end_dt),
            "reason": r["reason"],
            "type": r["maintenance_type"],
            "duration_mins": _duration_mins(start_dt, end_dt),
        }
        diagnostic = _event_diagnostic(
            "maintenance",
            r["machine_id"],
            start_dt,
            end_dt,
            "maintenance.planned_window",
            (
                f"{r['machine_id']} 存在计划维护窗口"
                f"（{r['maintenance_type'] or 'ROUTINE'}），会占用可排产时间。"
            ),
            [
                DiagnosticEvidence("duration_mins", event["duration_mins"], "min"),
                DiagnosticEvidence("maintenance_type", r["maintenance_type"]),
                DiagnosticEvidence("reason", r["reason"]),
            ],
            run_id=run_id,
        )
        event["diagnostic"] = diagnostic
        event["diagnostic_id"] = diagnostic["id"]
        event["guidance"] = _event_guidance(diagnostic["code"])
        maintenance.append(event)
        maintenance_events.append({
            "machine_id": r["machine_id"],
            "start": start_dt,
            "end": end_dt,
            "reason": r["reason"],
            "type": r["maintenance_type"],
        })

    idle_order_context = _load_idle_order_context(cur, run_id)

    cur.execute(
        "SELECT machine_id, start_time, end_time, event_type, severity, root_cause "
        "FROM machine_downtime_events ORDER BY machine_id, start_time"
    )
    downtime = []
    downtime_events = []
    for r in cur.fetchall():
        clipped = _clip_interval(r["start_time"], r["end_time"], horizon_start, horizon_end)
        if horizon_start and horizon_end and not clipped:
            continue
        if not clipped:
            continue
        start_dt, end_dt = clipped
        if r["machine_id"] not in machine_ids:
            machine_ids.append(r["machine_id"])
        event = {
            "machine_id": r["machine_id"],
            "start": _iso(start_dt),
            "end": _iso(end_dt),
            "type": r["event_type"],
            "severity": r["severity"],
            "cause": r["root_cause"],
            "duration_mins": _duration_mins(start_dt, end_dt),
        }
        diagnostic = _event_diagnostic(
            "downtime",
            r["machine_id"],
            start_dt,
            end_dt,
            "downtime.unplanned_event",
            (
                f"{r['machine_id']} 存在非计划停机"
                f"（{r['event_type'] or 'OTHER'}），会造成产能中断。"
            ),
            [
                DiagnosticEvidence("duration_mins", event["duration_mins"], "min"),
                DiagnosticEvidence("severity", r["severity"]),
                DiagnosticEvidence("root_cause", r["root_cause"]),
            ],
            severity="warning" if r["severity"] in {"CRITICAL", "DEGRADED"} else "info",
            run_id=run_id,
        )
        event["diagnostic"] = diagnostic
        event["diagnostic_id"] = diagnostic["id"]
        event["guidance"] = _event_guidance(diagnostic["code"])
        downtime.append(event)
        downtime_events.append({
            "machine_id": r["machine_id"],
            "start": start_dt,
            "end": end_dt,
            "cause": r["root_cause"],
            "event_type": r["event_type"],
            "severity": r["severity"],
        })

    idle = _build_idle_windows(
        machine_ids,
        horizon_start,
        horizon_end,
        task_rows,
        maintenance_events,
        downtime_events,
        run_id=run_id,
        order_context=idle_order_context,
    )

    return {
        "run_id": run_id,
        "horizon": {
            "start": _iso(horizon_start),
            "end": _iso(horizon_end),
        } if horizon_start and horizon_end else None,
        "machines": machines,
        "tasks": tasks,
        "maintenance": maintenance,
        "downtime": downtime,
        "idle": idle,
    }


def _normalize_solver_params(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _load_persisted_diagnostics(cur, run_id):
    cur.execute("SELECT solver_params FROM schedule_runs WHERE run_id=%s", (run_id,))
    row = cur.fetchone()
    params = _normalize_solver_params(row["solver_params"] if row else None)
    diagnostics = params.get("diagnostics") or []
    normalized = []
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        next_item = dict(item)
        next_item["run_id"] = next_item.get("run_id") or run_id
        normalized.append(next_item)
    return normalized


def _collect_event_diagnostics(gantt_payload):
    items = []
    for event_group in ("tasks", "maintenance", "downtime", "idle"):
        for event in gantt_payload.get(event_group, []) or []:
            if isinstance(event.get("diagnostic"), dict):
                items.append(event["diagnostic"])
            for diagnostic in event.get("diagnostics") or []:
                if isinstance(diagnostic, dict):
                    items.append(diagnostic)
    return items


def _dedupe_diagnostics(items):
    seen = set()
    result = []
    for item in items:
        diag_id = item.get("id")
        if diag_id and diag_id in seen:
            continue
        if diag_id:
            seen.add(diag_id)
        result.append(item)
    return result


def _filter_diagnostics(items, entity_type=None, entity_id=None, severity=None, category=None):
    filtered = []
    for item in items:
        if entity_type and item.get("entity_type") != entity_type:
            continue
        if entity_id and item.get("entity_id") != entity_id:
            continue
        if severity and item.get("severity") != severity:
            continue
        if category and item.get("category") != category:
            continue
        filtered.append(item)
    return filtered


def _diagnostic_counts(items):
    counts = {"total": len(items), "severity": {}, "category": {}}
    for item in items:
        sev = item.get("severity") or "info"
        cat = item.get("category") or "unknown"
        counts["severity"][sev] = counts["severity"].get(sev, 0) + 1
        counts["category"][cat] = counts["category"].get(cat, 0) + 1
    return counts


@router.get("/diagnostics")
def get_schedule_diagnostics(
    run_id: int = None,
    entity_type: str = None,
    entity_id: str = None,
    severity: str = None,
    category: str = None,
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    cur = db.cursor()
    if run_id is None:
        cur.execute(
            "SELECT run_id FROM schedule_runs "
            "WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if not row:
            return {"run_id": None, "diagnostics": [], "counts": _diagnostic_counts([])}
        run_id = row["run_id"]

    persisted = _load_persisted_diagnostics(cur, run_id)
    gantt_payload = get_gantt(run_id=run_id, db=db, _=_)
    event_items = _collect_event_diagnostics(gantt_payload)
    diagnostics = _dedupe_diagnostics(persisted + event_items)
    diagnostics = _filter_diagnostics(
        diagnostics,
        entity_type=entity_type,
        entity_id=entity_id,
        severity=severity,
        category=category,
    )
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    diagnostics.sort(key=lambda item: (
        severity_order.get(item.get("severity"), 9),
        item.get("category") or "",
        item.get("entity_id") or "",
    ))
    return {
        "run_id": run_id,
        "diagnostics": diagnostics,
        "counts": _diagnostic_counts(diagnostics),
    }


@router.get("/runs")
def get_runs(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT run_id, run_time, baseline_time, triggered_by, status, total_orders,
            total_machines_used, phase1_tardiness_score, phase2_setup_score,
            total_setup_time_mins, total_scrap_kg, total_late_orders,
            vip_late_orders, is_active
        FROM schedule_runs ORDER BY run_id DESC LIMIT 20
    """)
    runs = []
    for r in cur.fetchall():
        runs.append({
            "run_id": r["run_id"],
            "run_time": r["run_time"].isoformat() if r["run_time"] else None,
            "triggered_by": r["triggered_by"],
            "status": r["status"],
            "total_orders": r["total_orders"],
            "phase1_score": r["phase1_tardiness_score"],
            "phase2_score": r["phase2_setup_score"],
            "total_setup_mins": r["total_setup_time_mins"],
            "total_scrap_kg": float(r["total_scrap_kg"] or 0),
            "late_orders": r["total_late_orders"],
            "is_active": r["is_active"],
        })
    return runs


@router.get("/status")
def get_schedule_status(_=Depends(get_current_user)):
    return _snapshot_job()


@router.post("/trigger")
def trigger_schedule(user=Depends(require_role("admin", "planner"))):
    with _JOB_LOCK:
        if _CURRENT_JOB.get("state") == "running":
            raise HTTPException(status_code=409, detail="A schedule job is already running.")

        active_run_id_before = _get_active_run_id()
        job_id = uuid.uuid4().hex[:12]
        _CURRENT_JOB.update({
            "job_id": job_id,
            "state": "running",
            "message": "Schedule job is running.",
            "triggered_by": user.username,
            "started_at": _utc_now_iso(),
            "finished_at": None,
            "return_code": None,
            "active_run_id_before": active_run_id_before,
            "active_run_id_after": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "diagnostics": [],
        })

    def run_scheduler(current_job_id: str, username: str, previous_run_id: int | None):
        try:
            completed = subprocess.run(
                [
                    sys.executable, "main.py", "--save-db",
                    "--source", "db", "--triggered-by", username,
                ],
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=False,
                env=_child_env(),
            )
            stdout_text = _decode_child_output(completed.stdout)
            stderr_text = _decode_child_output(completed.stderr)
            try:
                active_run_id_after = _get_active_run_id()
            except Exception:
                active_run_id_after = None

            succeeded = completed.returncode == 0 and active_run_id_after != previous_run_id
            diagnostics = []
            if not succeeded:
                diagnostics = parse_infeasible_log_diagnostics(
                    "\n".join([stderr_text, stdout_text])
                )
            update = {
                "state": "succeeded" if succeeded else "failed",
                "message": (
                    "Schedule job completed and published a new active run."
                    if succeeded
                    else "Schedule job finished without publishing a new active run."
                ),
                "finished_at": _utc_now_iso(),
                "return_code": completed.returncode,
                "active_run_id_after": active_run_id_after,
                "stdout_tail": _tail(stdout_text),
                "stderr_tail": _tail(stderr_text),
                "diagnostics": diagnostics,
            }
        except Exception as exc:
            update = {
                "state": "failed",
                "message": str(exc),
                "finished_at": _utc_now_iso(),
                "return_code": None,
                "active_run_id_after": None,
                "stdout_tail": "",
                "stderr_tail": "",
                "diagnostics": [],
            }

        with _JOB_LOCK:
            if _CURRENT_JOB.get("job_id") == current_job_id:
                _CURRENT_JOB.update(update)

    t = threading.Thread(
        target=run_scheduler,
        args=(job_id, user.username, active_run_id_before),
        daemon=True,
    )
    t.start()
    return _snapshot_job()
