"""Machines API"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_db
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/api/machines", tags=["Machines"])


class MachineUpdate(BaseModel):
    name: Optional[str] = None
    cleanroom_level: Optional[str] = None
    layer_structure: Optional[int] = Field(default=None, gt=0)
    die_diameter_mm: Optional[int] = Field(default=None, gt=0)
    min_width: Optional[int] = Field(default=None, gt=0)
    max_width: Optional[int] = Field(default=None, gt=0)
    min_thickness: Optional[int] = Field(default=None, gt=0)
    max_thickness: Optional[int] = Field(default=None, gt=0)
    hourly_output_kg: Optional[int] = Field(default=None, gt=0)
    max_slitting_lanes: Optional[int] = Field(default=None, gt=0)
    status: Optional[str] = None
    current_width: Optional[int] = Field(default=None, ge=0)
    current_thickness: Optional[int] = Field(default=None, ge=0)
    current_materials: Optional[List[str]] = None


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
            "die_diameter_mm": r["die_diameter_mm"],
            "min_width": r["min_width"],
            "max_width": r["max_width"],
            "min_thickness": r["min_thickness"],
            "max_thickness": r["max_thickness"],
            "hourly_output_kg": r["hourly_output_kg"],
            "max_slitting_lanes": r["max_slitting_lanes"],
            "status": r["status"],
            "current_width": r["current_width"],
            "current_thickness": r["current_thickness"],
            "current_materials": r["current_material_lanes"],
            "last_order_id": r["last_order_id"],
            "continuous_run_mins": r["continuous_run_mins"] or 0,
        })
    return machines


@router.patch("/{machine_id}")
def update_machine(
    machine_id: str,
    payload: MachineUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No machine fields to update.")

    if "status" in fields and fields["status"] not in {"ACTIVE", "MAINTENANCE", "OFFLINE"}:
        raise HTTPException(status_code=400, detail="Invalid machine status.")
    if "cleanroom_level" in fields and fields["cleanroom_level"] not in {"Class_10K", "Class_100K"}:
        raise HTTPException(status_code=400, detail="Invalid cleanroom level.")

    min_width = fields.get("min_width")
    max_width = fields.get("max_width")
    if min_width is not None and max_width is not None and min_width > max_width:
        raise HTTPException(status_code=400, detail="min_width cannot exceed max_width.")
    min_thickness = fields.get("min_thickness")
    max_thickness = fields.get("max_thickness")
    if min_thickness is not None and max_thickness is not None and min_thickness > max_thickness:
        raise HTTPException(status_code=400, detail="min_thickness cannot exceed max_thickness.")

    machine_keys = {
        "name", "cleanroom_level", "layer_structure", "die_diameter_mm",
        "min_width", "max_width", "min_thickness", "max_thickness",
        "hourly_output_kg", "max_slitting_lanes", "status",
    }
    state_key_map = {
        "current_width": "current_width",
        "current_thickness": "current_thickness",
        "current_materials": "current_material_lanes",
    }

    cur = db.cursor()
    if any(k in fields for k in machine_keys):
        assignments = []
        params = []
        for key in sorted(machine_keys.intersection(fields.keys())):
            assignments.append(f"{key}=%s")
            params.append(fields[key])
        assignments.append("updated_at=NOW()")
        params.append(machine_id)
        cur.execute(
            f"UPDATE machines SET {', '.join(assignments)} WHERE machine_id=%s",
            params,
        )
        if cur.rowcount == 0:
            db.rollback()
            raise HTTPException(status_code=404, detail="Machine not found.")

    state_fields = {state_key_map[k]: v for k, v in fields.items() if k in state_key_map}
    if state_fields:
        assignments = []
        params = []
        for key, value in state_fields.items():
            assignments.append(f"{key}=%s")
            params.append(value)
        assignments.append("updated_at=NOW()")
        params.append(machine_id)
        cur.execute(
            f"UPDATE machine_current_state SET {', '.join(assignments)} WHERE machine_id=%s",
            params,
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO machine_current_state
                    (machine_id, current_width, current_thickness, current_material_lanes)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    machine_id,
                    fields.get("current_width", 0),
                    fields.get("current_thickness", 0),
                    fields.get("current_materials", []),
                ),
            )

    db.commit()
    return {"machine_id": machine_id, "updated": sorted(fields.keys())}


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
