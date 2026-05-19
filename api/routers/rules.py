"""Configurable scheduling constraints and setup rules."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_role
from api.deps import get_db

router = APIRouter(prefix="/api/rules", tags=["Rules"])


class MaterialSwitchRule(BaseModel):
    from_material: str
    to_material: str
    switch_time_mins: int = Field(gt=0)
    scrap_weight_kg: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None


class MaterialSwitchUpdate(BaseModel):
    from_material: Optional[str] = None
    to_material: Optional[str] = None
    switch_time_mins: Optional[int] = Field(default=None, gt=0)
    scrap_weight_kg: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None


class GmpRule(BaseModel):
    from_order_class: str
    to_order_class: str
    clearance_time_mins: int = Field(ge=0)
    description: Optional[str] = None


class GmpUpdate(BaseModel):
    from_order_class: Optional[str] = None
    to_order_class: Optional[str] = None
    clearance_time_mins: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = None


class SpecRule(BaseModel):
    attribute: str
    condition_desc: str
    threshold_lower: Optional[int] = None
    threshold_upper: Optional[int] = None
    change_time_mins: int = Field(ge=0)
    scrap_weight_kg: Optional[float] = Field(default=0, ge=0)
    description: Optional[str] = None


class SpecRuleUpdate(BaseModel):
    attribute: Optional[str] = None
    condition_desc: Optional[str] = None
    threshold_lower: Optional[int] = None
    threshold_upper: Optional[int] = None
    change_time_mins: Optional[int] = Field(default=None, ge=0)
    scrap_weight_kg: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None


class MaintenanceWindow(BaseModel):
    machine_id: str
    start_time: str
    end_time: str
    maintenance_type: str = "ROUTINE"
    reason: Optional[str] = None
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None


class MaintenanceUpdate(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    maintenance_type: Optional[str] = None
    reason: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_rule: Optional[str] = None


@router.get("/summary")
def get_rules_summary(db=Depends(get_db), _=Depends(get_current_user)):
    return {
        "material_switch": list_material_switch_rules(db, _),
        "gmp_clearance": list_gmp_rules(db, _),
        "spec_change": list_spec_rules(db, _),
        "maintenance": list_maintenance_windows(db, _),
    }


@router.get("/material-switch")
def list_material_switch_rules(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, from_material, to_material, switch_time_mins,
            scrap_weight_kg, description
        FROM material_switch_matrix
        ORDER BY from_material, to_material
    """)
    return [dict(r) for r in cur.fetchall()]


