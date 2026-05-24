"""Configurable scheduling constraints and setup rules."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from psycopg2.extras import Json

from api.auth import get_current_user, require_role
from api.deps import get_db
from api.routers.orders import _mark_order_screening_cache_stale

router = APIRouter(prefix="/api/rules", tags=["Rules"])


class MaterialSwitchRule(BaseModel):
    from_material: str
    to_material: str
    switch_time_mins: int = Field(gt=0)
    scrap_weight_kg: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None
    is_enabled: bool = True
    disabled_reason: Optional[str] = None


class MaterialSwitchUpdate(BaseModel):
    from_material: Optional[str] = None
    to_material: Optional[str] = None
    switch_time_mins: Optional[int] = Field(default=None, gt=0)
    scrap_weight_kg: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    disabled_reason: Optional[str] = None


class GmpRule(BaseModel):
    from_order_class: str
    to_order_class: str
    clearance_time_mins: int = Field(ge=0)
    description: Optional[str] = None
    is_enabled: bool = True
    disabled_reason: Optional[str] = None


class GmpUpdate(BaseModel):
    from_order_class: Optional[str] = None
    to_order_class: Optional[str] = None
    clearance_time_mins: Optional[int] = Field(default=None, ge=0)
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    disabled_reason: Optional[str] = None


class SpecRule(BaseModel):
    attribute: str
    condition_desc: str
    threshold_lower: Optional[int] = None
    threshold_upper: Optional[int] = None
    change_time_mins: int = Field(ge=0)
    scrap_weight_kg: Optional[float] = Field(default=0, ge=0)
    description: Optional[str] = None
    is_enabled: bool = True
    disabled_reason: Optional[str] = None


class SpecRuleUpdate(BaseModel):
    attribute: Optional[str] = None
    condition_desc: Optional[str] = None
    threshold_lower: Optional[int] = None
    threshold_upper: Optional[int] = None
    change_time_mins: Optional[int] = Field(default=None, ge=0)
    scrap_weight_kg: Optional[float] = Field(default=None, ge=0)
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    disabled_reason: Optional[str] = None


class MaintenanceWindow(BaseModel):
    machine_id: str
    start_time: str
    end_time: str
    maintenance_type: str = "ROUTINE"
    reason: Optional[str] = None
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    is_enabled: bool = True
    disabled_reason: Optional[str] = None


class MaintenanceUpdate(BaseModel):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    maintenance_type: Optional[str] = None
    reason: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_rule: Optional[str] = None
    is_enabled: Optional[bool] = None
    disabled_reason: Optional[str] = None


RULE_TABLES = {
    "material_switch": "material_switch_matrix",
    "gmp_clearance": "gmp_clearance_matrix",
    "spec_change": "spec_change_rules",
    "maintenance": "machine_maintenance_calendar",
}


def ensure_rule_enablement_schema(db) -> None:
    cur = db.cursor()
    for table in RULE_TABLES.values():
        cur.execute(f"""
            ALTER TABLE {table}
                ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                ADD COLUMN IF NOT EXISTS disabled_reason TEXT,
                ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50),
                ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
        """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS config_change_audit (
            id              SERIAL       PRIMARY KEY,
            config_scope    VARCHAR(40)  NOT NULL,
            config_key      TEXT,
            entity_id       VARCHAR(80),
            before_state    JSONB,
            after_state     JSONB,
            changed_by      VARCHAR(50),
            reason_text     TEXT,
            created_at      TIMESTAMPTZ  DEFAULT NOW()
        )
    """)
    cur.execute("""
        ALTER TABLE config_change_audit
            ALTER COLUMN config_key TYPE TEXT
    """)
    db.commit()


def _rule_state_counts(rows) -> dict:
    enabled = sum(1 for row in rows if row.get("is_enabled", True))
    disabled = sum(1 for row in rows if not row.get("is_enabled", True))
    return {"enabled": enabled, "disabled": disabled}


