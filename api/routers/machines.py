"""Machines API"""
from fastapi import APIRouter, Depends
from api.deps import get_db
from api.auth import get_current_user

router = APIRouter(prefix="/api/machines", tags=["Machines"])


@router.get("")
def list_machines(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT m.*, s.current_material_lanes, s.current_width,
            s.current_thickness, s.current_corona, s.current_core_size,
            s.last_order_id, s.continuous_run_mins, s.last_cleaning_time
        FROM machines m
        LEFT JOIN machine_current_state s ON m.machine_id = s.machine_id
        ORDER BY m.machine_id
    """)
    machines = []
    for r in cur.fetchall():
        machines.append({
            "machine_id": r["machine_id"],
            "name": r["name"],
            "cleanroom_level": r["cleanroom_level"],
            "layer_structure": r["layer_structure"],
            "min_width": r["min_width"],
            "max_width": r["max_width"],
            "hourly_output_kg": r["hourly_output_kg"],
            "status": r["status"],
            "current_width": r["current_width"],
            "current_thickness": r["current_thickness"],
            "current_materials": r["current_material_lanes"],
            "last_order_id": r["last_order_id"],
            "continuous_run_mins": r["continuous_run_mins"] or 0,
        })
    return machines


@router.get("/{machine_id}/timeline")
def get_timeline(machine_id: str, db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    # 排程任务
    cur.execute("""
        SELECT order_id, setup_start_time, start_time, end_time,
            setup_time_mins, duration_mins
        FROM scheduled_tasks
        WHERE machine_id=%s AND run_id=(SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        ORDER BY start_time
    """, (machine_id,))
    tasks = [{"order_id": r["order_id"], "type": "production",
              "start": r["start_time"].isoformat(), "end": r["end_time"].isoformat(),
              "setup_start": r["setup_start_time"].isoformat() if r["setup_start_time"] else None}
             for r in cur.fetchall()]

    # 维保
    cur.execute("SELECT start_time, end_time, reason FROM machine_maintenance_calendar WHERE machine_id=%s", (machine_id,))
    maint = [{"type": "maintenance", "start": r["start_time"].isoformat(),
              "end": r["end_time"].isoformat(), "reason": r["reason"]} for r in cur.fetchall()]

    # 停机
    cur.execute("SELECT start_time, end_time, event_type, severity, root_cause FROM machine_downtime_events WHERE machine_id=%s", (machine_id,))
    down = [{"type": "downtime", "start": r["start_time"].isoformat(),
             "end": r["end_time"].isoformat() if r["end_time"] else None,
             "event": r["event_type"], "severity": r["severity"]} for r in cur.fetchall()]

    return {"machine_id": machine_id, "tasks": tasks, "maintenance": maint, "downtime": down}
