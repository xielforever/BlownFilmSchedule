"""Machines API"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_db
from api.auth import get_current_user, require_role
from api.routers.orders import _mark_order_screening_cache_stale
from src.config import MANDATORY_CLEANING_DURATION_MINUTES

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
    current_corona: Optional[bool] = None
    current_core_size: Optional[int] = Field(default=None, ge=0)


def _continuous_run_mins_after_schedule(initial_mins, tasks):
    ordered = sorted(
        tasks,
        key=lambda item: (
            item.get("setup_start_time") or item.get("start_time"),
            item.get("end_time"),
        ),
    )
    if not ordered:
        return max(0, int(initial_mins or 0))

    segment_anchor = None
    segment_initial = max(0, int(initial_mins or 0))
    last_end = None
    elapsed = segment_initial
    for task in ordered:
        setup_start = task.get("setup_start_time") or task.get("start_time")
        end_time = task.get("end_time")
        if not setup_start or not end_time:
            continue
        if segment_anchor is None:
            segment_anchor = setup_start
        elif last_end is not None:
            gap_mins = int((setup_start - last_end).total_seconds() / 60)
            if gap_mins >= MANDATORY_CLEANING_DURATION_MINUTES:
                segment_anchor = setup_start
                segment_initial = 0

        elapsed = segment_initial + int((end_time - segment_anchor).total_seconds() / 60)
        last_end = end_time
    return max(0, elapsed)


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
            "current_corona": r["current_corona"],
            "current_core_size": r["current_core_size"],
            "last_order_id": r["last_order_id"],
            "continuous_run_mins": r["continuous_run_mins"] or 0,
        })
    return machines


@router.post("/apply-schedule-end-state")
def apply_schedule_end_state(
    run_id: Optional[int] = None,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    cur = db.cursor()
    if run_id is None:
        cur.execute(
            "SELECT run_id FROM schedule_runs "
            "WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1"
        )
    else:
        cur.execute("SELECT run_id FROM schedule_runs WHERE run_id=%s", (run_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule run not found.")

    resolved_run_id = row["run_id"]
    cur.execute("""
        SELECT machine_id, COALESCE(continuous_run_mins, 0) AS continuous_run_mins,
            last_order_id
        FROM machine_current_state
    """)
    previous_state = {r["machine_id"]: dict(r) for r in cur.fetchall()}
    cur.execute("""
        WITH recipe_materials AS (
            SELECT product_type, ARRAY_AGG(material_grade ORDER BY layer) AS materials
            FROM recipes
            GROUP BY product_type
        ),
        latest_task AS (
            SELECT DISTINCT ON (t.machine_id)
                t.machine_id,
                t.order_id,
                o.product_type,
                o.target_width,
                o.target_thickness,
                o.corona_req,
                o.core_size_inch
            FROM scheduled_tasks t
            JOIN production_orders o ON o.order_id = t.order_id
            WHERE t.run_id = %s
            ORDER BY t.machine_id, t.end_time DESC, t.id DESC
        ),
        state_rows AS (
            SELECT
                lt.machine_id,
                COALESCE(rm.materials, s.current_material_lanes, ARRAY[]::TEXT[]) AS current_material_lanes,
                lt.target_width AS current_width,
                lt.target_thickness AS current_thickness,
                lt.corona_req AS current_corona,
                COALESCE(lt.core_size_inch, 3) AS current_core_size,
                lt.order_id AS last_order_id
            FROM latest_task lt
            LEFT JOIN recipe_materials rm ON rm.product_type = lt.product_type
            LEFT JOIN machine_current_state s ON s.machine_id = lt.machine_id
        )
        INSERT INTO machine_current_state
            (machine_id, current_material_lanes, current_width,
             current_thickness, current_corona, current_core_size, last_order_id)
        SELECT
            machine_id, current_material_lanes, current_width,
            current_thickness, current_corona, current_core_size, last_order_id
        FROM state_rows
        ON CONFLICT (machine_id) DO UPDATE SET
            current_material_lanes=EXCLUDED.current_material_lanes,
            current_width=EXCLUDED.current_width,
            current_thickness=EXCLUDED.current_thickness,
            current_corona=EXCLUDED.current_corona,
            current_core_size=EXCLUDED.current_core_size,
            last_order_id=EXCLUDED.last_order_id,
            updated_at=NOW()
        RETURNING machine_id, current_material_lanes, current_width,
            current_thickness, current_corona, current_core_size, last_order_id
    """, (resolved_run_id,))
    rows = cur.fetchall()
    state_rows = [dict(r) for r in rows]
    cur.execute("""
        SELECT t.machine_id, t.setup_start_time, t.start_time, t.end_time
        FROM scheduled_tasks t
        WHERE t.run_id=%s
        ORDER BY t.machine_id, t.start_time, t.id
    """, (resolved_run_id,))
    tasks_by_machine = {}
    for task in cur.fetchall():
        machine_id = task["machine_id"]
        tasks_by_machine.setdefault(machine_id, []).append(task)

    continuous_by_machine = {}
    for row in state_rows:
        machine_id = row["machine_id"]
        previous = previous_state.get(machine_id, {})
        if previous.get("last_order_id") == row["last_order_id"]:
            continuous_by_machine[machine_id] = previous.get("continuous_run_mins", 0)
            continue
        continuous_by_machine[machine_id] = _continuous_run_mins_after_schedule(
            previous.get("continuous_run_mins", 0),
            tasks_by_machine.get(machine_id, []),
        )
    for machine_id, continuous_run_mins in continuous_by_machine.items():
        cur.execute(
            """
            UPDATE machine_current_state
            SET continuous_run_mins=%s, updated_at=NOW()
            WHERE machine_id=%s
            """,
            (continuous_run_mins, machine_id),
        )
    for row in state_rows:
        row["continuous_run_mins"] = continuous_by_machine.get(row["machine_id"], 0)
    db.commit()
    return {
        "run_id": resolved_run_id,
        "applied_count": len(state_rows),
        "machines": state_rows,
    }


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
        "current_corona": "current_corona",
        "current_core_size": "current_core_size",
    }

    cur = db.cursor()
    machine_table_changed = any(k in fields for k in machine_keys)
    if machine_table_changed:
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
        _mark_order_screening_cache_stale(cur, reason="machine_capability_changed")

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
                    (machine_id, current_width, current_thickness,
                     current_material_lanes, current_corona, current_core_size)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    machine_id,
                    fields.get("current_width", 0),
                    fields.get("current_thickness", 0),
                    fields.get("current_materials", []),
                    fields.get("current_corona", False),
                    fields.get("current_core_size", 3),
                ),
            )
        if not machine_table_changed:
            _mark_order_screening_cache_stale(cur, reason="machine_state_changed")

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
    cur.execute("""
        SELECT start_time, end_time, reason
        FROM (
            SELECT DISTINCT ON (
                machine_id, start_time, end_time, maintenance_type,
                COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                COALESCE(recurrence_rule, '')
            )
                machine_id, start_time, end_time, reason
            FROM machine_maintenance_calendar
            WHERE machine_id=%s
            ORDER BY
                machine_id, start_time, end_time, maintenance_type,
                COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                COALESCE(recurrence_rule, ''), id
        ) deduped
        ORDER BY start_time
    """, (machine_id,))
    maint = [{"type": "maintenance", "start": r["start_time"].isoformat(),
              "end": r["end_time"].isoformat(), "reason": r["reason"]} for r in cur.fetchall()]

    # 停机
    cur.execute("SELECT start_time, end_time, event_type, severity, root_cause FROM machine_downtime_events WHERE machine_id=%s", (machine_id,))
    down = [{"type": "downtime", "start": r["start_time"].isoformat(),
             "end": r["end_time"].isoformat() if r["end_time"] else None,
             "event": r["event_type"], "severity": r["severity"]} for r in cur.fetchall()]

    return {"machine_id": machine_id, "tasks": tasks, "maintenance": maint, "downtime": down}