def _normalize_rule_enablement_fields(fields: dict, before: dict | None = None) -> dict:
    normalized = dict(fields)
    if "is_enabled" not in normalized and "disabled_reason" not in normalized:
        return normalized

    before_enabled = True if before is None else before.get("is_enabled", True)
    before_reason = None if before is None else before.get("disabled_reason")
    is_enabled = normalized.get("is_enabled", before_enabled)
    reason = normalized.get("disabled_reason", before_reason)

    if is_enabled is False:
        reason = (reason or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail="禁用规则必须填写禁用原因。")
        normalized["disabled_reason"] = reason
    elif normalized.get("is_enabled") is True or "disabled_reason" in normalized:
        normalized["disabled_reason"] = None

    return normalized


def _plain_row(row) -> dict | None:
    return dict(row) if row else None


def _json_safe(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _rule_audit_payload(
    table: str,
    row_id: int,
    before: dict | None,
    after: dict | None,
    user: str | None,
) -> dict:
    config_key = next((key for key, table_name in RULE_TABLES.items() if table_name == table), table)
    reason = None
    if after and after.get("is_enabled") is False:
        reason = after.get("disabled_reason")
    if reason is None and before and after is None:
        reason = "规则删除"
    return {
        "config_scope": "rule",
        "config_key": config_key,
        "entity_id": str(row_id),
        "before_state": before,
        "after_state": after,
        "changed_by": user,
        "reason_text": reason or "规则配置调整",
    }


def _insert_config_audit(cur, payload: dict) -> None:
    cur.execute("""
        INSERT INTO config_change_audit
            (config_scope, config_key, entity_id, before_state, after_state, changed_by, reason_text)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        payload["config_scope"],
        payload["config_key"],
        payload["entity_id"],
        Json(_json_safe(payload.get("before_state"))),
        Json(_json_safe(payload.get("after_state"))),
        payload.get("changed_by"),
        payload.get("reason_text"),
    ))
    _mark_order_screening_cache_stale(cur, reason="rule_matrix_changed")


def _load_rule_row(cur, table: str, row_id: int) -> dict | None:
    cur.execute(f"SELECT * FROM {table} WHERE id=%s", (row_id,))
    return _plain_row(cur.fetchone())


def rule_state_counts_for_db(db) -> dict:
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    result = {}
    for key, table in RULE_TABLES.items():
        cur.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE COALESCE(is_enabled, TRUE)=TRUE) AS enabled,
                COUNT(*) FILTER (WHERE COALESCE(is_enabled, TRUE)=FALSE) AS disabled
            FROM {table}
        """)
        row = cur.fetchone() or {}
        result[key] = {
            "enabled": int(row.get("enabled") or 0),
            "disabled": int(row.get("disabled") or 0),
        }
    db.commit()
    return result


@router.get("/summary")
def get_rules_summary(db=Depends(get_db), _=Depends(get_current_user)):
    ensure_rule_enablement_schema(db)
    material_switch = list_material_switch_rules(db, _)
    gmp_clearance = list_gmp_rules(db, _)
    spec_change = list_spec_rules(db, _)
    maintenance = list_maintenance_windows(db, _)
    return {
        "material_switch": material_switch,
        "gmp_clearance": gmp_clearance,
        "spec_change": spec_change,
        "maintenance": maintenance,
        "maintenance_duplicate_summary": get_maintenance_duplicate_summary(db, _),
        "rule_state_counts": {
            "material_switch": _rule_state_counts(material_switch),
            "gmp_clearance": _rule_state_counts(gmp_clearance),
            "spec_change": _rule_state_counts(spec_change),
            "maintenance": _rule_state_counts(maintenance),
        },
    }


@router.get("/material-switch")
def list_material_switch_rules(db=Depends(get_db), _=Depends(get_current_user)):
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT id, from_material, to_material, switch_time_mins,
            scrap_weight_kg, description, is_enabled, disabled_reason,
            updated_by, updated_at
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
    ensure_rule_enablement_schema(db)
    fields = _normalize_rule_enablement_fields(payload.model_dump(), before=None)
    cur = db.cursor()
    cur.execute("""
        INSERT INTO material_switch_matrix
            (from_material, to_material, switch_time_mins, scrap_weight_kg, description,
             is_enabled, disabled_reason, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (from_material, to_material) DO UPDATE SET
            switch_time_mins=EXCLUDED.switch_time_mins,
            scrap_weight_kg=EXCLUDED.scrap_weight_kg,
            description=EXCLUDED.description,
            is_enabled=EXCLUDED.is_enabled,
            disabled_reason=EXCLUDED.disabled_reason,
            updated_by=EXCLUDED.updated_by,
            updated_at=NOW()
        RETURNING id
    """, (
        fields["from_material"], fields["to_material"], fields["switch_time_mins"],
        fields.get("scrap_weight_kg"), fields.get("description"), fields["is_enabled"],
        fields.get("disabled_reason"), _.username,
    ))
    rule_id = cur.fetchone()["id"]
    _mark_order_screening_cache_stale(cur, reason="rule_matrix_changed")
    db.commit()
    return {"id": rule_id}


@router.patch("/material-switch/{rule_id}")
def update_material_switch_rule(
    rule_id: int,
    payload: MaterialSwitchUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    fields = payload.model_dump(exclude_unset=True)
    return _update_by_id(db, "material_switch_matrix", rule_id, fields, user=_.username)


@router.delete("/material-switch/{rule_id}")
def delete_material_switch_rule(
    rule_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    return _delete_by_id(db, "material_switch_matrix", rule_id, "Material switch rule", user=_.username)


@router.get("/gmp-clearance")
def list_gmp_rules(db=Depends(get_db), _=Depends(get_current_user)):
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT id, from_order_class, to_order_class, clearance_time_mins,
            description, is_enabled, disabled_reason, updated_by, updated_at
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
    ensure_rule_enablement_schema(db)
    fields = _normalize_rule_enablement_fields(payload.model_dump(), before=None)
    cur = db.cursor()
    cur.execute("""
        INSERT INTO gmp_clearance_matrix
            (from_order_class, to_order_class, clearance_time_mins, description,
             is_enabled, disabled_reason, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (from_order_class, to_order_class) DO UPDATE SET
            clearance_time_mins=EXCLUDED.clearance_time_mins,
            description=EXCLUDED.description,
            is_enabled=EXCLUDED.is_enabled,
            disabled_reason=EXCLUDED.disabled_reason,
            updated_by=EXCLUDED.updated_by,
            updated_at=NOW()
        RETURNING id
    """, (
        fields["from_order_class"], fields["to_order_class"],
        fields["clearance_time_mins"], fields.get("description"),
        fields["is_enabled"], fields.get("disabled_reason"), _.username,
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
    ensure_rule_enablement_schema(db)
    fields = payload.model_dump(exclude_unset=True)
    return _update_by_id(db, "gmp_clearance_matrix", rule_id, fields, user=_.username)


@router.delete("/gmp-clearance/{rule_id}")
def delete_gmp_rule(
    rule_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    return _delete_by_id(db, "gmp_clearance_matrix", rule_id, "GMP clearance rule", user=_.username)


@router.get("/spec-change")
def list_spec_rules(db=Depends(get_db), _=Depends(get_current_user)):
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT id, attribute, condition_desc, threshold_lower, threshold_upper,
            change_time_mins, scrap_weight_kg, description, is_enabled,
            disabled_reason, updated_by, updated_at
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
    ensure_rule_enablement_schema(db)
    fields = _normalize_rule_enablement_fields(payload.model_dump(), before=None)
    cur = db.cursor()
    cur.execute("""
        INSERT INTO spec_change_rules
            (attribute, condition_desc, threshold_lower, threshold_upper,
             change_time_mins, scrap_weight_kg, description, is_enabled,
             disabled_reason, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING id
    """, (
        fields["attribute"], fields["condition_desc"], fields.get("threshold_lower"),
        fields.get("threshold_upper"), fields["change_time_mins"],
        fields.get("scrap_weight_kg"), fields.get("description"), fields["is_enabled"],
        fields.get("disabled_reason"), _.username,
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
    ensure_rule_enablement_schema(db)
    fields = payload.model_dump(exclude_unset=True)
    return _update_by_id(db, "spec_change_rules", rule_id, fields, user=_.username)


@router.delete("/spec-change/{rule_id}")
def delete_spec_rule(
    rule_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    return _delete_by_id(db, "spec_change_rules", rule_id, "Spec change rule", user=_.username)


@router.get("/maintenance")
def list_maintenance_windows(db=Depends(get_db), _=Depends(get_current_user)):
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT * FROM (
            SELECT DISTINCT ON (
                machine_id, start_time, end_time, maintenance_type,
                COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                COALESCE(recurrence_rule, '')
            )
                id, machine_id, start_time, end_time, maintenance_type,
                reason, is_recurring, recurrence_rule, is_enabled,
                disabled_reason, updated_by, updated_at
            FROM machine_maintenance_calendar
            ORDER BY
                machine_id, start_time, end_time, maintenance_type,
                COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                COALESCE(recurrence_rule, ''), id
        ) deduped
        ORDER BY start_time, machine_id
    """)
    return [_maintenance_row_to_dict(r) for r in cur.fetchall()]


@router.get("/maintenance/duplicates")
def get_maintenance_duplicate_summary(db=Depends(get_db), _=Depends(get_current_user)):
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT id, machine_id, start_time, end_time, maintenance_type,
            reason, is_recurring, recurrence_rule
        FROM machine_maintenance_calendar
        WHERE id IN (
            SELECT UNNEST(ids) FROM (
                SELECT ARRAY_AGG(id ORDER BY id) AS ids
                FROM machine_maintenance_calendar
                GROUP BY
                    machine_id, start_time, end_time, maintenance_type,
                    COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                    COALESCE(recurrence_rule, '')
                HAVING COUNT(*) > 1
            ) groups
        )
        ORDER BY machine_id, start_time, id
    """)
    rows = [_maintenance_row_to_dict(r) for r in cur.fetchall()]
    groups = {}
    for row in rows:
        key = (
            row["machine_id"],
            row["start_time"],
            row["end_time"],
            row["maintenance_type"],
            row.get("reason") or "",
            bool(row.get("is_recurring")),
            row.get("recurrence_rule") or "",
        )
        groups.setdefault(key, []).append(row)

    duplicate_groups = []
    for items in groups.values():
        keep = min(items, key=lambda item: item["id"])
        duplicate_groups.append({
            "machine_id": keep["machine_id"],
            "start_time": keep["start_time"],
            "end_time": keep["end_time"],
            "maintenance_type": keep["maintenance_type"],
            "reason": keep.get("reason"),
            "keep_id": keep["id"],
            "ids": [item["id"] for item in sorted(items, key=lambda item: item["id"])],
            "duplicate_count": len(items),
            "duplicate_row_count": len(items) - 1,
        })

    duplicate_groups.sort(key=lambda item: (
        -item["duplicate_row_count"],
        item["start_time"],
        item["machine_id"],
    ))
    return {
        "group_count": len(duplicate_groups),
        "duplicate_row_count": sum(item["duplicate_row_count"] for item in duplicate_groups),
        "groups": duplicate_groups,
    }


@router.post("/maintenance/dedupe")
def dedupe_maintenance_windows(
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    before = get_maintenance_duplicate_summary(db, _)
    cur = db.cursor()
    cur.execute("""
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        machine_id, start_time, end_time, maintenance_type,
                        COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                        COALESCE(recurrence_rule, '')
                    ORDER BY id
                ) AS rn
            FROM machine_maintenance_calendar
        ),
        deleted AS (
            DELETE FROM machine_maintenance_calendar m
            USING ranked r
            WHERE m.id = r.id AND r.rn > 1
            RETURNING m.id
        )
        SELECT COUNT(*) AS deleted_count FROM deleted
    """)
    deleted_count = cur.fetchone()["deleted_count"]
    db.commit()
    after = get_maintenance_duplicate_summary(db, _)
    return {
        "deleted_count": deleted_count,
        "before": before,
        "after": after,
    }


@router.post("/maintenance")
def create_maintenance_window(
    payload: MaintenanceWindow,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    _validate_maintenance_type(payload.maintenance_type)
    fields = _normalize_rule_enablement_fields(payload.model_dump(), before=None)
    cur = db.cursor()
    cur.execute("""
        SELECT id
        FROM machine_maintenance_calendar
        WHERE machine_id=%s
          AND start_time=%s::timestamptz
          AND end_time=%s::timestamptz
          AND COALESCE(maintenance_type, '')=COALESCE(%s, '')
          AND COALESCE(reason, '')=COALESCE(%s, '')
          AND COALESCE(is_recurring, FALSE)=%s
          AND COALESCE(recurrence_rule, '')=COALESCE(%s, '')
          AND COALESCE(is_enabled, TRUE)=%s
          AND COALESCE(disabled_reason, '')=COALESCE(%s, '')
        ORDER BY id
        LIMIT 1
    """, (
        fields["machine_id"], fields["start_time"], fields["end_time"],
        fields["maintenance_type"], fields.get("reason"), bool(fields.get("is_recurring")),
        fields.get("recurrence_rule"), bool(fields["is_enabled"]), fields.get("disabled_reason"),
    ))
    existing = cur.fetchone()
    if existing:
        db.commit()
        return {"id": existing["id"], "created": False, "deduped": True}

    cur.execute("""
        INSERT INTO machine_maintenance_calendar
            (machine_id, start_time, end_time, maintenance_type,
             reason, is_recurring, recurrence_rule, is_enabled,
             disabled_reason, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING id
    """, (
        fields["machine_id"], fields["start_time"], fields["end_time"],
        fields["maintenance_type"], fields.get("reason"), fields.get("is_recurring"),
        fields.get("recurrence_rule"), fields["is_enabled"], fields.get("disabled_reason"),
        _.username,
    ))
    window_id = cur.fetchone()["id"]
    db.commit()
    return {"id": window_id, "created": True}


@router.patch("/maintenance/{window_id}")
def update_maintenance_window(
    window_id: int,
    payload: MaintenanceUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    fields = payload.model_dump(exclude_unset=True)
    if "maintenance_type" in fields:
        _validate_maintenance_type(fields["maintenance_type"])
    return _update_by_id(db, "machine_maintenance_calendar", window_id, fields, user=_.username)


@router.delete("/maintenance/{window_id}")
def delete_maintenance_window(
    window_id: int,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    ensure_rule_enablement_schema(db)
    cur = db.cursor()
    before = _load_rule_row(cur, "machine_maintenance_calendar", window_id)
    cur.execute("DELETE FROM machine_maintenance_calendar WHERE id=%s", (window_id,))
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Maintenance window not found.")
    _insert_config_audit(cur, _rule_audit_payload("machine_maintenance_calendar", window_id, before, None, _.username))
    db.commit()
    return {"id": window_id, "deleted": True}


def _validate_maintenance_type(value: str):
    if value not in {"ROUTINE", "EMERGENCY", "GMP_CLEANING", "OVERHAUL"}:
        raise HTTPException(status_code=400, detail="Invalid maintenance type.")


def _maintenance_row_to_dict(row):
    return {
        **dict(row),
        "start_time": row["start_time"].isoformat(),
        "end_time": row["end_time"].isoformat(),
    }


def _update_by_id(db, table: str, row_id: int, fields: dict, user: str | None = None):
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")

    cur = db.cursor()
    before = _load_rule_row(cur, table, row_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Rule not found.")
    fields = _normalize_rule_enablement_fields(fields, before=before)
    assignments = []
    params = []
    for key, value in fields.items():
        assignments.append(f"{key}=%s")
        params.append(value)
    assignments.append("updated_at=NOW()")
    if user:
        assignments.append("updated_by=%s")
        params.append(user)
    params.append(row_id)

    cur.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE id=%s", params)
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Rule not found.")
    after = _load_rule_row(cur, table, row_id)
    _insert_config_audit(cur, _rule_audit_payload(table, row_id, before, after, user))
    db.commit()
    return {"id": row_id, "updated": sorted(fields.keys())}


def _delete_by_id(db, table: str, row_id: int, label: str, user: str | None = None):
    cur = db.cursor()
    before = _load_rule_row(cur, table, row_id)
    cur.execute(f"DELETE FROM {table} WHERE id=%s", (row_id,))
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail=f"{label} not found.")
    _insert_config_audit(cur, _rule_audit_payload(table, row_id, before, None, user))
    db.commit()
    return {"id": row_id, "deleted": True}
