"""Schedule & Gantt API"""
import subprocess, sys, threading
from fastapi import APIRouter, Depends, HTTPException
from api.deps import get_db
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/api/schedule", tags=["Schedule"])


@router.get("/gantt")
def get_gantt(run_id: int = None, db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    if run_id is None:
        cur.execute("SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return {"tasks": [], "maintenance": [], "downtime": []}
        run_id = row["run_id"]

    cur.execute("""
        SELECT t.order_id, t.machine_id, t.sequence_index,
            t.setup_start_time, t.start_time, t.end_time,
            t.setup_time_mins, t.duration_mins, t.scrap_kg,
            t.is_late, t.tardiness_mins, t.net_weight_kg,
            o.product_type, o.target_width, o.target_thickness,
            o.order_class, o.due_date
        FROM scheduled_tasks t
        JOIN production_orders o ON t.order_id = o.order_id
        WHERE t.run_id = %s
        ORDER BY t.machine_id, t.start_time
    """, (run_id,))
    tasks = []
    for r in cur.fetchall():
        tasks.append({
            "order_id": r["order_id"],
            "machine_id": r["machine_id"],
            "sequence": r["sequence_index"],
            "setup_start": r["setup_start_time"].isoformat() if r["setup_start_time"] else None,
            "start": r["start_time"].isoformat(),
            "end": r["end_time"].isoformat(),
            "setup_mins": r["setup_time_mins"],
            "duration_mins": r["duration_mins"],
            "scrap_kg": float(r["scrap_kg"]),
            "product_type": r["product_type"],
            "target_width": r["target_width"],
            "target_thickness": r["target_thickness"],
            "order_class": r["order_class"],
            "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            "is_late": r["is_late"],
            "tardiness_mins": r["tardiness_mins"],
            "net_weight_kg": r["net_weight_kg"],
        })

    cur.execute("SELECT machine_id, start_time, end_time, reason, maintenance_type FROM machine_maintenance_calendar")
    maintenance = [{"machine_id": r["machine_id"], "start": r["start_time"].isoformat(),
                     "end": r["end_time"].isoformat(), "reason": r["reason"],
                     "type": r["maintenance_type"]} for r in cur.fetchall()]

    cur.execute("SELECT machine_id, start_time, end_time, event_type, severity, root_cause FROM machine_downtime_events")
    downtime = [{"machine_id": r["machine_id"],
                 "start": r["start_time"].isoformat(),
                 "end": r["end_time"].isoformat() if r["end_time"] else None,
                 "type": r["event_type"], "severity": r["severity"],
                 "cause": r["root_cause"]} for r in cur.fetchall()]

    return {"run_id": run_id, "tasks": tasks, "maintenance": maintenance, "downtime": downtime}


@router.get("/runs")
def get_runs(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT run_id, run_time, baseline_time, status, total_orders,
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


@router.post("/trigger")
def trigger_schedule(db=Depends(get_db), user=Depends(require_role("admin", "planner"))):
    """触发新一轮排程（异步执行）"""
    def run_scheduler():
        subprocess.run(
            [sys.executable, "main.py", "--save-db"],
            cwd="d:/devops/BlownFilm Schedule",
            capture_output=True,
        )
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
    return {"message": "排程已触发", "triggered_by": user.username}