@router.post("/material-switch")
def create_material_switch_rule(
    payload: MaterialSwitchRule,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    cur = db.cursor()
    cur.execute("""
        INSERT INTO material_switch_matrix
            (from_material, to_material, switch_time_mins, scrap_weight_kg, description)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (from_material, to_material) DO UPDATE SET
            switch_time_mins=EXCLUDED.switch_time_mins,
            scrap_weight_kg=EXCLUDED.scrap_weight_kg,
            description=EXCLUDED.description
        RETURNING id
    """, (
        payload.from_material, payload.to_material, payload.switch_time_mins,
        payload.scrap_weight_kg, payload.description,
    ))
    rule_id = cur.fetchone()["id"]
    db.commit()
    return {"id": rule_id}


@router.patch("/material-switch/{rule_id}")
def update_material_switch_rule(
    rule_id: int,
    payload: MaterialSwitchUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    return _update_by_id(db, "material_switch_matrix", rule_id, fields)


@router.delete("/material-switch/{rule_id}")
def delete_material_switch_rule(
    rule_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    return _delete_by_id(db, "material_switch_matrix", rule_id, "Material switch rule")


@router.get("/gmp-clearance")
def list_gmp_rules(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, from_order_class, to_order_class, clearance_time_mins, description
        FROM gmp_clearance_matrix
        ORDER BY from_order_class, to_order_class
    """)
    return [dict(r) for r in cur.fetchall()]


@router.post("/gmp-clearance")
def create_gmp_rule(
    payload: GmpRule,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    cur = db.cursor()
    cur.execute("""
        INSERT INTO gmp_clearance_matrix
            (from_order_class, to_order_class, clearance_time_mins, description)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (from_order_class, to_order_class) DO UPDATE SET
            clearance_time_mins=EXCLUDED.clearance_time_mins,
            description=EXCLUDED.description
        RETURNING id
    """, (
        payload.from_order_class, payload.to_order_class,
        payload.clearance_time_mins, payload.description,
    ))
    rule_id = cur.fetchone()["id"]
    db.commit()
    return {"id": rule_id}


@router.patch("/gmp-clearance/{rule_id}")
def update_gmp_rule(
    rule_id: int,
    payload: GmpUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    return _update_by_id(db, "gmp_clearance_matrix", rule_id, fields)


@router.delete("/gmp-clearance/{rule_id}")
def delete_gmp_rule(
    rule_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    return _delete_by_id(db, "gmp_clearance_matrix", rule_id, "GMP clearance rule")


@router.get("/spec-change")
def list_spec_rules(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, attribute, condition_desc, threshold_lower, threshold_upper,
            change_time_mins, scrap_weight_kg, description
        FROM spec_change_rules
        ORDER BY attribute, threshold_upper NULLS LAST, id
    """)
    return [dict(r) for r in cur.fetchall()]


@router.post("/spec-change")
def create_spec_rule(
    payload: SpecRule,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    cur = db.cursor()
    cur.execute("""
        INSERT INTO spec_change_rules
            (attribute, condition_desc, threshold_lower, threshold_upper,
             change_time_mins, scrap_weight_kg, description)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        payload.attribute, payload.condition_desc, payload.threshold_lower,
        payload.threshold_upper, payload.change_time_mins,
        payload.scrap_weight_kg, payload.description,
    ))
    rule_id = cur.fetchone()["id"]
    db.commit()
    return {"id": rule_id}


@router.patch("/spec-change/{rule_id}")
def update_spec_rule(
    rule_id: int,
    payload: SpecRuleUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    return _update_by_id(db, "spec_change_rules", rule_id, fields)


@router.delete("/spec-change/{rule_id}")
def delete_spec_rule(
    rule_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    return _delete_by_id(db, "spec_change_rules", rule_id, "Spec change rule")


@router.get("/maintenance")
def list_maintenance_windows(db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    cur.execute("""
        SELECT id, machine_id, start_time, end_time, maintenance_type,
            reason, is_recurring, recurrence_rule
        FROM machine_maintenance_calendar
        ORDER BY start_time, machine_id
    """)
    return [{
        **dict(r),
        "start_time": r["start_time"].isoformat(),
        "end_time": r["end_time"].isoformat(),
    } for r in cur.fetchall()]


@router.post("/maintenance")
def create_maintenance_window(
    payload: MaintenanceWindow,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    _validate_maintenance_type(payload.maintenance_type)
    cur = db.cursor()
    cur.execute("""
        INSERT INTO machine_maintenance_calendar
            (machine_id, start_time, end_time, maintenance_type,
             reason, is_recurring, recurrence_rule)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        payload.machine_id, payload.start_time, payload.end_time,
        payload.maintenance_type, payload.reason, payload.is_recurring,
        payload.recurrence_rule,
    ))
    window_id = cur.fetchone()["id"]
    db.commit()
    return {"id": window_id}


@router.patch("/maintenance/{window_id}")
def update_maintenance_window(
    window_id: int,
    payload: MaintenanceUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    if "maintenance_type" in fields:
        _validate_maintenance_type(fields["maintenance_type"])
    return _update_by_id(db, "machine_maintenance_calendar", window_id, fields)


@router.delete("/maintenance/{window_id}")
def delete_maintenance_window(
    window_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    cur = db.cursor()
    cur.execute("DELETE FROM machine_maintenance_calendar WHERE id=%s", (window_id,))
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Maintenance window not found.")
    db.commit()
    return {"id": window_id, "deleted": True}


def _validate_maintenance_type(value: str):
    if value not in {"ROUTINE", "EMERGENCY", "GMP_CLEANING", "OVERHAUL"}:
        raise HTTPException(status_code=400, detail="Invalid maintenance type.")


def _update_by_id(db, table: str, row_id: int, fields: dict):
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    assignments = []
    params = []
    for key, value in fields.items():
        assignments.append(f"{key}=%s")
        params.append(value)
    params.append(row_id)

    cur = db.cursor()
    cur.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id=%s", params)
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Rule not found.")
    db.commit()
    return {"id": row_id, "updated": sorted(fields.keys())}


def _delete_by_id(db, table: str, row_id: int, label: str):
    cur = db.cursor()
    cur.execute(f"DELETE FROM {table} WHERE id=%s", (row_id,))
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    db.commit()
    return {"id": row_id, "deleted": True}
