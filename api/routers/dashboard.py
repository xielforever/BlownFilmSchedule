"""Dashboard API"""
import json

from fastapi import APIRouter, Depends
from api.deps import get_db
from api.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


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


def _schedule_summary_counts(run):
    params = _normalize_solver_params(run.get("solver_params"))
    summary = params.get("summary") if isinstance(params.get("summary"), dict) else {}
    scheduled_count = run["total_orders"] or 0
    schedulable_count = summary.get("schedulable_order_count", scheduled_count)
    input_count = summary.get("input_order_count", schedulable_count)
    blocked_count = summary.get("blocked_order_count", max(0, input_count - schedulable_count))
    return {
        "input_order_count": input_count,
        "scheduled_order_count": scheduled_count,
        "schedulable_order_count": schedulable_count,
        "blocked_order_count": blocked_count,
    }


@router.get("/summary")
def get_summary(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("SELECT * FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1")
    run = cur.fetchone()
    if not run:
        return {"total_orders": 0, "on_time_rate": 0, "total_scrap_kg": 0, "avg_utilization": 0, "late_orders": []}

    cur.execute("""
        SELECT order_id, machine_id, tardiness_mins
        FROM scheduled_tasks WHERE run_id=%s AND is_late=TRUE
    """, (run["run_id"],))
    late = cur.fetchall()

    cur.execute("""
        SELECT machine_id,
            SUM(duration_mins) AS prod,
            MAX(end_mins) - MIN(start_mins) AS span
        FROM scheduled_tasks WHERE run_id=%s
        GROUP BY machine_id
    """, (run["run_id"],))
    utils = cur.fetchall()
    avg_util = 0
    if utils:
        rates = [r["prod"] / r["span"] * 100 if r["span"] > 0 else 0 for r in utils]
        avg_util = round(sum(rates) / len(rates), 1)

    counts = _schedule_summary_counts(run)
    on_time = round((run["total_orders"] - run["total_late_orders"]) / run["total_orders"] * 100, 1) if run["total_orders"] else 0
    return {
        "total_orders": run["total_orders"],
        **counts,
        "on_time_rate": on_time,
        "total_scrap_kg": float(run["total_scrap_kg"] or 0),
        "total_setup_mins": run["total_setup_time_mins"],
        "avg_utilization": avg_util,
        "phase1_score": run["phase1_tardiness_score"],
        "phase2_score": run["phase2_setup_score"],
        "status": run["status"],
        "run_id": run["run_id"],
        "run_time": run["run_time"].isoformat() if run["run_time"] else None,
        "triggered_by": run["triggered_by"],
        "late_orders": [dict(r) for r in late],
    }


@router.get("/utilization-heatmap")
def get_utilization_heatmap(days: int = 7, db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("SELECT * FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1")
    run = cur.fetchone()
    if not run:
        return {"days": [], "machines": [], "values": []}

    cur.execute("""
        SELECT machine_id, start_time::date AS day,
            SUM(duration_mins) AS prod_mins
        FROM scheduled_tasks WHERE run_id=%s
        GROUP BY machine_id, start_time::date
        ORDER BY day, machine_id
    """, (run["run_id"],))
    rows = cur.fetchall()

    days_set = sorted(set(r["day"].isoformat() for r in rows))[:days]
    machines = sorted(set(r["machine_id"] for r in rows))
    lookup = {(r["machine_id"], r["day"].isoformat()): float(r["prod_mins"]) for r in rows}

    values = []
    for mi, m in enumerate(machines):
        for di, d in enumerate(days_set):
            prod = lookup.get((m, d), 0)
            values.append([di, mi, round(prod / 1440 * 100, 1)])

    return {"days": days_set, "machines": machines, "values": values}
