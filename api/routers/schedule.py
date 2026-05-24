"""Schedule, run history, and Gantt API."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import locale
from math import ceil
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import Json

from api.auth import get_current_user, require_role
from api.deps import get_db
from api.routers.orders import (
    _ensure_order_screening_override_schema,
    _ensure_order_screening_schema,
    _mark_order_screening_cache_stale,
)
from src.config import BASELINE_TIME, CONTINUOUS_RUN_LIMIT_MINUTES
from src.diagnostics import (
    Diagnostic,
    DiagnosticEvidence,
    DiagnosticRecommendation,
    parse_infeasible_log_diagnostics,
)
from src.order_screening import DEFAULT_SCREENING_POLICY, build_screening_snapshot, screen_orders
from src.models import ProductionOrderModel
from src.scheduler import AdvancedMedicalAPS, ScheduledTask, SetupCalculator
from src.snapshotting import (
    build_input_snapshot,
    build_machine_capability_snapshot,
    build_maintenance_calendar_snapshot,
    build_process_snapshot,
    build_rule_matrix_snapshot,
    stable_hash,
)

router = APIRouter(prefix="/api/schedule", tags=["Schedule"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_JOB_LOCK = threading.Lock()
_PLANNING_SCHEMA_LOCK = threading.Lock()
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
ORDER_SNAPSHOT_FIELDS = (
    "product_type",
    "target_width",
    "target_thickness",
    "total_quantity_kg",
    "cleanroom_req",
    "order_class",
    "due_date",
    "material_available_time",
    "status",
    "priority_override",
)
VALIDATION_SUMMARY_VERSION = "preplan-validation-v1"
VALIDATION_LEVELS = {"info", "warning", "publish_blocker", "invalid"}
VALIDATION_BLOCKING_LEVELS = {"publish_blocker", "invalid"}


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _as_naive(value):
    return value.replace(tzinfo=None) if value and value.tzinfo is not None else value


class ScheduleSettingsPayload(BaseModel):
    review_required: Optional[bool] = None
    manual_adjust_enabled: Optional[bool] = None
    manual_adjust_reason_required: Optional[bool] = None
    publish_with_warnings_allowed: Optional[bool] = None
    auto_release_enabled: Optional[bool] = None
    material_constraint_enabled: Optional[bool] = None
    maintenance_constraint_enabled: Optional[bool] = None
    setup_rules_enabled: Optional[bool] = None
    cleanroom_constraint_enabled: Optional[bool] = None
    machine_capability_constraint_enabled: Optional[bool] = None
    due_date_optimization_enabled: Optional[bool] = None
    continuous_run_limit_mins: Optional[int] = None
    continuous_run_enforcement_mode: Optional[str] = None
    phase2_feasible_tardiness_tolerance_mins: Optional[int] = None
    solver_profile: Optional[str] = None
    solver_time_limit_seconds: Optional[float] = None
    solver_relative_gap_limit: Optional[float] = None
    solver_random_seed: Optional[int] = None
    solver_num_workers: Optional[int] = None
    solver_log_search_progress: Optional[bool] = None
    planning_must_schedule_horizon_days: Optional[int] = None
    planning_candidate_horizon_days: Optional[int] = None
    candidate_reject_penalty: Optional[int] = None
    candidate_max_deferred_count: Optional[int] = None
    candidate_min_acceptance_ratio: Optional[float] = None
    arc_pruning_enabled: Optional[bool] = None
    arc_pruning_max_setup_mins: Optional[int] = None
    arc_pruning_top_k_per_order: Optional[int] = None
    screening_due_risk_min_slack_mins: Optional[int] = None
    screening_due_risk_duration_multiplier: Optional[float] = None
    screening_allowed_order_statuses: Optional[list[str]] = None
    screening_prohibited_override_codes: Optional[list[str]] = None
    screening_restricted_override_codes: Optional[list[str]] = None
    screening_required_positive_order_fields: Optional[list[str]] = None
    manual_adjust_review_delay_threshold_mins: Optional[int] = None
    manual_adjust_review_setup_threshold_mins: Optional[int] = None
    manual_adjust_review_tardiness_threshold_mins: Optional[int] = None
    change_reason: Optional[str] = None


POLICY_SETTING_KEYS = (
    "review_required",
    "manual_adjust_enabled",
    "manual_adjust_reason_required",
    "publish_with_warnings_allowed",
    "auto_release_enabled",
    "material_constraint_enabled",
    "maintenance_constraint_enabled",
    "setup_rules_enabled",
    "cleanroom_constraint_enabled",
    "machine_capability_constraint_enabled",
    "due_date_optimization_enabled",
)


POLICY_VALUE_KEYS = (
    "continuous_run_limit_mins",
    "continuous_run_enforcement_mode",
    "phase2_feasible_tardiness_tolerance_mins",
    "solver_profile",
    "solver_time_limit_seconds",
    "solver_relative_gap_limit",
    "solver_random_seed",
    "solver_num_workers",
    "solver_log_search_progress",
    "planning_must_schedule_horizon_days",
    "planning_candidate_horizon_days",
    "candidate_reject_penalty",
    "candidate_max_deferred_count",
    "candidate_min_acceptance_ratio",
    "arc_pruning_enabled",
    "arc_pruning_max_setup_mins",
    "arc_pruning_top_k_per_order",
    "screening_due_risk_min_slack_mins",
    "screening_due_risk_duration_multiplier",
    "screening_allowed_order_statuses",
    "screening_prohibited_override_codes",
    "screening_restricted_override_codes",
    "screening_required_positive_order_fields",
    "manual_adjust_review_delay_threshold_mins",
    "manual_adjust_review_setup_threshold_mins",
    "manual_adjust_review_tardiness_threshold_mins",
)


POLICY_DEFAULTS = {
    "policy_version": 1,
    "review_required": True,
    "manual_adjust_enabled": True,
    "manual_adjust_reason_required": True,
    "publish_with_warnings_allowed": True,
    "auto_release_enabled": False,
    "material_constraint_enabled": True,
    "maintenance_constraint_enabled": True,
    "setup_rules_enabled": True,
    "cleanroom_constraint_enabled": True,
    "machine_capability_constraint_enabled": True,
    "due_date_optimization_enabled": True,
    "continuous_run_limit_mins": CONTINUOUS_RUN_LIMIT_MINUTES,
    "continuous_run_enforcement_mode": "publish_blocker",
    "phase2_feasible_tardiness_tolerance_mins": 0,
    "solver_profile": "standard",
    "solver_time_limit_seconds": 120.0,
    "solver_relative_gap_limit": 0.0,
    "solver_random_seed": 0,
    "solver_num_workers": 8,
    "solver_log_search_progress": False,
    "planning_must_schedule_horizon_days": 3,
    "planning_candidate_horizon_days": 14,
    "candidate_reject_penalty": 10_000_000,
    "candidate_max_deferred_count": None,
    "candidate_min_acceptance_ratio": 0.0,
    "arc_pruning_enabled": False,
    "arc_pruning_max_setup_mins": 0,
    "arc_pruning_top_k_per_order": 0,
    "screening_due_risk_min_slack_mins": 240,
    "screening_due_risk_duration_multiplier": 1.5,
    "screening_allowed_order_statuses": DEFAULT_SCREENING_POLICY["allowed_order_statuses"],
    "screening_prohibited_override_codes": DEFAULT_SCREENING_POLICY["prohibited_override_codes"],
    "screening_restricted_override_codes": DEFAULT_SCREENING_POLICY["restricted_override_codes"],
    "screening_required_positive_order_fields": DEFAULT_SCREENING_POLICY["required_positive_order_fields"],
    "manual_adjust_review_delay_threshold_mins": 0,
    "manual_adjust_review_setup_threshold_mins": 0,
    "manual_adjust_review_tardiness_threshold_mins": 0,
}


def _require_policy_change_reason(value: str | None) -> str:
    reason = (value or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="保存全局策略前必须填写变更原因。")
    return reason


class PreplanCreatePayload(BaseModel):
    order_ids: list[str] = Field(default_factory=list)
    mode: str = Field(default="AUTO")


class ManualAdjustmentPayload(BaseModel):
    order_id: str
    machine_id: str
    start_time: datetime
    end_time: datetime
    sequence_index: Optional[int] = None
    reason_code: str = Field(default="OTHER")
    reason_text: str = ""
    lock_machine: bool = True
    lock_time: bool = True


class CancelPreplanPayload(BaseModel):
    reason: str = ""


class QueueStatusUpdatePayload(BaseModel):
    queue_status: str
    reason: str = ""


def _ensure_planning_schema(db):
    with _PLANNING_SCHEMA_LOCK:
        _ensure_planning_schema_locked(db)


def _ensure_planning_schema_locked(db):
    cur = db.cursor()
    cur.execute("""
        ALTER TABLE schedule_runs
            ADD COLUMN IF NOT EXISTS mode VARCHAR(20) DEFAULT 'AUTO',
            ADD COLUMN IF NOT EXISTS lifecycle_status VARCHAR(30) DEFAULT 'CONFIRMED',
            ADD COLUMN IF NOT EXISTS confirmed_by VARCHAR(50),
            ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS cancelled_by VARCHAR(50),
            ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS cancel_reason TEXT
    """)
    cur.execute("""
        ALTER TABLE scheduled_tasks
            ADD COLUMN IF NOT EXISTS task_source VARCHAR(20) DEFAULT 'AUTO',
            ADD COLUMN IF NOT EXISTS manual_lock_machine BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS manual_lock_time BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS setup_detail JSONB
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_settings (
            id                                  BOOLEAN PRIMARY KEY DEFAULT TRUE,
            review_required                     BOOLEAN NOT NULL DEFAULT TRUE,
            manual_adjust_enabled               BOOLEAN NOT NULL DEFAULT TRUE,
            manual_adjust_reason_required       BOOLEAN NOT NULL DEFAULT TRUE,
            publish_with_warnings_allowed       BOOLEAN NOT NULL DEFAULT TRUE,
            auto_release_enabled                BOOLEAN NOT NULL DEFAULT FALSE,
            material_constraint_enabled         BOOLEAN NOT NULL DEFAULT TRUE,
            maintenance_constraint_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
            setup_rules_enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
            cleanroom_constraint_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
            machine_capability_constraint_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            due_date_optimization_enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            continuous_run_limit_mins           INTEGER NOT NULL DEFAULT 4320,
            continuous_run_enforcement_mode     VARCHAR(30) NOT NULL DEFAULT 'publish_blocker',
            phase2_feasible_tardiness_tolerance_mins INTEGER NOT NULL DEFAULT 0,
            solver_profile                      VARCHAR(30) NOT NULL DEFAULT 'standard',
            solver_time_limit_seconds           DOUBLE PRECISION NOT NULL DEFAULT 120,
            solver_relative_gap_limit           DOUBLE PRECISION NOT NULL DEFAULT 0,
            solver_random_seed                  INTEGER NOT NULL DEFAULT 0,
            solver_num_workers                  INTEGER NOT NULL DEFAULT 8,
            solver_log_search_progress          BOOLEAN NOT NULL DEFAULT FALSE,
            planning_must_schedule_horizon_days INTEGER NOT NULL DEFAULT 3,
            planning_candidate_horizon_days     INTEGER NOT NULL DEFAULT 14,
            candidate_reject_penalty            INTEGER NOT NULL DEFAULT 10000000,
            candidate_max_deferred_count        INTEGER,
            candidate_min_acceptance_ratio      DOUBLE PRECISION NOT NULL DEFAULT 0,
            arc_pruning_enabled                 BOOLEAN NOT NULL DEFAULT FALSE,
            arc_pruning_max_setup_mins          INTEGER NOT NULL DEFAULT 0,
            arc_pruning_top_k_per_order         INTEGER NOT NULL DEFAULT 0,
            screening_due_risk_min_slack_mins   INTEGER NOT NULL DEFAULT 240,
            screening_due_risk_duration_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.5,
            screening_allowed_order_statuses    TEXT[] NOT NULL DEFAULT ARRAY['PENDING']::TEXT[],
            screening_prohibited_override_codes TEXT[] NOT NULL DEFAULT ARRAY['missing_product','missing_recipe','invalid_order_data','no_eligible_machine','status_not_pending']::TEXT[],
            screening_restricted_override_codes TEXT[] NOT NULL DEFAULT ARRAY['material_not_ready','due_risk']::TEXT[],
            screening_required_positive_order_fields TEXT[] NOT NULL DEFAULT ARRAY['due_date_mins','target_thickness','target_width','total_quantity_kg']::TEXT[],
            manual_adjust_review_delay_threshold_mins INTEGER NOT NULL DEFAULT 0,
            manual_adjust_review_setup_threshold_mins INTEGER NOT NULL DEFAULT 0,
            manual_adjust_review_tardiness_threshold_mins INTEGER NOT NULL DEFAULT 0,
            policy_version                      INTEGER NOT NULL DEFAULT 1,
            updated_by                          VARCHAR(50),
            change_reason                       TEXT,
            updated_at                          TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        ALTER TABLE schedule_settings
            ADD COLUMN IF NOT EXISTS material_constraint_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS maintenance_constraint_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS setup_rules_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS cleanroom_constraint_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS machine_capability_constraint_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS due_date_optimization_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            ADD COLUMN IF NOT EXISTS continuous_run_limit_mins INTEGER NOT NULL DEFAULT 4320,
            ADD COLUMN IF NOT EXISTS continuous_run_enforcement_mode VARCHAR(30) NOT NULL DEFAULT 'publish_blocker',
            ADD COLUMN IF NOT EXISTS phase2_feasible_tardiness_tolerance_mins INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS solver_profile VARCHAR(30) NOT NULL DEFAULT 'standard',
            ADD COLUMN IF NOT EXISTS solver_time_limit_seconds DOUBLE PRECISION NOT NULL DEFAULT 120,
            ADD COLUMN IF NOT EXISTS solver_relative_gap_limit DOUBLE PRECISION NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS solver_random_seed INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS solver_num_workers INTEGER NOT NULL DEFAULT 8,
            ADD COLUMN IF NOT EXISTS solver_log_search_progress BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS planning_must_schedule_horizon_days INTEGER NOT NULL DEFAULT 3,
            ADD COLUMN IF NOT EXISTS planning_candidate_horizon_days INTEGER NOT NULL DEFAULT 14,
            ADD COLUMN IF NOT EXISTS candidate_reject_penalty INTEGER NOT NULL DEFAULT 10000000,
            ADD COLUMN IF NOT EXISTS candidate_max_deferred_count INTEGER,
            ADD COLUMN IF NOT EXISTS candidate_min_acceptance_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS arc_pruning_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS arc_pruning_max_setup_mins INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS arc_pruning_top_k_per_order INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS screening_due_risk_min_slack_mins INTEGER NOT NULL DEFAULT 240,
            ADD COLUMN IF NOT EXISTS screening_due_risk_duration_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.5,
            ADD COLUMN IF NOT EXISTS screening_allowed_order_statuses TEXT[] NOT NULL DEFAULT ARRAY['PENDING']::TEXT[],
            ADD COLUMN IF NOT EXISTS screening_prohibited_override_codes TEXT[] NOT NULL DEFAULT ARRAY['missing_product','missing_recipe','invalid_order_data','no_eligible_machine','status_not_pending']::TEXT[],
            ADD COLUMN IF NOT EXISTS screening_restricted_override_codes TEXT[] NOT NULL DEFAULT ARRAY['material_not_ready','due_risk']::TEXT[],
            ADD COLUMN IF NOT EXISTS screening_required_positive_order_fields TEXT[] NOT NULL DEFAULT ARRAY['due_date_mins','target_thickness','target_width','total_quantity_kg']::TEXT[],
            ADD COLUMN IF NOT EXISTS manual_adjust_review_delay_threshold_mins INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS manual_adjust_review_setup_threshold_mins INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS manual_adjust_review_tardiness_threshold_mins INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS policy_version INTEGER NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50),
            ADD COLUMN IF NOT EXISTS change_reason TEXT
    """)
    cur.execute("""
        INSERT INTO schedule_settings (id)
        VALUES (TRUE)
        ON CONFLICT (id) DO NOTHING
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_adjustment_audit (
            id                  SERIAL       PRIMARY KEY,
            run_id              INTEGER      NOT NULL REFERENCES schedule_runs(run_id),
            order_id            VARCHAR(20)  REFERENCES production_orders(order_id),
            action_type         VARCHAR(30)  NOT NULL,
            before_state        JSONB,
            after_state         JSONB,
            reason_code         VARCHAR(50),
            reason_text         TEXT,
            changed_by          VARCHAR(50),
            changed_at          TIMESTAMPTZ  DEFAULT NOW(),
            validation_status   VARCHAR(20)  DEFAULT 'PENDING',
            validation_messages JSONB
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS manufacturing_queue (
            id                  SERIAL       PRIMARY KEY,
            run_id              INTEGER      NOT NULL REFERENCES schedule_runs(run_id),
            scheduled_task_id   INTEGER      REFERENCES scheduled_tasks(id),
            order_id            VARCHAR(20)  NOT NULL REFERENCES production_orders(order_id),
            machine_id          VARCHAR(20)  NOT NULL REFERENCES machines(machine_id),
            sequence_index      INTEGER      NOT NULL,
            planned_start_time  TIMESTAMPTZ  NOT NULL,
            planned_end_time    TIMESTAMPTZ  NOT NULL,
            queue_status        VARCHAR(30)  NOT NULL DEFAULT 'QUEUED',
            released_by         VARCHAR(50),
            released_at         TIMESTAMPTZ  DEFAULT NOW(),
            started_at          TIMESTAMPTZ,
            completed_at        TIMESTAMPTZ,
            UNIQUE(run_id, order_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule_publish_audit (
            id                   SERIAL       PRIMARY KEY,
            run_id               INTEGER      REFERENCES schedule_runs(run_id),
            event_type           VARCHAR(40)  NOT NULL,
            actor                VARCHAR(50),
            selected_order_count INTEGER      NOT NULL DEFAULT 0,
            warning_count        INTEGER      NOT NULL DEFAULT 0,
            queue_row_count      INTEGER      NOT NULL DEFAULT 0,
            details              JSONB,
            created_at           TIMESTAMPTZ  DEFAULT NOW()
        )
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
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_publish_audit_run
        ON schedule_publish_audit(run_id, created_at DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_config_change_audit_created
        ON config_change_audit(created_at DESC, id DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_runs_lifecycle
        ON schedule_runs(lifecycle_status, run_id DESC)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_queue_status
        ON manufacturing_queue(queue_status, planned_start_time)
    """)
    cur.execute("""
        UPDATE schedule_runs
        SET lifecycle_status='CONFIRMED'
        WHERE lifecycle_status IS NULL
    """)
    db.commit()


def _normalize_json(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _json_safe(value):
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _get_schedule_settings(db):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT review_required, manual_adjust_enabled,
            manual_adjust_reason_required, publish_with_warnings_allowed,
            auto_release_enabled, material_constraint_enabled,
            maintenance_constraint_enabled, setup_rules_enabled,
            cleanroom_constraint_enabled, machine_capability_constraint_enabled,
            due_date_optimization_enabled, continuous_run_limit_mins,
            continuous_run_enforcement_mode, phase2_feasible_tardiness_tolerance_mins,
            solver_profile, solver_time_limit_seconds, solver_relative_gap_limit,
            solver_random_seed, solver_num_workers, solver_log_search_progress,
            planning_must_schedule_horizon_days, planning_candidate_horizon_days,
            candidate_reject_penalty, candidate_max_deferred_count,
            candidate_min_acceptance_ratio,
            arc_pruning_enabled, arc_pruning_max_setup_mins,
            arc_pruning_top_k_per_order,
            screening_due_risk_min_slack_mins, screening_due_risk_duration_multiplier,
            screening_allowed_order_statuses,
            screening_prohibited_override_codes,
            screening_restricted_override_codes,
            screening_required_positive_order_fields,
            manual_adjust_review_delay_threshold_mins,
            manual_adjust_review_setup_threshold_mins,
            manual_adjust_review_tardiness_threshold_mins,
            policy_version, updated_by,
            change_reason, updated_at
        FROM schedule_settings WHERE id=TRUE
    """)
    row = cur.fetchone()
    if not row:
        return dict(POLICY_DEFAULTS)
    settings = {**POLICY_DEFAULTS, **dict(row)}
    settings["policy_version"] = int(settings.get("policy_version") or 1)
    return settings


def _policy_list(settings: dict, key: str, *, transform=None) -> list[str]:
    values = settings.get(key, POLICY_DEFAULTS.get(key, []))
    values = _normalize_json(values, values)
    if isinstance(values, str):
        values = [values]
    transform = transform or (lambda item: item)
    normalized = []
    seen = set()
    for value in values or []:
        item = transform(str(value).strip())
        if not item or item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    if normalized:
        return normalized
    return list(POLICY_DEFAULTS.get(key, []))


def _screening_override_code_lists(settings: dict) -> tuple[list[str], list[str]]:
    prohibited = _policy_list(settings, "screening_prohibited_override_codes", transform=str.lower)
    restricted = _policy_list(settings, "screening_restricted_override_codes", transform=str.lower)
    prohibited_set = set(prohibited)
    return prohibited, [code for code in restricted if code not in prohibited_set]


def _candidate_max_deferred_count(settings: dict) -> int | None:
    value = settings.get("candidate_max_deferred_count")
    if value is None:
        return None
    return max(0, int(value))


def _candidate_min_acceptance_ratio(settings: dict) -> float:
    value = settings.get("candidate_min_acceptance_ratio")
    if value is None:
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _policy_snapshot(settings: dict, enabled_rule_counts: dict | None = None) -> dict:
    normalized = {key: bool(settings.get(key, POLICY_DEFAULTS[key])) for key in POLICY_SETTING_KEYS}
    prohibited_override_codes, restricted_override_codes = _screening_override_code_lists(settings)
    return {
        "policy_version": int(settings.get("policy_version") or 1),
        "settings": normalized,
        "continuous_run": {
            "limit_mins": int(settings.get("continuous_run_limit_mins") or CONTINUOUS_RUN_LIMIT_MINUTES),
            "enforcement_mode": str(settings.get("continuous_run_enforcement_mode") or "publish_blocker"),
        },
        "solver_quality": {
            "phase2_feasible_tardiness_tolerance_mins": int(
                settings.get("phase2_feasible_tardiness_tolerance_mins") or 0
            ),
        },
        "solver_profile": {
            "profile": str(settings.get("solver_profile") or "standard"),
            "time_limit_seconds": float(settings.get("solver_time_limit_seconds") or 120.0),
            "relative_gap_limit": float(settings.get("solver_relative_gap_limit") or 0.0),
            "random_seed": int(settings.get("solver_random_seed") or 0),
            "num_workers": int(settings.get("solver_num_workers") or 8),
            "log_search_progress": bool(settings.get("solver_log_search_progress", False)),
        },
        "planning_bucket": {
            "must_schedule_horizon_days": int(settings.get("planning_must_schedule_horizon_days") or 3),
            "candidate_horizon_days": int(settings.get("planning_candidate_horizon_days") or 14),
        },
        "candidate_acceptance": {
            "reject_penalty": int(settings.get("candidate_reject_penalty") or 10_000_000),
            "max_deferred_count": _candidate_max_deferred_count(settings),
            "min_acceptance_ratio": _candidate_min_acceptance_ratio(settings),
        },
        "arc_pruning": {
            "enabled": bool(settings.get("arc_pruning_enabled", False)),
            "max_setup_time_mins": int(settings.get("arc_pruning_max_setup_mins") or 0),
            "top_k_per_order": int(settings.get("arc_pruning_top_k_per_order") or 0),
        },
        "order_screening": {
            "due_risk_min_slack_mins": int(settings.get("screening_due_risk_min_slack_mins") or 240),
            "due_risk_duration_multiplier": float(
                settings.get("screening_due_risk_duration_multiplier") or 1.5
            ),
            "allowed_order_statuses": _policy_list(
                settings,
                "screening_allowed_order_statuses",
                transform=str.upper,
            ),
            "prohibited_override_codes": prohibited_override_codes,
            "restricted_override_codes": restricted_override_codes,
            "required_positive_order_fields": _policy_list(
                settings,
                "screening_required_positive_order_fields",
            ),
        },
        "manual_adjustment_review": {
            "delay_threshold_mins": int(settings.get("manual_adjust_review_delay_threshold_mins") or 0),
            "setup_threshold_mins": int(settings.get("manual_adjust_review_setup_threshold_mins") or 0),
            "tardiness_threshold_mins": int(settings.get("manual_adjust_review_tardiness_threshold_mins") or 0),
        },
        "enabled_rule_counts": enabled_rule_counts or {},
        "runtime_rule_source": "db_only",
        "fallback_setup_used": False,
    }


def _policy_snapshot_mismatch(saved: dict | None, current: dict | None) -> str | None:
    if not saved:
        return "当前草案缺少全局策略快照，请重新预排。"
    if not current:
        return "无法读取当前全局策略，请重新校验后再发布。"
    if int(saved.get("policy_version") or 0) != int(current.get("policy_version") or 0):
        return "全局策略版本已变化，请重新预排后再发布。"
    if (saved.get("settings") or {}) != (current.get("settings") or {}):
        return "全局策略开关已变化，请重新预排后再发布。"
    if (saved.get("continuous_run") or {}) != (current.get("continuous_run") or {}):
        return "连续运行清场策略已变化，请重新预排后再发布。"
    if (saved.get("solver_quality") or {}) != (current.get("solver_quality") or {}):
        return "求解质量策略已变化，请重新预排后再发布。"
    if (saved.get("solver_profile") or {}) != (current.get("solver_profile") or {}):
        return "求解 profile 已变化，请重新预排后再发布。"
    if (saved.get("planning_bucket") or {}) != (current.get("planning_bucket") or {}):
        return "计划窗口策略已变化，请重新预排后再发布。"
    if (saved.get("candidate_acceptance") or {}) != (current.get("candidate_acceptance") or {}):
        return "candidate acceptance policy changed; rerun pre-schedule before publishing."
    if (saved.get("arc_pruning") or {}) != (current.get("arc_pruning") or {}):
        return "arc pruning policy changed; rerun pre-schedule before publishing."
    if (saved.get("order_screening") or {}) != (current.get("order_screening") or {}):
        return "订单初筛策略已变化，请重新预排后再发布。"
    if (saved.get("manual_adjustment_review") or {}) != (current.get("manual_adjustment_review") or {}):
        return "manual adjustment review policy changed; rerun pre-schedule before publishing."
    if (saved.get("enabled_rule_counts") or {}) != (current.get("enabled_rule_counts") or {}):
        return "启用规则数量已变化，请重新预排后再发布。"
    return None


def _policy_snapshot_validation_item(saved: dict | None, current: dict | None) -> dict[str, Any] | None:
    message = _policy_snapshot_mismatch(saved, current)
    if not message:
        return None
    return _validation_item("error", "policy_snapshot_stale", message)


def _continuous_run_policy(settings: dict, setup_mgr) -> dict[str, Any]:
    return {
        "limit_mins": int(settings.get("continuous_run_limit_mins") or CONTINUOUS_RUN_LIMIT_MINUTES),
        "cleaning_mins": int(getattr(setup_mgr, "continuous_run_cleaning_time", 0) or 0),
        "enforcement_mode": str(settings.get("continuous_run_enforcement_mode") or "publish_blocker"),
    }


def _order_screening_policy(settings: dict) -> dict[str, Any]:
    prohibited_override_codes, restricted_override_codes = _screening_override_code_lists(settings)
    return {
        "due_risk_min_slack_mins": int(settings.get("screening_due_risk_min_slack_mins") or 240),
        "due_risk_duration_multiplier": float(settings.get("screening_due_risk_duration_multiplier") or 1.5),
        "allowed_order_statuses": _policy_list(
            settings,
            "screening_allowed_order_statuses",
            transform=str.upper,
        ),
        "prohibited_override_codes": prohibited_override_codes,
        "restricted_override_codes": restricted_override_codes,
        "required_positive_order_fields": _policy_list(
            settings,
            "screening_required_positive_order_fields",
        ),
    }


def _build_scheduler(setup_mgr, settings: dict) -> AdvancedMedicalAPS:
    return AdvancedMedicalAPS(
        setup_mgr,
        continuous_run_policy=_continuous_run_policy(settings, setup_mgr),
        solver_quality_policy={
            "phase2_feasible_tardiness_tolerance_mins": int(
                settings.get("phase2_feasible_tardiness_tolerance_mins") or 0
            ),
        },
        solver_profile_policy={
            "profile": str(settings.get("solver_profile") or "standard"),
            "time_limit_seconds": float(settings.get("solver_time_limit_seconds") or 120.0),
            "relative_gap_limit": float(settings.get("solver_relative_gap_limit") or 0.0),
            "random_seed": int(settings.get("solver_random_seed") or 0),
            "num_workers": int(settings.get("solver_num_workers") or 8),
            "log_search_progress": bool(settings.get("solver_log_search_progress", False)),
        },
        candidate_acceptance_policy={
            "reject_penalty": int(settings.get("candidate_reject_penalty") or 10_000_000),
            "max_deferred_count": _candidate_max_deferred_count(settings),
            "min_acceptance_ratio": _candidate_min_acceptance_ratio(settings),
        },
        arc_pruning_policy={
            "enabled": bool(settings.get("arc_pruning_enabled", False)),
            "max_setup_time_mins": int(settings.get("arc_pruning_max_setup_mins") or 0),
            "top_k_per_order": int(settings.get("arc_pruning_top_k_per_order") or 0),
        },
    )


INPUT_SNAPSHOT_LABELS = {
    "orders": "订单输入",
    "machine_capability": "机台能力",
    "maintenance_calendar": "维护日历",
    "rule_matrix": "规则矩阵",
    "process": "产品工艺",
    "screening": "订单筛选",
}


def _input_snapshot_mismatch(saved: dict | None, current: dict | None) -> str | None:
    if not saved:
        return "当前草案缺少输入快照，请重新预排。"
    if not current:
        return "无法读取当前输入快照，请重新校验后再发布。"
    if saved.get("hash") == current.get("hash"):
        return None
    changed = []
    for key, label in INPUT_SNAPSHOT_LABELS.items():
        saved_hash = (saved.get(key) or {}).get("hash")
        current_hash = (current.get(key) or {}).get("hash")
        if saved_hash != current_hash:
            changed.append(label)
    changed_text = "、".join(changed) if changed else "排程输入"
    return f"{changed_text}已变化，请重新预排后再发布。"


def _input_snapshot_validation_item(saved: dict | None, current: dict | None) -> dict[str, Any] | None:
    message = _input_snapshot_mismatch(saved, current)
    if not message:
        return None
    return _validation_item("error", "input_snapshot_stale", message)


def _screening_item_has_preplan_override(item: dict[str, Any], audit: dict[str, Any] | None) -> bool:
    if not audit:
        return False
    decision = item.get("override_decision") or {}
    if not decision.get("allowed"):
        return False
    if (audit.get("mode") or "formal") != "formal":
        return False
    if audit.get("screening_status") != item.get("screening_status"):
        return False
    if audit.get("screening_code") != item.get("code"):
        return False
    if audit.get("override_policy") != decision.get("policy"):
        return False
    item["applied_override"] = {
        "audit_id": audit.get("id"),
        "override_policy": audit.get("override_policy"),
        "reason_text": audit.get("reason_text"),
    }
    return True


def _load_latest_formal_screening_overrides(cur, order_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not order_ids:
        return {}
    cur.execute("""
        SELECT DISTINCT ON (order_id)
            id, order_id, screening_status, screening_code, override_policy,
            reason_code, reason_text, mode, policy_version, actor, details,
            created_at
        FROM order_screening_override_audit
        WHERE order_id = ANY(%s)
          AND mode='formal'
        ORDER BY order_id, created_at DESC, id DESC
    """, (order_ids,))
    return {
        row["order_id"]: dict(row)
        for row in cur.fetchall()
    }


def _raise_for_blocked_preplan_orders(
    screening: dict[str, Any],
    override_audits_by_order_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    override_audits_by_order_id = override_audits_by_order_id or {}
    blocked_orders = [
        item
        for item in screening.get("items", [])
        if item.get("screening_status") == "blocked"
        and not _screening_item_has_preplan_override(
            item,
            override_audits_by_order_id.get(item.get("order_id")),
        )
    ]
    if not blocked_orders:
        return
    preview = ", ".join(str(item.get("order_id")) for item in blocked_orders[:5])
    raise HTTPException(
        status_code=400,
        detail={
            "code": "preplan_blocked_orders",
            "message": f"存在不能进入预排的异常订单: {preview}",
            "summary": screening.get("summary", {}),
            "blocked_orders": blocked_orders,
        },
    )


CONFIG_SCOPE_LABELS = {
    "schedule_policy": "全局策略",
    "rule": "规则",
}


def _config_audit_row_to_dict(row) -> dict[str, Any]:
    data = dict(row)
    data["scope_label"] = CONFIG_SCOPE_LABELS.get(data.get("config_scope"), data.get("config_scope") or "配置")
    data["before_state"] = _normalize_json(data.get("before_state"), {}) or {}
    data["after_state"] = _normalize_json(data.get("after_state"), {}) or {}
    data["created_at"] = _iso(data.get("created_at"))
    return data


def _load_rule_state_counts(db) -> dict:
    from api.routers.rules import ensure_rule_enablement_schema, rule_state_counts_for_db

    ensure_rule_enablement_schema(db)
    return rule_state_counts_for_db(db)


def _run_row_to_dict(row):
    params = _normalize_json(row.get("solver_params"), {}) or {}
    summary = params.get("summary") or {}
    return {
        "run_id": row["run_id"],
        "run_time": _iso(row.get("run_time")),
        "baseline_time": _iso(row.get("baseline_time")),
        "triggered_by": row.get("triggered_by"),
        "status": row.get("status"),
        "mode": row.get("mode") or "AUTO",
        "lifecycle_status": row.get("lifecycle_status") or "CONFIRMED",
        "total_orders": row.get("total_orders") or 0,
        "total_machines_used": row.get("total_machines_used") or 0,
        "total_setup_mins": row.get("total_setup_time_mins") or 0,
        "total_scrap_kg": float(row.get("total_scrap_kg") or 0),
        "late_orders": row.get("total_late_orders") or 0,
        "is_active": bool(row.get("is_active")),
        "selected_order_ids": params.get("selected_order_ids") or [],
        "order_snapshots": params.get("order_snapshots") or [],
        "policy_snapshot": params.get("policy_snapshot"),
        "input_snapshot": params.get("input_snapshot"),
        "preplan_screening": params.get("preplan_screening"),
        "last_validated_at": params.get("last_validated_at"),
        "last_validation_summary": params.get("last_validation_summary"),
        "summary": summary,
        "confirmed_by": row.get("confirmed_by"),
        "confirmed_at": _iso(row.get("confirmed_at")),
        "cancelled_by": row.get("cancelled_by"),
        "cancelled_at": _iso(row.get("cancelled_at")),
        "cancel_reason": row.get("cancel_reason"),
    }


def _task_row_to_dict(row):
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "order_id": row["order_id"],
        "machine_id": row["machine_id"],
        "sequence_index": row["sequence_index"],
        "setup_start_time": _iso(row.get("setup_start_time")),
        "start_time": _iso(row.get("start_time")),
        "end_time": _iso(row.get("end_time")),
        "duration_mins": row.get("duration_mins"),
        "setup_time_mins": row.get("setup_time_mins") or 0,
        "setup_detail": _normalize_json(row.get("setup_detail"), {}) or {},
        "scrap_kg": float(row.get("scrap_kg") or 0),
        "net_weight_kg": row.get("net_weight_kg"),
        "actual_material_required_kg": float(row.get("actual_material_required_kg") or 0),
        "is_late": bool(row.get("is_late")),
        "tardiness_mins": row.get("tardiness_mins") or 0,
        "prev_order_id": row.get("prev_order_id"),
        "task_source": row.get("task_source") or "AUTO",
        "manual_lock_machine": bool(row.get("manual_lock_machine")),
        "manual_lock_time": bool(row.get("manual_lock_time")),
        "product_type": row.get("product_type"),
        "target_width": row.get("target_width"),
        "target_thickness": row.get("target_thickness"),
        "total_quantity_kg": row.get("total_quantity_kg"),
        "order_class": row.get("order_class"),
        "due_date": _iso(row.get("due_date")),
    }


def _adjustment_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return _as_naive(value)
    try:
        return _as_naive(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _minutes_between(before, after):
    if before is None or after is None:
        return None
    return int((after - before).total_seconds() / 60)


def _duration_between(start, end):
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() / 60)


def _manual_adjustment_impact(before_state: dict[str, Any] | None, after_state: dict[str, Any] | None) -> dict[str, Any]:
    before_state = before_state or {}
    after_state = after_state or {}
    before_start = _adjustment_datetime(before_state.get("start_time"))
    before_end = _adjustment_datetime(before_state.get("end_time"))
    after_start = _adjustment_datetime(after_state.get("start_time"))
    after_end = _adjustment_datetime(after_state.get("end_time"))
    before_tardiness = int(before_state.get("tardiness_mins") or 0)
    after_tardiness = int(after_state.get("tardiness_mins") or before_tardiness)
    before_setup = int(before_state.get("setup_time_mins") or 0)
    after_setup = int(after_state.get("setup_time_mins") or before_setup)
    from_machine = before_state.get("machine_id")
    to_machine = after_state.get("machine_id")
    return {
        "from_machine_id": from_machine,
        "to_machine_id": to_machine,
        "machine_changed": bool(from_machine and to_machine and from_machine != to_machine),
        "start_delta_mins": _minutes_between(before_start, after_start),
        "end_delta_mins": _minutes_between(before_end, after_end),
        "duration_delta_mins": (
            None
            if _duration_between(before_start, before_end) is None or _duration_between(after_start, after_end) is None
            else _duration_between(after_start, after_end) - _duration_between(before_start, before_end)
        ),
        "setup_time_delta_mins": after_setup - before_setup,
        "tardiness_delta_mins": after_tardiness - before_tardiness,
        "lock_machine": bool(after_state.get("lock_machine", after_state.get("manual_lock_machine", False))),
        "lock_time": bool(after_state.get("lock_time", after_state.get("manual_lock_time", False))),
    }


def _manual_adjustment_review_policy(settings: dict | None = None) -> dict[str, int]:
    settings = settings or {}
    return {
        "delay_threshold_mins": max(
            0,
            int(settings.get("delay_threshold_mins", settings.get("manual_adjust_review_delay_threshold_mins", 0)) or 0),
        ),
        "setup_threshold_mins": max(
            0,
            int(settings.get("setup_threshold_mins", settings.get("manual_adjust_review_setup_threshold_mins", 0)) or 0),
        ),
        "tardiness_threshold_mins": max(
            0,
            int(
                settings.get(
                    "tardiness_threshold_mins",
                    settings.get("manual_adjust_review_tardiness_threshold_mins", 0),
                )
                or 0
            ),
        ),
    }


ADJUSTMENT_REVIEW_REASON_DETAILS = {
    "end_delayed": {
        "code": "end_delayed",
        "label": "完工延后",
        "description": "调整后完工时间超过复核阈值。",
    },
    "setup_increased": {
        "code": "setup_increased",
        "label": "换产增加",
        "description": "调整后换产时间超过复核阈值。",
    },
    "tardiness_increased": {
        "code": "tardiness_increased",
        "label": "逾期增加",
        "description": "调整后逾期时间超过复核阈值。",
    },
}


ADJUSTMENT_REVIEW_REASON_EVIDENCE = {
    "end_delayed": ("end_delta_mins", "delay_threshold_mins"),
    "setup_increased": ("setup_time_delta_mins", "setup_threshold_mins"),
    "tardiness_increased": ("tardiness_delta_mins", "tardiness_threshold_mins"),
}


def _manual_adjustment_review_reason_details(
    reasons: list[str],
    impact: dict[str, Any],
    review_policy: dict[str, int],
) -> list[dict[str, Any]]:
    details = []
    for reason in reasons:
        impact_key, threshold_key = ADJUSTMENT_REVIEW_REASON_EVIDENCE[reason]
        details.append({
            **ADJUSTMENT_REVIEW_REASON_DETAILS[reason],
            "actual_delta_mins": int(impact.get(impact_key) or 0),
            "threshold_mins": int(review_policy.get(threshold_key) or 0),
        })
    return details


def _manual_adjustment_review_reason_summary(review_reasons: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for item in review_reasons or []:
        order_id = item.get("order_id")
        for detail in item.get("reason_details") or []:
            code = detail["code"]
            entry = summary.setdefault(code, {
                "code": code,
                "label": detail["label"],
                "count": 0,
                "order_ids": [],
                "max_actual_delta_mins": 0,
                "max_excess_mins": 0,
                "total_excess_mins": 0,
                "threshold_mins": detail["threshold_mins"],
            })
            excess_mins = int(detail.get("actual_delta_mins") or 0) - int(detail.get("threshold_mins") or 0)
            entry["count"] += 1
            if order_id:
                entry["order_ids"] = list(dict.fromkeys([*entry["order_ids"], order_id]))
                entry["affected_order_count"] = len(entry["order_ids"])
            entry["max_actual_delta_mins"] = max(
                entry["max_actual_delta_mins"],
                int(detail.get("actual_delta_mins") or 0),
            )
            entry["max_excess_mins"] = max(
                entry["max_excess_mins"],
                excess_mins,
            )
            entry["total_excess_mins"] += excess_mins
    return summary


def _manual_adjustment_impact_summary(
    adjustments: list[dict[str, Any]],
    review_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review_policy = _manual_adjustment_review_policy(review_policy)
    affected_order_ids = []
    negative_impact_order_ids = []
    review_reasons = []
    machine_change_count = 0
    time_changed_count = 0
    locked_after_adjustment_count = 0
    total_setup_time_delta_mins = 0
    total_tardiness_delta_mins = 0
    delay_deltas = []
    for item in adjustments or []:
        impact = item.get("impact") or {}
        order_id = item.get("order_id")
        if order_id:
            affected_order_ids.append(order_id)
        if impact.get("machine_changed"):
            machine_change_count += 1
        if (impact.get("start_delta_mins") or 0) != 0 or (impact.get("end_delta_mins") or 0) != 0:
            time_changed_count += 1
        if impact.get("lock_machine") or impact.get("lock_time"):
            locked_after_adjustment_count += 1
        total_setup_time_delta_mins += int(impact.get("setup_time_delta_mins") or 0)
        total_tardiness_delta_mins += int(impact.get("tardiness_delta_mins") or 0)
        reasons = []
        if int(impact.get("end_delta_mins") or 0) > review_policy["delay_threshold_mins"]:
            reasons.append("end_delayed")
        if int(impact.get("setup_time_delta_mins") or 0) > review_policy["setup_threshold_mins"]:
            reasons.append("setup_increased")
        if int(impact.get("tardiness_delta_mins") or 0) > review_policy["tardiness_threshold_mins"]:
            reasons.append("tardiness_increased")
        if order_id and reasons:
            negative_impact_order_ids.append(order_id)
            review_reasons.append({
                "order_id": order_id,
                "reasons": reasons,
                "reason_details": _manual_adjustment_review_reason_details(reasons, impact, review_policy),
            })
        for key in ("start_delta_mins", "end_delta_mins"):
            value = impact.get(key)
            if value is not None and int(value) > 0:
                delay_deltas.append(int(value))
    return {
        "adjustment_count": len(adjustments or []),
        "machine_change_count": machine_change_count,
        "time_changed_count": time_changed_count,
        "locked_after_adjustment_count": locked_after_adjustment_count,
        "total_setup_time_delta_mins": total_setup_time_delta_mins,
        "total_tardiness_delta_mins": total_tardiness_delta_mins,
        "max_delay_delta_mins": max(delay_deltas) if delay_deltas else 0,
        "has_negative_impact": bool(negative_impact_order_ids),
        "negative_impact_order_ids": negative_impact_order_ids,
        "review_required_count": len(negative_impact_order_ids),
        "review_required_order_ids": negative_impact_order_ids,
        "review_reasons": review_reasons,
        "review_reason_summary": _manual_adjustment_review_reason_summary(review_reasons),
        "review_policy": review_policy,
        "affected_order_ids": affected_order_ids,
    }


def _locked_task_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    locked_rows = [
        task for task in tasks or []
        if task.get("manual_lock_machine") or task.get("manual_lock_time")
    ]
    return {
        "locked_task_count": len(locked_rows),
        "machine_locked_count": sum(1 for task in locked_rows if task.get("manual_lock_machine")),
        "time_locked_count": sum(1 for task in locked_rows if task.get("manual_lock_time")),
        "protected_order_ids": [task.get("order_id") for task in locked_rows if task.get("order_id")],
        "protected_machine_ids": list(dict.fromkeys(
            task.get("machine_id") for task in locked_rows if task.get("machine_id")
        )),
    }


def _adjustment_reason_summary(adjustments: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    actor_counts: dict[str, int] = {}
    reason_texts: dict[str, str] = {}
    failed_adjustment_count = 0
    for item in adjustments or []:
        reason = item.get("reason_code") or "UNKNOWN"
        actor = item.get("changed_by") or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        actor_counts[actor] = actor_counts.get(actor, 0) + 1
        if item.get("reason_text") and reason not in reason_texts:
            reason_texts[reason] = item["reason_text"]
        if item.get("validation_status") == "FAILED":
            failed_adjustment_count += 1
    return {
        "adjustment_count": len(adjustments or []),
        "failed_adjustment_count": failed_adjustment_count,
        "reason_counts": reason_counts,
        "actor_counts": actor_counts,
        "reason_texts": reason_texts,
        "reason_items": [
            {
                "reason_code": reason,
                "count": count,
                "sample_reason_text": reason_texts.get(reason, ""),
            }
            for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def _locked_external_order_from_row(row: dict[str, Any]) -> ProductionOrderModel:
    return ProductionOrderModel(
        order_id=str(row.get("order_id")),
        product_type=str(row.get("product_type") or "LOCKED_EXTERNAL"),
        target_width=int(row.get("target_width") or 0),
        target_thickness=int(row.get("target_thickness") or 0),
        total_quantity_kg=int(row.get("total_quantity_kg") or 0),
        cleanroom_req=str(row.get("cleanroom_req") or "Class_100K"),
        customer_class=str(row.get("customer_class") or "STANDARD"),
        order_class=str(row.get("order_class") or "NORMAL"),
        corona_req=bool(row.get("corona_req") or False),
        core_size_inch=int(row.get("core_size_inch") or 3),
        due_date_mins=int(row.get("due_date_mins") or 0),
    )


def _locked_task_rows_to_solver_inputs(rows, orders, machines) -> list[ScheduledTask]:
    orders_by_id = {order.order_id: order for order in orders}
    machines_by_id = {machine.machine_id: machine for machine in machines}
    locked_tasks: list[ScheduledTask] = []
    for row in rows or []:
        machine = machines_by_id.get(row.get("machine_id"))
        if machine is None:
            continue
        order = orders_by_id.get(row.get("order_id")) or _locked_external_order_from_row(row)
        locked_tasks.append(ScheduledTask(
            order,
            machine,
            int(row.get("start_mins") or 0),
            int(row.get("end_mins") or 0),
            int(row.get("setup_time_mins") or 0),
            float(row.get("scrap_kg") or 0),
            int(row.get("sequence_index") or 0),
            manual_lock_machine=bool(row.get("manual_lock_machine")),
            manual_lock_time=bool(row.get("manual_lock_time")),
        ))
    return locked_tasks


def _load_preplan_locked_tasks(cur, orders, machines) -> list[ScheduledTask]:
    cur.execute("""
        SELECT DISTINCT ON (t.order_id)
            t.order_id, t.machine_id, t.start_mins, t.end_mins,
            t.setup_time_mins, t.scrap_kg, t.sequence_index,
            t.manual_lock_machine, t.manual_lock_time,
            o.product_type, o.target_width, o.target_thickness,
            o.total_quantity_kg, o.cleanroom_req, o.order_class,
            o.corona_req, o.core_size_inch,
            COALESCE(c.customer_class, 'STANDARD') AS customer_class
        FROM scheduled_tasks t
        JOIN schedule_runs r ON r.run_id=t.run_id
        LEFT JOIN production_orders o ON o.order_id=t.order_id
        LEFT JOIN customers c ON c.customer_id=o.customer_id
        WHERE COALESCE(r.lifecycle_status, 'CONFIRMED') IN ('VALIDATED', 'CONFIRMED')
          AND (COALESCE(t.manual_lock_machine, FALSE)=TRUE
               OR COALESCE(t.manual_lock_time, FALSE)=TRUE)
        ORDER BY t.order_id, r.run_id DESC, t.id DESC
    """)
    return _locked_task_rows_to_solver_inputs(cur.fetchall(), orders, machines)


def _queue_row_to_dict(row):
    last_transition = None
    if row.get("last_transition_created_at") or row.get("last_transition_details"):
        last_transition = {
            "actor": row.get("last_transition_actor"),
            "created_at": _iso(row.get("last_transition_created_at")),
            "details": _normalize_json(row.get("last_transition_details"), {}),
        }
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "scheduled_task_id": row["scheduled_task_id"],
        "order_id": row["order_id"],
        "machine_id": row["machine_id"],
        "sequence_index": row["sequence_index"],
        "planned_start_time": _iso(row["planned_start_time"]),
        "planned_end_time": _iso(row["planned_end_time"]),
        "queue_status": row["queue_status"],
        "released_by": row["released_by"],
        "released_at": _iso(row["released_at"]),
        "started_at": _iso(row.get("started_at")),
        "completed_at": _iso(row.get("completed_at")),
        "product_type": row.get("product_type"),
        "target_width": row.get("target_width"),
        "target_thickness": row.get("target_thickness"),
        "total_quantity_kg": row.get("total_quantity_kg"),
        "order_class": row.get("order_class"),
        "last_transition": last_transition,
    }


def _as_int(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _as_number(value, fallback=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _order_id_from_diagnostic(item):
    return item.get("entity_id") or item.get("order_id")


def _first_order_diagnostics(diagnostics):
    result = {}
    for item in diagnostics or []:
        if not isinstance(item, dict):
            continue
        if item.get("entity_type") != "order" and not item.get("order_id"):
            continue
        order_id = _order_id_from_diagnostic(item)
        if order_id and order_id not in result:
            result[order_id] = item
    return result


def _count_eligible_machines(order, machines):
    if not order:
        return 0
    recipe_layers = _as_int(order.get("recipe_layers"), 1)
    count = 0
    for machine in machines or []:
        if machine.get("status", "ACTIVE") != "ACTIVE":
            continue
        if order.get("cleanroom_req") == "Class_10K" and machine.get("cleanroom_level") == "Class_100K":
            continue
        width = order.get("target_width")
        if width is not None and not (_as_number(machine.get("min_width")) <= _as_number(width) <= _as_number(machine.get("max_width"))):
            continue
        thickness = order.get("target_thickness")
        if thickness is not None and not (_as_number(machine.get("min_thickness")) <= _as_number(thickness) <= _as_number(machine.get("max_thickness"))):
            continue
        if recipe_layers > _as_int(machine.get("layer_structure")):
            continue
        count += 1
    return count


def _preplan_order_base(order_id, order=None):
    source = order or {}
    row = {
        "order_id": order_id,
        "product_type": source.get("product_type"),
        "target_width": source.get("target_width"),
        "target_thickness": source.get("target_thickness"),
        "total_quantity_kg": source.get("total_quantity_kg"),
        "cleanroom_req": source.get("cleanroom_req"),
        "customer_class": source.get("customer_class"),
        "order_class": source.get("order_class"),
        "due_date": _iso(source.get("due_date")),
        "material_available_time": _iso(source.get("material_available_time")),
        "status": source.get("status"),
        "recipe_layers": source.get("recipe_layers"),
        "planning_bucket": source.get("planning_bucket"),
    }
    if source.get("applied_override"):
        row["applied_override"] = source.get("applied_override")
    return row


def _preplan_order_bucket_row(order_id, order=None, task=None, diagnostic=None, bucket="input", bucket_reason=""):
    row = _preplan_order_base(order_id, order)
    candidate_machine_count = _as_int((order or {}).get("candidate_machine_count"))
    eligible_machine_count = _as_int((order or {}).get("eligible_machine_count"))
    row.update({
        "bucket": bucket,
        "placement_status": bucket.upper(),
        "bucket_reason": bucket_reason,
        "candidate_machine_count": candidate_machine_count,
        "eligible_machine_count": eligible_machine_count,
    })
    if task:
        row.update({
            "scheduled_task_id": task.get("id"),
            "machine_id": task.get("machine_id"),
            "sequence_index": task.get("sequence_index"),
            "setup_start_time": task.get("setup_start_time"),
            "start_time": task.get("start_time"),
            "end_time": task.get("end_time"),
            "is_late": task.get("is_late"),
            "tardiness_mins": task.get("tardiness_mins"),
            "task_source": task.get("task_source"),
        })
    if diagnostic:
        row.update({
            "entity_type": diagnostic.get("entity_type", "order"),
            "entity_id": diagnostic.get("entity_id") or order_id,
            "severity": diagnostic.get("severity"),
            "category": diagnostic.get("category"),
            "code": diagnostic.get("code"),
            "display_title": diagnostic.get("display_title") or order_id,
            "confidence": diagnostic.get("confidence"),
            "root_cause": diagnostic.get("root_cause"),
            "evidence": diagnostic.get("evidence") or [],
            "recommendations": diagnostic.get("recommendations") or [],
            "diagnostic": diagnostic,
        })
    return row


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None
    return None


def _planning_bucket(order, policy=None):
    if not policy:
        return "must_schedule"
    due_date = _as_datetime((order or {}).get("due_date"))
    plan_start = _as_datetime(policy.get("plan_start"))
    if not due_date or not plan_start:
        return "must_schedule"
    if due_date.tzinfo is None and plan_start.tzinfo is not None:
        due_date = due_date.replace(tzinfo=plan_start.tzinfo)
    if plan_start.tzinfo is None and due_date.tzinfo is not None:
        plan_start = plan_start.replace(tzinfo=due_date.tzinfo)
    must_days = max(0, int(policy.get("must_schedule_horizon_days") or 0))
    candidate_days = max(must_days, int(policy.get("candidate_horizon_days") or must_days))
    if due_date <= plan_start + timedelta(days=must_days):
        return "must_schedule"
    if due_date <= plan_start + timedelta(days=candidate_days):
        return "candidate"
    return "deferred"


def _build_preplan_order_buckets(
    order_rows,
    machines,
    tasks,
    diagnostics,
    selected_order_ids,
    screening_items_by_order_id=None,
    planning_bucket_policy=None,
    deferred_order_items=None,
    unplaced_solver_failed_order_items=None,
):
    orders_by_id = {row["order_id"]: dict(row) for row in order_rows or []}
    screening_items_by_order_id = screening_items_by_order_id or {}
    deferred_items_by_order_id = {
        item.get("order_id"): item
        for item in deferred_order_items or []
        if item.get("order_id")
    }
    unplaced_items_by_order_id = {
        item.get("order_id"): item
        for item in unplaced_solver_failed_order_items or []
        if item.get("order_id")
    }
    task_by_order = {}
    for task in tasks or []:
        task_by_order.setdefault(task.get("order_id"), task)

    diagnostics_by_order = _first_order_diagnostics(diagnostics)
    ordered_ids = []
    for source in (selected_order_ids or []):
        if source and source not in ordered_ids:
            ordered_ids.append(source)
    for source in list(task_by_order) + list(diagnostics_by_order):
        if source and source not in ordered_ids:
            ordered_ids.append(source)

    input_orders = []
    scheduled_orders = []
    schedulable_orders = []
    unplaced_schedulable_orders = []
    blocked_orders = []
    late_orders = []
    must_schedule_orders = []
    candidate_orders = []
    deferred_orders = []
    unplaced_solver_failed_orders = []
    deferred_reason_counts = {}
    candidate_machine_count = len(machines or [])

    for order_id in ordered_ids:
        order = orders_by_id.get(order_id, {"order_id": order_id})
        screening_item = screening_items_by_order_id.get(order_id) or {}
        if screening_item.get("applied_override"):
            order["applied_override"] = screening_item.get("applied_override")
        order["candidate_machine_count"] = candidate_machine_count
        order["eligible_machine_count"] = _count_eligible_machines(order, machines)
        task = task_by_order.get(order_id)
        diagnostic = diagnostics_by_order.get(order_id)
        deferred_item = deferred_items_by_order_id.get(order_id)
        unplaced_item = unplaced_items_by_order_id.get(order_id)
        diagnostic_blocks = diagnostic and diagnostic.get("category") == "eligibility"
        planning_bucket = "blocked" if diagnostic_blocks or order["eligible_machine_count"] == 0 else _planning_bucket(order, planning_bucket_policy)
        order["planning_bucket"] = planning_bucket

        if diagnostic_blocks or order["eligible_machine_count"] == 0:
            bucket = "blocked"
            reason = (
                (diagnostic or {}).get("root_cause")
                or "订单没有满足硬能力约束的可用机台。"
            )
        elif task:
            bucket = "scheduled"
            reason = "已落位到预排程任务。"
        elif deferred_item:
            bucket = "deferred"
            reason = deferred_item.get("message") or deferred_item.get("reason") or "candidate_optional_rejected"
        elif unplaced_item:
            bucket = "unplaced_solver_failed"
            reason = unplaced_item.get("message") or unplaced_item.get("reason") or "required_order_unplaced"
        elif planning_bucket in {"candidate", "deferred"}:
            bucket = "deferred"
            reason = "订单未进入当前计划窗口，按策略推迟到候选或后续周期。"
        else:
            bucket = "unplaced_schedulable"
            reason = "订单满足硬能力约束，但当前草案未生成落位任务。"

        input_row = _preplan_order_bucket_row(order_id, order, task, diagnostic, bucket, reason)
        if deferred_item:
            input_row["deferred_reason_code"] = deferred_item.get("reason")
            input_row["deferred_reason"] = deferred_item
        elif bucket == "deferred":
            input_row["deferred_reason_code"] = "planning_window_deferred"
        if unplaced_item:
            input_row["unplaced_reason_code"] = unplaced_item.get("reason")
            input_row["unplaced_reason"] = unplaced_item
        input_orders.append(input_row)

        if bucket == "blocked":
            blocked_orders.append(input_row)
            continue

        if order["eligible_machine_count"] > 0:
            schedulable_orders.append(input_row)

        if planning_bucket == "must_schedule":
            must_schedule_orders.append(input_row)
        elif planning_bucket == "candidate":
            candidate_orders.append(input_row)

        if task:
            scheduled_row = _preplan_order_bucket_row(order_id, order, task, diagnostic, "scheduled", "已落位到预排程任务。")
            scheduled_orders.append(scheduled_row)
            if task.get("is_late") or _as_int(task.get("tardiness_mins")) > 0:
                late_orders.append(_preplan_order_bucket_row(order_id, order, task, diagnostic, "late", "计划完工时间晚于订单交期。"))
        else:
            if bucket == "deferred":
                deferred_orders.append(input_row)
                reason_code = input_row.get("deferred_reason_code") or "planning_window_deferred"
                deferred_reason_counts[reason_code] = deferred_reason_counts.get(reason_code, 0) + 1
            elif bucket == "unplaced_solver_failed":
                unplaced_solver_failed_orders.append(input_row)
            else:
                unplaced_schedulable_orders.append(input_row)

    return {
        "input_orders": input_orders,
        "scheduled_orders": scheduled_orders,
        "schedulable_orders": schedulable_orders,
        "unplaced_schedulable_orders": unplaced_schedulable_orders,
        "blocked_orders": blocked_orders,
        "late_orders": late_orders,
        "must_schedule_orders": must_schedule_orders,
        "candidate_orders": candidate_orders,
        "deferred_orders": deferred_orders,
        "deferred_reason_counts": deferred_reason_counts,
        "unplaced_solver_failed_orders": unplaced_solver_failed_orders,
    }


def _load_preplan_order_context(cur, run, tasks, diagnostics):
    params = _normalize_json(run.get("solver_params"), {}) or {}
    selected_ids = params.get("selected_order_ids") or []
    planning_snapshot = (params.get("policy_snapshot") or {}).get("planning_bucket") or {}
    planning_bucket_policy = None
    if planning_snapshot:
        planning_bucket_policy = {
            "plan_start": run.get("run_time"),
            "must_schedule_horizon_days": planning_snapshot.get("must_schedule_horizon_days"),
            "candidate_horizon_days": planning_snapshot.get("candidate_horizon_days"),
        }
    screening_items_by_order_id = {
        item.get("order_id"): item
        for item in (params.get("preplan_screening") or {}).get("items", [])
        if item.get("order_id")
    }
    diagnostics_by_order = _first_order_diagnostics(diagnostics)
    order_ids = []
    for source in selected_ids + [task.get("order_id") for task in tasks] + list(diagnostics_by_order):
        if source and source not in order_ids:
            order_ids.append(source)

    order_rows = []
    if order_ids:
        cur.execute("""
            SELECT o.order_id, o.product_type, o.target_width, o.target_thickness,
                o.total_quantity_kg, o.cleanroom_req, o.order_class, o.due_date,
                o.material_available_time, o.status,
                COALESCE(c.customer_class, 'STANDARD') AS customer_class,
                COALESCE(recipe_layers.layers, 1) AS recipe_layers
            FROM production_orders o
            LEFT JOIN customers c ON c.customer_id=o.customer_id
            LEFT JOIN (
                SELECT product_type, COUNT(*) AS layers
                FROM recipes
                GROUP BY product_type
            ) recipe_layers ON recipe_layers.product_type=o.product_type
            WHERE o.order_id = ANY(%s)
        """, (order_ids,))
        order_rows = cur.fetchall()

    cur.execute("""
        SELECT machine_id, status, cleanroom_level, layer_structure,
            min_width, max_width, min_thickness, max_thickness
        FROM machines
        WHERE status='ACTIVE'
        ORDER BY machine_id
    """)
    machines = cur.fetchall()
    return _build_preplan_order_buckets(
        order_rows,
        machines,
        tasks,
        diagnostics,
        selected_ids,
        screening_items_by_order_id=screening_items_by_order_id,
        planning_bucket_policy=planning_bucket_policy,
        deferred_order_items=params.get("deferred_orders") or [],
        unplaced_solver_failed_order_items=params.get("unplaced_solver_failed_orders") or [],
    )


def _validation_item(severity, code, message, order_id=None, machine_id=None, level=None):
    normalized_level = level
    if normalized_level is None:
        normalized_level = "publish_blocker" if severity == "error" else severity
    if normalized_level not in VALIDATION_LEVELS:
        normalized_level = "publish_blocker" if severity == "error" else "warning"
    normalized_severity = "error" if normalized_level in VALIDATION_BLOCKING_LEVELS else normalized_level
    return {
        "severity": normalized_severity,
        "level": normalized_level,
        "code": code,
        "message": message,
        "order_id": order_id,
        "machine_id": machine_id,
    }


def _validation_result_payload(run_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    hard_errors = [
        item for item in items
        if item.get("level") in VALIDATION_BLOCKING_LEVELS or item.get("severity") == "error"
    ]
    warnings = [
        item for item in items
        if item.get("level", item.get("severity")) == "warning"
    ]
    info_items = [
        item for item in items
        if item.get("level", item.get("severity")) == "info"
    ]
    return {
        "run_id": run_id,
        "status": "FAILED" if hard_errors else ("WARNING" if warnings else "PASSED"),
        "publishable": not hard_errors,
        "hard_error_count": len(hard_errors),
        "publish_blocker_count": len(hard_errors),
        "warning_count": len(warnings),
        "info_count": len(info_items),
        "items": items,
    }


def _validation_is_publishable(validation: dict[str, Any]) -> bool:
    return bool(validation.get("publishable", int(validation.get("hard_error_count") or 0) == 0))


def _raise_if_unpublishable(validation: dict[str, Any]) -> None:
    if _validation_is_publishable(validation):
        return
    raise HTTPException(
        status_code=400,
        detail={"message": "草案存在发布阻断，不能发布。", "validation": validation},
    )


def _diagnostic_validation_items(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for diagnostic in diagnostics or []:
        if diagnostic.get("code") != "maintenance.continuous_run_cleaning_required":
            continue
        level = diagnostic.get("level") or (
            "publish_blocker" if diagnostic.get("severity") == "critical" else "warning"
        )
        if level not in VALIDATION_LEVELS:
            level = "publish_blocker"
        items.append(_validation_item(
            "error" if level in VALIDATION_BLOCKING_LEVELS else level,
            diagnostic.get("code"),
            diagnostic.get("root_cause") or "连续运行清场规则未满足。",
            machine_id=diagnostic.get("entity_id"),
            level=level,
        ))
    return items


def _unplaced_solver_failed_validation_items(unplaced_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for order in unplaced_orders or []:
        order_id = order.get("order_id")
        if not order_id:
            continue
        code = order.get("reason") or "required_order_unplaced"
        message = order.get("message") or "Required order was not placed by the solver."
        items.append(_validation_item(
            "error",
            code,
            message,
            order_id=order_id,
            level="publish_blocker",
        ))
    return items


def _publish_audit_payload(
    *,
    event_type: str,
    run_id: int | None,
    actor: str,
    selected_order_count: int = 0,
    warning_count: int = 0,
    queue_row_count: int = 0,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "run_id": run_id,
        "actor": actor,
        "selected_order_count": int(selected_order_count or 0),
        "warning_count": int(warning_count or 0),
        "queue_row_count": int(queue_row_count or 0),
        "details": details or {},
    }


def _insert_publish_audit(cur, payload: dict[str, Any]) -> None:
    cur.execute("""
        INSERT INTO schedule_publish_audit
            (run_id, event_type, actor, selected_order_count,
             warning_count, queue_row_count, details)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        payload.get("run_id"),
        payload.get("event_type"),
        payload.get("actor"),
        payload.get("selected_order_count") or 0,
        payload.get("warning_count") or 0,
        payload.get("queue_row_count") or 0,
        Json(payload.get("details") or {}),
    ))


def _validation_summary_payload(validation: dict[str, Any], task_signature: str) -> dict[str, Any]:
    hard_error_count = int(validation.get("hard_error_count") or 0)
    publish_blocker_count = int(validation.get("publish_blocker_count") or hard_error_count)
    publishable = bool(validation.get("publishable", hard_error_count == 0))
    return {
        "valid": publishable,
        "publishable": publishable,
        "status": validation.get("status") or ("FAILED" if hard_error_count else "PASSED"),
        "hard_error_count": hard_error_count,
        "publish_blocker_count": publish_blocker_count,
        "warning_count": int(validation.get("warning_count") or 0),
        "info_count": int(validation.get("info_count") or 0),
        "validator_version": VALIDATION_SUMMARY_VERSION,
        "task_signature": task_signature,
        "validated_at": _utc_now_iso(),
    }


def _validation_summary_mismatch(
    summary: Optional[dict[str, Any]],
    validation: dict[str, Any],
    *,
    current_task_signature: str,
) -> Optional[str]:
    if not summary:
        return "当前草案缺少最近校验摘要，请重新校验方案。"
    if not summary.get("valid"):
        reason = summary.get("invalid_reason") or "validation_failed"
        return f"当前草案校验摘要已失效（{reason}），请重新校验方案。"
    if summary.get("validator_version") != VALIDATION_SUMMARY_VERSION:
        return "当前草案校验器版本已变化，请重新校验方案。"
    if summary.get("task_signature") != current_task_signature:
        return "当前草案任务已变化，请重新校验方案。"
    if int(summary.get("hard_error_count") or 0) != int(validation.get("hard_error_count") or 0):
        return "当前草案阻断错误数量已变化，请重新校验方案。"
    if int(summary.get("warning_count") or 0) != int(validation.get("warning_count") or 0):
        return "当前草案警告数量已变化，请重新校验方案。"
    return None


def _task_signature_value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _task_signature_from_rows(rows: list[dict[str, Any]]) -> str:
    payload = []
    for row in rows:
        payload.append({
            "id": row.get("id"),
            "order_id": row.get("order_id"),
            "machine_id": row.get("machine_id"),
            "sequence_index": row.get("sequence_index"),
            "setup_start_time": _task_signature_value(row.get("setup_start_time")),
            "start_time": _task_signature_value(row.get("start_time")),
            "end_time": _task_signature_value(row.get("end_time")),
            "task_source": row.get("task_source") or "AUTO",
            "manual_lock_machine": bool(row.get("manual_lock_machine")),
            "manual_lock_time": bool(row.get("manual_lock_time")),
        })
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _schedule_task_signature(cur, run_id: int) -> str:
    cur.execute("""
        SELECT id, order_id, machine_id, sequence_index, setup_start_time,
            start_time, end_time, task_source, manual_lock_machine,
            manual_lock_time
        FROM scheduled_tasks
        WHERE run_id=%s
        ORDER BY machine_id, start_time, sequence_index, order_id
    """, (run_id,))
    return _task_signature_from_rows(cur.fetchall())


def _load_validation_summary(cur, run_id: int) -> Optional[dict[str, Any]]:
    cur.execute("SELECT solver_params FROM schedule_runs WHERE run_id=%s", (run_id,))
    row = cur.fetchone()
    params = _normalize_solver_params(row["solver_params"] if row else None)
    summary = params.get("last_validation_summary")
    return summary if isinstance(summary, dict) else None


def _persist_validation_summary(cur, run_id: int, validation: dict[str, Any], task_signature: str) -> dict[str, Any]:
    cur.execute("SELECT solver_params FROM schedule_runs WHERE run_id=%s", (run_id,))
    row = cur.fetchone()
    params = _normalize_solver_params(row["solver_params"] if row else None)
    summary = _validation_summary_payload(validation, task_signature)
    params["last_validated_at"] = summary["validated_at"]
    params["last_validation_summary"] = summary
    cur.execute("UPDATE schedule_runs SET solver_params=%s WHERE run_id=%s", (Json(params), run_id))
    return summary


def _invalidate_validation_summary(cur, run_id: int, reason: str) -> None:
    cur.execute("SELECT solver_params FROM schedule_runs WHERE run_id=%s", (run_id,))
    row = cur.fetchone()
    params = _normalize_solver_params(row["solver_params"] if row else None)
    summary = params.get("last_validation_summary")
    if not isinstance(summary, dict):
        return
    summary = {
        **summary,
        "valid": False,
        "invalid_reason": reason,
        "invalidated_at": _utc_now_iso(),
    }
    params["last_validation_summary"] = summary
    cur.execute("UPDATE schedule_runs SET solver_params=%s WHERE run_id=%s", (Json(params), run_id))


QUEUE_ALLOWED_TRANSITIONS = {
    "QUEUED": {"READY", "ON_HOLD", "CANCELLED"},
    "READY": {"IN_PRODUCTION", "ON_HOLD", "CANCELLED"},
    "ON_HOLD": {"READY", "CANCELLED"},
    "IN_PRODUCTION": {"COMPLETED", "ON_HOLD"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def _validate_queue_transition(current_status: str, next_status: str, reason: str = "") -> None:
    current = (current_status or "").upper()
    target = (next_status or "").upper()
    if current not in QUEUE_ALLOWED_TRANSITIONS:
        raise HTTPException(status_code=400, detail="当前队列状态无效。")
    if target not in QUEUE_ALLOWED_TRANSITIONS:
        raise HTTPException(status_code=400, detail="目标队列状态无效。")
    if target == current:
        raise HTTPException(status_code=400, detail="目标状态与当前状态相同。")
    if target not in QUEUE_ALLOWED_TRANSITIONS[current]:
        raise HTTPException(status_code=400, detail=f"不允许从 {current} 切换到 {target}。")
    if target in {"ON_HOLD", "CANCELLED"} and not (reason or "").strip():
        raise HTTPException(status_code=400, detail="切换为暂停或取消必须填写原因。")


def _order_status_for_queue_status(queue_status: str) -> str | None:
    return {
        "QUEUED": "SCHEDULED",
        "READY": "SCHEDULED",
        "ON_HOLD": "SCHEDULED",
        "IN_PRODUCTION": "IN_PRODUCTION",
        "COMPLETED": "COMPLETED",
        "CANCELLED": "PENDING",
    }.get((queue_status or "").upper())


def _order_snapshot_value(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _order_snapshot_hash(snapshot: dict[str, Any]) -> str:
    fields = snapshot.get("fields") or {}
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _order_snapshot_from_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = {
        key: _order_snapshot_value(row.get(key))
        for key in ORDER_SNAPSHOT_FIELDS
    }
    snapshot = {
        "order_id": row.get("order_id"),
        "updated_at": _iso(row.get("updated_at")),
        "fields": fields,
    }
    snapshot["hash"] = _order_snapshot_hash(snapshot)
    return snapshot


def _normalize_order_snapshot_map(value) -> dict[str, dict[str, Any]]:
    if not value:
        return {}
    items: list[tuple[Any, dict[str, Any]]] = []
    if isinstance(value, dict):
        items = list(value.items())
    elif isinstance(value, list):
        items = [(item.get("order_id"), item) for item in value if isinstance(item, dict)]
    result: dict[str, dict[str, Any]] = {}
    for order_id, snapshot in items:
        if not order_id or not isinstance(snapshot, dict):
            continue
        normalized = dict(snapshot)
        normalized["order_id"] = order_id
        normalized.setdefault("fields", {})
        normalized["hash"] = normalized.get("hash") or _order_snapshot_hash(normalized)
        result[str(order_id)] = normalized
    return result


def _current_order_snapshot_map(cur, order_ids: list[str]) -> dict[str, dict[str, Any]]:
    order_ids = [order_id for order_id in dict.fromkeys(order_ids or []) if order_id]
    if not order_ids:
        return {}
    cur.execute("""
        SELECT order_id, product_type, target_width, target_thickness,
            total_quantity_kg, cleanroom_req, order_class, due_date,
            material_available_time, status, priority_override, updated_at
        FROM production_orders
        WHERE order_id = ANY(%s)
    """, (order_ids,))
    return {
        row["order_id"]: _order_snapshot_from_row(row)
        for row in cur.fetchall()
    }


def _screening_snapshot_for_input_snapshot(
    screening: dict[str, Any] | None,
    order_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    if screening:
        return build_screening_snapshot(screening)
    return {
        "count": len(order_snapshots or []),
        "hash": stable_hash([
            {"order_id": item.get("order_id"), "hash": item.get("hash")}
            for item in order_snapshots or []
        ]),
    }


def _current_input_snapshot(
    cur,
    order_snapshots: list[dict[str, Any]],
    screening: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cur.execute("""
        SELECT machine_id, status, cleanroom_level, layer_structure,
            die_diameter_mm, min_width, max_width, min_thickness,
            max_thickness, hourly_output_kg, max_slitting_lanes
        FROM machines
        WHERE status='ACTIVE'
        ORDER BY machine_id
    """)
    machine_snapshot = build_machine_capability_snapshot(cur.fetchall())

    cur.execute("""
        SELECT machine_id, start_time, end_time, maintenance_type,
            reason, is_enabled
        FROM machine_maintenance_calendar
        WHERE COALESCE(is_enabled, TRUE)=TRUE
        ORDER BY machine_id, start_time, end_time
    """)
    maintenance_snapshot = build_maintenance_calendar_snapshot(cur.fetchall())

    rule_rows = []
    cur.execute("""
        SELECT from_material, to_material, switch_time_mins, scrap_weight_kg,
            is_enabled
        FROM material_switch_matrix
        ORDER BY from_material, to_material
    """)
    for row in cur.fetchall():
        rule_rows.append({
            "table": "material_switch_matrix",
            "key": f"{row.get('from_material')}->{row.get('to_material')}",
            "values": {
                "switch_time_mins": row.get("switch_time_mins"),
                "scrap_weight_kg": row.get("scrap_weight_kg"),
            },
            "is_enabled": row.get("is_enabled"),
        })

    cur.execute("""
        SELECT attribute, condition_desc, threshold_lower, threshold_upper,
            change_time_mins, scrap_weight_kg, is_enabled
        FROM spec_change_rules
        ORDER BY attribute, condition_desc
    """)
    for row in cur.fetchall():
        rule_rows.append({
            "table": "spec_change_rules",
            "key": f"{row.get('attribute')}:{row.get('condition_desc')}",
            "values": {
                "threshold_lower": row.get("threshold_lower"),
                "threshold_upper": row.get("threshold_upper"),
                "change_time_mins": row.get("change_time_mins"),
                "scrap_weight_kg": row.get("scrap_weight_kg"),
            },
            "is_enabled": row.get("is_enabled"),
        })

    cur.execute("""
        SELECT from_order_class, to_order_class, clearance_time_mins,
            is_enabled
        FROM gmp_clearance_matrix
        ORDER BY from_order_class, to_order_class
    """)
    for row in cur.fetchall():
        rule_rows.append({
            "table": "gmp_clearance_matrix",
            "key": f"{row.get('from_order_class')}->{row.get('to_order_class')}",
            "values": {
                "clearance_time_mins": row.get("clearance_time_mins"),
            },
            "is_enabled": row.get("is_enabled"),
        })
    rule_snapshot = build_rule_matrix_snapshot(rule_rows)

    cur.execute("""
        SELECT product_type, layer, material_grade, ratio_pct
        FROM recipes
        ORDER BY product_type, layer
    """)
    process_snapshot = build_process_snapshot(cur.fetchall())

    screening_snapshot = _screening_snapshot_for_input_snapshot(screening, order_snapshots)
    return build_input_snapshot(
        order_snapshots=order_snapshots,
        machine_capability_snapshot=machine_snapshot,
        maintenance_calendar_snapshot=maintenance_snapshot,
        rule_matrix_snapshot=rule_snapshot,
        process_snapshot=process_snapshot,
        screening_snapshot=screening_snapshot,
    )


def _snapshot_changed_fields(before_fields: dict[str, Any], after_fields: dict[str, Any]) -> list[str]:
    changed = []
    keys = set(before_fields) | set(after_fields)
    for key in sorted(keys):
        if _order_snapshot_value(before_fields.get(key)) != _order_snapshot_value(after_fields.get(key)):
            changed.append(key)
    return changed


def _stale_order_snapshot_items(saved_snapshots, current_snapshots):
    saved_map = _normalize_order_snapshot_map(saved_snapshots)
    current_map = _normalize_order_snapshot_map(current_snapshots)
    items = []
    for order_id, saved in saved_map.items():
        current = current_map.get(order_id)
        if not current:
            item = _validation_item(
                "error",
                "order_snapshot_missing",
                f"订单 {order_id} 的当前快照缺失，请重新生成草案。",
                order_id,
            )
            item["changed_fields"] = list(saved.get("fields", {}).keys())
            items.append(item)
            continue
        if saved.get("hash") == current.get("hash"):
            continue
        changed_fields = _snapshot_changed_fields(saved.get("fields", {}), current.get("fields", {}))
        item = _validation_item(
            "error",
            "order_snapshot_stale",
            f"订单 {order_id} 的调度关键字段已变化，请重新生成草案。",
            order_id,
        )
        item["changed_fields"] = changed_fields
        item["saved_updated_at"] = saved.get("updated_at")
        item["current_updated_at"] = current.get("updated_at")
        items.append(item)
    return items


def _task_busy_start(task):
    return task.get("setup_start_time") or task.get("start_time")


def _task_busy_end(task):
    return task.get("end_time")


def _calculate_candidate_setup_start(
    run_id: int,
    order_id: str,
    machine_id: str,
    start_time: datetime,
    setup_rules_enabled: bool = True,
):
    if not setup_rules_enabled:
        return start_time

    from src.database import DatabaseManager

    with DatabaseManager() as manager:
        machines, orders, _, setup_mgr = manager.load_master_data(
            order_statuses=("PENDING", "SCHEDULED"),
        )
        machine_map = {machine.machine_id: machine for machine in machines}
        order_map = {order.order_id: order for order in orders}
        machine = machine_map.get(machine_id)
        order = order_map.get(order_id)
        if not machine or not order:
            return start_time

        with manager.conn.cursor() as cur:
            cur.execute("""
                SELECT order_id, start_time, sequence_index, id
                FROM scheduled_tasks
                WHERE run_id=%s AND machine_id=%s AND order_id<>%s
                ORDER BY start_time, sequence_index, id
            """, (run_id, machine_id, order_id))
            rows = cur.fetchall()

    prev_order = None
    naive_start = _as_naive(start_time)
    for row in rows:
        row_start = row[1]
        if _as_naive(row_start) <= naive_start:
            prev_order = order_map.get(row[0])
        else:
            break
    setup_mins = SetupCalculator(setup_mgr).calculate_setup_time(prev_order, order, machine)
    return start_time - timedelta(minutes=setup_mins)


def _manual_adjustment_policy_items(ctx, payload: ManualAdjustmentPayload, settings: dict) -> list[dict[str, Any]]:
    messages = []
    if ctx["status"] != "PENDING":
        messages.append(_validation_item("error", "order_status", f"订单 {payload.order_id} 当前状态为 {ctx['status']}。", payload.order_id, payload.machine_id))
    if ctx["machine_status"] != "ACTIVE":
        messages.append(_validation_item("error", "machine_status", f"机台 {payload.machine_id} 当前状态为 {ctx['machine_status']}。", payload.order_id, payload.machine_id))
    if settings["machine_capability_constraint_enabled"]:
        if not (ctx["min_width"] <= ctx["target_width"] <= ctx["max_width"]):
            messages.append(_validation_item("error", "width_capacity", "订单幅宽不在机台能力范围。", payload.order_id, payload.machine_id))
        if not (ctx["min_thickness"] <= ctx["target_thickness"] <= ctx["max_thickness"]):
            messages.append(_validation_item("error", "thickness_capacity", "订单厚度不在机台能力范围。", payload.order_id, payload.machine_id))
        if ctx["recipe_layers"] and ctx["recipe_layers"] > ctx["layer_structure"]:
            messages.append(_validation_item("error", "layer_capacity", "订单配方层数超过机台能力。", payload.order_id, payload.machine_id))
    if settings["cleanroom_constraint_enabled"] and ctx["cleanroom_req"] == "Class_10K" and ctx["cleanroom_level"] != "Class_10K":
        messages.append(_validation_item("error", "cleanroom_capacity", "机台洁净等级不满足订单要求。", payload.order_id, payload.machine_id))
    if settings["material_constraint_enabled"] and ctx["material_available_time"] and _as_naive(payload.start_time) < _as_naive(ctx["material_available_time"]):
        messages.append(_validation_item("error", "material_not_ready", "计划开工早于物料齐套时间。", payload.order_id, payload.machine_id))
    return messages


def _recalculate_machine_setup_fields(db, run_id: int, machine_ids: list[str]):
    machine_ids = sorted({machine_id for machine_id in machine_ids if machine_id})
    if not machine_ids:
        return

    from src.database import DatabaseManager

    with DatabaseManager() as manager:
        machines, orders, _, setup_mgr = manager.load_master_data(
            order_statuses=("PENDING", "SCHEDULED"),
        )
    machine_map = {machine.machine_id: machine for machine in machines}
    order_map = {order.order_id: order for order in orders}
    setup_calc = SetupCalculator(setup_mgr)

    cur = db.cursor()
    cur.execute("""
        SELECT id, order_id, machine_id, start_time, end_time
        FROM scheduled_tasks
        WHERE run_id=%s AND machine_id = ANY(%s)
        ORDER BY machine_id, start_time, sequence_index, id
    """, (run_id, machine_ids))
    rows_by_machine = {}
    for row in cur.fetchall():
        rows_by_machine.setdefault(row["machine_id"], []).append(row)

    for machine_id, rows in rows_by_machine.items():
        machine = machine_map.get(machine_id)
        if not machine:
            continue
        prev_order = None
        prev_order_id = None
        for sequence, row in enumerate(rows):
            order = order_map.get(row["order_id"])
            if not order:
                prev_order = None
                prev_order_id = None
                continue
            setup_mins = setup_calc.calculate_setup_time(prev_order, order, machine)
            setup_detail = setup_calc.calculate_setup_detail(prev_order, order, machine)
            scrap_kg = setup_calc.calculate_scrap_weight(prev_order, order, machine)
            setup_start_time = row["start_time"] - timedelta(minutes=setup_mins)
            cur.execute("""
                UPDATE scheduled_tasks
                SET sequence_index=%s,
                    setup_start_time=%s,
                    setup_time_mins=%s,
                    scrap_kg=%s,
                    actual_material_required_kg=%s,
                    prev_order_id=%s,
                    setup_detail=%s
                WHERE id=%s
            """, (
                sequence,
                setup_start_time,
                setup_mins,
                scrap_kg,
                order.total_quantity_kg + scrap_kg,
                prev_order_id,
                Json(setup_detail),
                row["id"],
            ))
            prev_order = order
            prev_order_id = order.order_id


def _load_preplan_validation(db, run_id: int):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute(
        "SELECT lifecycle_status, status, total_orders, solver_params "
        "FROM schedule_runs WHERE run_id=%s",
        (run_id,),
    )
    run_row = cur.fetchone()
    lifecycle_status = run_row["lifecycle_status"] if run_row else "DRAFT"
    cur.execute("""
        SELECT t.*, o.status AS order_status, o.target_width, o.target_thickness,
            o.cleanroom_req, o.material_available_time, o.due_date,
            m.status AS machine_status, m.min_width, m.max_width,
            m.min_thickness, m.max_thickness, m.cleanroom_level,
            m.layer_structure,
            COALESCE(recipe_layers.layers, 0) AS recipe_layers
        FROM scheduled_tasks t
        JOIN production_orders o ON o.order_id=t.order_id
        JOIN machines m ON m.machine_id=t.machine_id
        LEFT JOIN (
            SELECT product_type, COUNT(*) AS layers
            FROM recipes
            GROUP BY product_type
        ) recipe_layers ON recipe_layers.product_type=o.product_type
        WHERE t.run_id=%s
        ORDER BY t.machine_id, t.start_time, t.sequence_index
    """, (run_id,))
    tasks = cur.fetchall()
    items = []

    params = _normalize_json(run_row.get("solver_params") if run_row else None, {}) or {}
    items.extend(_diagnostic_validation_items(params.get("diagnostics") or []))
    items.extend(_unplaced_solver_failed_validation_items(params.get("unplaced_solver_failed_orders") or []))
    summary = params.get("summary") or {}
    selected_ids = params.get("selected_order_ids") or []
    saved_snapshots = params.get("order_snapshots") or []
    saved_input_snapshot = params.get("input_snapshot")
    settings = _get_schedule_settings(db)
    if lifecycle_status in {"DRAFT", "VALIDATED"}:
        current_policy_snapshot = _policy_snapshot(settings, _load_rule_state_counts(db))
        policy_item = _policy_snapshot_validation_item(params.get("policy_snapshot"), current_policy_snapshot)
        if policy_item:
            items.append(policy_item)
    input_count = summary.get("input_order_count")
    if input_count is None:
        input_count = len(selected_ids) if selected_ids else (run_row.get("total_orders") if run_row else len(tasks))
    blocked_count = summary.get("blocked_order_count")
    if blocked_count is None:
        blocked_count = max(0, int(input_count or 0) - len(tasks))
    if (run_row and run_row.get("status") == "PARTIAL") or int(blocked_count or 0) > 0:
        items.append(_validation_item(
            "warning",
            "partial_schedule",
            f"本轮输入 {int(input_count or 0)} 单，已排 {len(tasks)} 单，"
            f"{int(blocked_count or 0)} 单未进入草案；发布后未排订单仍保留待排。",
        ))

    current_snapshots = _current_order_snapshot_map(cur, selected_ids)
    if selected_ids and not _normalize_order_snapshot_map(saved_snapshots) and lifecycle_status in {"DRAFT", "VALIDATED"}:
        items.append(_validation_item(
            "warning",
            "order_snapshot_missing",
            "旧草案未保存订单快照，请重新生成草案以获得完整校验。",
        ))
    elif saved_snapshots:
        items.extend(_stale_order_snapshot_items(saved_snapshots, current_snapshots))

    if lifecycle_status in {"DRAFT", "VALIDATED"} and selected_ids:
        if not saved_input_snapshot:
            items.append(_validation_item(
                "warning",
                "input_snapshot_missing",
                "旧草案未保存输入快照，请重新生成草案以获得完整校验。",
            ))
        else:
            current_input_snapshot = _current_input_snapshot(
                cur,
                list(current_snapshots.values()),
                params.get("preplan_screening"),
            )
            input_item = _input_snapshot_validation_item(saved_input_snapshot, current_input_snapshot)
            if input_item:
                items.append(input_item)

    seen_orders = set()
    for task in tasks:
        order_id = task["order_id"]
        machine_id = task["machine_id"]
        if order_id in seen_orders:
            items.append(_validation_item("error", "duplicate_order", f"订单 {order_id} 在草案中出现多次。", order_id, machine_id))
        seen_orders.add(order_id)
        if task["start_time"] >= task["end_time"]:
            items.append(_validation_item("error", "invalid_time", f"订单 {order_id} 开始时间必须早于结束时间。", order_id, machine_id))
        if lifecycle_status in {"DRAFT", "VALIDATED"} and task["order_status"] != "PENDING":
            items.append(_validation_item("error", "order_status", f"订单 {order_id} 当前状态为 {task['order_status']}，不能发布到制造队列。", order_id, machine_id))
        if task["machine_status"] != "ACTIVE":
            items.append(_validation_item("error", "machine_status", f"机台 {machine_id} 当前状态为 {task['machine_status']}。", order_id, machine_id))
        if settings["machine_capability_constraint_enabled"] and not (task["min_width"] <= task["target_width"] <= task["max_width"]):
            items.append(_validation_item("error", "width_capacity", f"订单 {order_id} 幅宽 {task['target_width']}mm 不在机台 {machine_id} 范围 {task['min_width']}-{task['max_width']}mm。", order_id, machine_id))
        if settings["machine_capability_constraint_enabled"] and not (task["min_thickness"] <= task["target_thickness"] <= task["max_thickness"]):
            items.append(_validation_item("error", "thickness_capacity", f"订单 {order_id} 厚度 {task['target_thickness']}um 不在机台 {machine_id} 范围 {task['min_thickness']}-{task['max_thickness']}um。", order_id, machine_id))
        if settings["cleanroom_constraint_enabled"] and task["cleanroom_req"] == "Class_10K" and task["cleanroom_level"] != "Class_10K":
            items.append(_validation_item("error", "cleanroom_capacity", f"订单 {order_id} 需要万级洁净，机台 {machine_id} 不满足。", order_id, machine_id))
        if settings["machine_capability_constraint_enabled"] and task["recipe_layers"] and task["recipe_layers"] > task["layer_structure"]:
            items.append(_validation_item("error", "layer_capacity", f"订单 {order_id} 配方 {task['recipe_layers']} 层超过机台 {machine_id} {task['layer_structure']} 层能力。", order_id, machine_id))
        if settings["material_constraint_enabled"] and task["material_available_time"] and task["start_time"] < task["material_available_time"]:
            items.append(_validation_item("error", "material_not_ready", f"订单 {order_id} 计划开工早于物料齐套时间。", order_id, machine_id))
        if task["end_time"] > task["due_date"]:
            items.append(_validation_item("warning", "late_order", f"订单 {order_id} 计划完工晚于交期。", order_id, machine_id))
        if task.get("task_source") in {"MANUAL", "ADJUSTED"}:
            items.append(_validation_item("warning", "manual_adjustment", f"订单 {order_id} 由人工调整，需复核换产和现场原因。", order_id, machine_id))

    for task in tasks:
        busy_start = _task_busy_start(task)
        busy_end = _task_busy_end(task)
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM scheduled_tasks other
            WHERE other.run_id=%s
              AND other.machine_id=%s
              AND other.id<>%s
              AND COALESCE(other.setup_start_time, other.start_time) < %s
              AND other.end_time > %s
        """, (run_id, task["machine_id"], task["id"], busy_end, busy_start))
        if cur.fetchone()["cnt"]:
            items.append(_validation_item("error", "task_overlap", f"机台 {task['machine_id']} 存在生产或换产时间重叠。", task["order_id"], task["machine_id"]))

        if settings["maintenance_constraint_enabled"]:
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM machine_maintenance_calendar m
                WHERE m.machine_id=%s
                  AND m.start_time < %s
                  AND m.end_time > %s
                  AND COALESCE(m.is_enabled, TRUE)=TRUE
            """, (task["machine_id"], busy_end, busy_start))
            if cur.fetchone()["cnt"]:
                items.append(_validation_item("error", "maintenance_overlap", f"订单 {task['order_id']} 的生产或换产时间与机台 {task['machine_id']} 维护窗口冲突。", task["order_id"], task["machine_id"]))

        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM machine_downtime_events d
            WHERE d.machine_id=%s
              AND d.start_time < %s
              AND COALESCE(d.end_time, %s) > %s
        """, (task["machine_id"], busy_end, busy_end, busy_start))
        if cur.fetchone()["cnt"]:
            items.append(_validation_item("error", "downtime_overlap", f"订单 {task['order_id']} 的生产或换产时间与机台 {task['machine_id']} 停机事件冲突。", task["order_id"], task["machine_id"]))

    return _validation_result_payload(run_id, items)


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
            DiagnosticRecommendation("review_maintenance", "检查维护窗口", "/config?tab=rules&section=maintenance"),
            DiagnosticRecommendation("review_gantt", "查看机台甘特图", f"/gantt?machine={machine_id}"),
        ]
    elif prev_event and prev_event.get("kind") == "maintenance":
        code = "idle.after_maintenance"
        confidence = "proven"
        recommendations = [
            DiagnosticRecommendation("review_maintenance", "检查维护窗口", "/config?tab=rules&section=maintenance"),
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
            "/config?tab=rules&section=maintenance",
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
            t.setup_time_mins, t.setup_detail, t.duration_mins, t.scrap_kg,
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
            "setup_detail": _normalize_json(r.get("setup_detail"), {}) or {},
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
        """
        SELECT machine_id, start_time, end_time, reason, maintenance_type
        FROM (
            SELECT DISTINCT ON (
                machine_id, start_time, end_time, maintenance_type,
                COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                COALESCE(recurrence_rule, '')
            )
                machine_id, start_time, end_time, reason, maintenance_type
            FROM machine_maintenance_calendar
            ORDER BY
                machine_id, start_time, end_time, maintenance_type,
                COALESCE(reason, ''), COALESCE(is_recurring, FALSE),
                COALESCE(recurrence_rule, ''), id
        ) deduped
        ORDER BY machine_id, start_time
        """
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


@router.get("/settings")
def get_schedule_settings(db=Depends(get_db), _=Depends(get_current_user)):
    return _get_schedule_settings(db)


@router.patch("/settings")
def update_schedule_settings(
    payload: ScheduleSettingsPayload,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No settings to update.")
    change_reason = _require_policy_change_reason(fields.pop("change_reason", None))
    allowed = set(POLICY_SETTING_KEYS) | set(POLICY_VALUE_KEYS)
    assignments = []
    params = []
    for key, value in fields.items():
        if key in POLICY_SETTING_KEYS:
            assignments.append(f"{key}=%s")
            params.append(bool(value))
        elif key == "continuous_run_limit_mins":
            assignments.append(f"{key}=%s")
            params.append(max(1, int(value)))
        elif key == "phase2_feasible_tardiness_tolerance_mins":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "solver_profile":
            profile = str(value or "standard")
            if profile not in {"fast", "standard", "deep"}:
                raise HTTPException(status_code=400, detail="Invalid solver profile.")
            assignments.append(f"{key}=%s")
            params.append(profile)
        elif key == "solver_time_limit_seconds":
            assignments.append(f"{key}=%s")
            params.append(max(0.1, float(value)))
        elif key == "solver_relative_gap_limit":
            assignments.append(f"{key}=%s")
            params.append(max(0.0, float(value)))
        elif key == "solver_random_seed":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "solver_num_workers":
            assignments.append(f"{key}=%s")
            params.append(max(1, int(value)))
        elif key == "solver_log_search_progress":
            assignments.append(f"{key}=%s")
            params.append(bool(value))
        elif key == "planning_must_schedule_horizon_days":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "planning_candidate_horizon_days":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "candidate_reject_penalty":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "candidate_max_deferred_count":
            assignments.append(f"{key}=%s")
            params.append(None if value is None else max(0, int(value)))
        elif key == "candidate_min_acceptance_ratio":
            assignments.append(f"{key}=%s")
            params.append(min(1.0, max(0.0, float(value or 0.0))))
        elif key == "arc_pruning_enabled":
            assignments.append(f"{key}=%s")
            params.append(bool(value))
        elif key == "arc_pruning_max_setup_mins":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "arc_pruning_top_k_per_order":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "screening_due_risk_min_slack_mins":
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "screening_due_risk_duration_multiplier":
            assignments.append(f"{key}=%s")
            params.append(max(0.0, float(value)))
        elif key == "screening_allowed_order_statuses":
            statuses = _policy_list({key: value}, key, transform=str.upper)
            assignments.append(f"{key}=%s")
            params.append(statuses)
        elif key in {"screening_prohibited_override_codes", "screening_restricted_override_codes"}:
            codes = _policy_list({key: value}, key)
            assignments.append(f"{key}=%s")
            params.append(codes)
        elif key == "screening_required_positive_order_fields":
            fields = _policy_list({key: value}, key)
            assignments.append(f"{key}=%s")
            params.append(fields)
        elif key in {
            "manual_adjust_review_delay_threshold_mins",
            "manual_adjust_review_setup_threshold_mins",
            "manual_adjust_review_tardiness_threshold_mins",
        }:
            assignments.append(f"{key}=%s")
            params.append(max(0, int(value)))
        elif key == "continuous_run_enforcement_mode":
            mode = str(value or "publish_blocker")
            if mode not in {"hard", "publish_blocker", "experimental_disabled"}:
                raise HTTPException(status_code=400, detail="Invalid continuous run enforcement mode.")
            assignments.append(f"{key}=%s")
            params.append(mode)
    if not assignments:
        raise HTTPException(status_code=400, detail="No valid settings to update.")
    _ensure_planning_schema(db)
    cur = db.cursor()
    before = _get_schedule_settings(db)
    assignments.extend(["policy_version=policy_version+1", "updated_by=%s", "change_reason=%s"])
    params.extend([_.username, change_reason])
    cur.execute(
        f"UPDATE schedule_settings SET {', '.join(assignments)}, updated_at=NOW() WHERE id=TRUE",
        params,
    )
    after = _get_schedule_settings(db)
    cur.execute("""
        INSERT INTO config_change_audit
            (config_scope, config_key, entity_id, before_state, after_state, changed_by, reason_text)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        "schedule_policy",
        ",".join(sorted(fields)),
        "global",
        Json(_json_safe(before)),
        Json(_json_safe(after)),
        _.username,
        change_reason,
    ))
    _ensure_order_screening_schema(db)
    _mark_order_screening_cache_stale(cur, reason="schedule_policy_changed")
    db.commit()
    return after


@router.get("/config-audit")
def get_config_audit(limit: int = 50, db=Depends(get_db), _=Depends(get_current_user)):
    _ensure_planning_schema(db)
    safe_limit = max(1, min(int(limit or 50), 200))
    cur = db.cursor()
    cur.execute("""
        SELECT id, config_scope, config_key, entity_id, before_state,
            after_state, changed_by, reason_text, created_at
        FROM config_change_audit
        ORDER BY created_at DESC, id DESC
        LIMIT %s
    """, (safe_limit,))
    return [_config_audit_row_to_dict(row) for row in cur.fetchall()]


@router.post("/preplans")
def create_preplan(
    payload: PreplanCreatePayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    order_ids = [item.strip() for item in payload.order_ids if item and item.strip()]
    order_ids = list(dict.fromkeys(order_ids))
    if not order_ids:
        raise HTTPException(status_code=400, detail="请选择至少一条待排订单。")
    mode = payload.mode.upper()
    if mode not in {"AUTO", "MANUAL", "HYBRID"}:
        raise HTTPException(status_code=400, detail="Invalid preplan mode.")

    _ensure_planning_schema(db)
    _ensure_order_screening_override_schema(db)
    cur = db.cursor()
    cur.execute(
        """
        SELECT order_id, status
        FROM production_orders
        WHERE order_id = ANY(%s)
        """,
        (order_ids,),
    )
    found = {row["order_id"]: row["status"] for row in cur.fetchall()}
    missing = [order_id for order_id in order_ids if order_id not in found]
    blocked = [order_id for order_id, status in found.items() if status != "PENDING"]
    if missing:
        raise HTTPException(status_code=404, detail=f"订单不存在: {', '.join(missing[:5])}")
    if blocked:
        raise HTTPException(status_code=400, detail=f"只有待排订单可以创建预排程: {', '.join(blocked[:5])}")

    settings = _get_schedule_settings(db)
    policy_snapshot = _policy_snapshot(settings, _load_rule_state_counts(db))
    from src.database import DatabaseManager

    with DatabaseManager() as manager:
        manager.ensure_planning_schema()
        machines, orders, _, setup_mgr = manager.load_master_data(
            order_ids=order_ids,
            order_statuses=("PENDING",),
        )
        loaded_ids = {order.order_id for order in orders}
        not_loaded = [order_id for order_id in order_ids if order_id not in loaded_ids]
        if not_loaded:
            raise HTTPException(status_code=400, detail=f"订单未进入排程输入: {', '.join(not_loaded[:5])}")
        screening = screen_orders(
            orders,
            machines,
            status_by_order_id={order_id: "PENDING" for order_id in order_ids},
            scope="preplan",
            screening_policy=_order_screening_policy(settings),
        )
        override_audits = _load_latest_formal_screening_overrides(cur, order_ids)
        _raise_for_blocked_preplan_orders(screening, override_audits)
        aps = _build_scheduler(setup_mgr, settings)
        locked_tasks = _load_preplan_locked_tasks(cur, orders, machines)
        result = aps.run(orders, machines, locked_tasks=locked_tasks)
        run_id = manager.save_schedule_result(
            result,
            triggered_by=user.username,
            activate=False,
            allow_invalid=True,
            publish_orders=False,
            mode=mode,
            lifecycle_status="DRAFT",
            selected_order_ids=order_ids,
            policy_snapshot=policy_snapshot,
            screening_snapshot=screening,
            input_screening_snapshot=build_screening_snapshot(screening),
        )

    if settings["auto_release_enabled"] and not settings["review_required"]:
        confirm_preplan(run_id=run_id, db=db, user=user)

    return get_preplan(run_id=run_id, db=db, _=user)


@router.get("/preplans")
def list_preplans(db=Depends(get_db), _=Depends(get_current_user)):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT run_id, run_time, baseline_time, triggered_by, status,
            total_orders, total_machines_used, total_setup_time_mins,
            total_scrap_kg, total_late_orders, is_active, solver_params,
            mode, lifecycle_status, confirmed_by, confirmed_at,
            cancelled_by, cancelled_at, cancel_reason
        FROM schedule_runs
        WHERE lifecycle_status IN ('DRAFT', 'VALIDATED', 'CONFIRMED', 'CANCELLED')
        ORDER BY run_id DESC
        LIMIT 30
    """)
    return [_run_row_to_dict(row) for row in cur.fetchall()]


@router.get("/preplans/{run_id}")
def get_preplan(run_id: int, db=Depends(get_db), _=Depends(get_current_user)):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT run_id, run_time, baseline_time, triggered_by, status,
            total_orders, total_machines_used, total_setup_time_mins,
            total_scrap_kg, total_late_orders, is_active, solver_params,
            mode, lifecycle_status, confirmed_by, confirmed_at,
            cancelled_by, cancelled_at, cancel_reason
        FROM schedule_runs
        WHERE run_id=%s
    """, (run_id,))
    run = cur.fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Preplan not found.")
    run_params = _normalize_json(run.get("solver_params"), {}) or {}
    review_policy = (run_params.get("policy_snapshot") or {}).get("manual_adjustment_review")
    if not review_policy:
        review_policy = _manual_adjustment_review_policy(_get_schedule_settings(db))
    cur.execute("""
        SELECT t.*, o.product_type, o.target_width, o.target_thickness,
            o.total_quantity_kg, o.order_class, o.due_date
        FROM scheduled_tasks t
        JOIN production_orders o ON o.order_id=t.order_id
        WHERE t.run_id=%s
        ORDER BY t.machine_id, t.start_time, t.sequence_index
    """, (run_id,))
    tasks = [_task_row_to_dict(row) for row in cur.fetchall()]
    cur.execute("""
        SELECT id, order_id, action_type, before_state, after_state,
            reason_code, reason_text, changed_by, changed_at,
            validation_status, validation_messages
        FROM schedule_adjustment_audit
        WHERE run_id=%s
        ORDER BY changed_at DESC, id DESC
        LIMIT 50
    """, (run_id,))
    adjustments = []
    for row in cur.fetchall():
        before_state = _normalize_json(row["before_state"], {})
        after_state = _normalize_json(row["after_state"], {})
        adjustments.append({
            "id": row["id"],
            "order_id": row["order_id"],
            "action_type": row["action_type"],
            "before_state": before_state,
            "after_state": after_state,
            "impact": _manual_adjustment_impact(before_state, after_state),
            "reason_code": row["reason_code"],
            "reason_text": row["reason_text"],
            "changed_by": row["changed_by"],
            "changed_at": _iso(row["changed_at"]),
            "validation_status": row["validation_status"],
            "validation_messages": _normalize_json(row["validation_messages"], []),
        })
    cur.execute("""
        SELECT id, run_id, event_type, actor, selected_order_count,
            warning_count, queue_row_count, details, created_at
        FROM schedule_publish_audit
        WHERE run_id=%s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """, (run_id,))
    publish_audit_row = cur.fetchone()
    latest_publish_audit = None
    if publish_audit_row:
        latest_publish_audit = {
            "id": publish_audit_row["id"],
            "run_id": publish_audit_row["run_id"],
            "event_type": publish_audit_row["event_type"],
            "actor": publish_audit_row["actor"],
            "selected_order_count": publish_audit_row["selected_order_count"],
            "warning_count": publish_audit_row["warning_count"],
            "queue_row_count": publish_audit_row["queue_row_count"],
            "details": _normalize_json(publish_audit_row["details"], {}),
            "created_at": _iso(publish_audit_row["created_at"]),
        }
    validation = _load_preplan_validation(db, run_id)
    diagnostics = _load_persisted_diagnostics(cur, run_id)
    order_buckets = _load_preplan_order_context(cur, run, tasks, diagnostics)
    return {
        "run": _run_row_to_dict(run),
        "tasks": tasks,
        "validation": validation,
        "adjustments": adjustments,
        "adjustment_impact_summary": _manual_adjustment_impact_summary(adjustments, review_policy),
        "locked_task_summary": _locked_task_summary(tasks),
        "adjustment_reason_summary": _adjustment_reason_summary(adjustments),
        "latest_publish_audit": latest_publish_audit,
        "diagnostics": diagnostics,
        **order_buckets,
    }


@router.post("/preplans/{run_id}/adjustments")
def apply_manual_adjustment(
    run_id: int,
    payload: ManualAdjustmentPayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    settings = _get_schedule_settings(db)
    if not settings["manual_adjust_enabled"]:
        raise HTTPException(status_code=400, detail="当前系统未开启人工调整。")
    if settings["manual_adjust_reason_required"] and not payload.reason_text.strip():
        raise HTTPException(status_code=400, detail="人工调整必须填写原因。")
    if payload.start_time >= payload.end_time:
        raise HTTPException(status_code=400, detail="开始时间必须早于结束时间。")

    cur = db.cursor()
    cur.execute("SELECT run_id, lifecycle_status FROM schedule_runs WHERE run_id=%s", (run_id,))
    run = cur.fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Preplan not found.")
    if run["lifecycle_status"] not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=400, detail="只有草案状态允许人工调整。")

    cur.execute("""
        SELECT t.*, o.product_type, o.target_width, o.target_thickness,
            o.total_quantity_kg, o.order_class, o.due_date
        FROM scheduled_tasks t
        JOIN production_orders o ON o.order_id=t.order_id
        WHERE t.run_id=%s AND t.order_id=%s
        LIMIT 1
    """, (run_id, payload.order_id))
    before = cur.fetchone()
    before_state = _task_row_to_dict(before) if before else None

    cur.execute("""
        SELECT o.*, COALESCE(layer_count.layers, 0) AS recipe_layers,
            m.machine_id, m.status AS machine_status, m.min_width, m.max_width,
            m.min_thickness, m.max_thickness, m.cleanroom_level,
            m.layer_structure
        FROM production_orders o
        CROSS JOIN machines m
        LEFT JOIN (
            SELECT product_type, COUNT(*) AS layers
            FROM recipes
            GROUP BY product_type
        ) layer_count ON layer_count.product_type=o.product_type
        WHERE o.order_id=%s AND m.machine_id=%s
    """, (payload.order_id, payload.machine_id))
    ctx = cur.fetchone()
    if not ctx:
        raise HTTPException(status_code=404, detail="订单或机台不存在。")

    messages = _manual_adjustment_policy_items(ctx, payload, settings)

    candidate_busy_start = _calculate_candidate_setup_start(
        run_id,
        payload.order_id,
        payload.machine_id,
        payload.start_time,
        setup_rules_enabled=settings["setup_rules_enabled"],
    )
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM scheduled_tasks t
        WHERE t.run_id=%s
          AND t.machine_id=%s
          AND t.order_id<>%s
          AND COALESCE(t.setup_start_time, t.start_time) < %s
          AND t.end_time > %s
    """, (run_id, payload.machine_id, payload.order_id, payload.end_time, candidate_busy_start))
    if cur.fetchone()["cnt"]:
        messages.append(_validation_item("error", "task_overlap", "该机台在目标生产或换产时间段已有其他任务。", payload.order_id, payload.machine_id))
    if settings["maintenance_constraint_enabled"]:
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM machine_maintenance_calendar m
            WHERE m.machine_id=%s
              AND m.start_time < %s
              AND m.end_time > %s
              AND COALESCE(m.is_enabled, TRUE)=TRUE
        """, (payload.machine_id, payload.end_time, candidate_busy_start))
        if cur.fetchone()["cnt"]:
            messages.append(_validation_item("error", "maintenance_overlap", "目标生产或换产时间段与维护窗口冲突。", payload.order_id, payload.machine_id))
    cur.execute("""
        SELECT COUNT(*) AS cnt
        FROM machine_downtime_events d
        WHERE d.machine_id=%s
          AND d.start_time < %s
          AND COALESCE(d.end_time, %s) > %s
    """, (payload.machine_id, payload.end_time, payload.end_time, candidate_busy_start))
    if cur.fetchone()["cnt"]:
        messages.append(_validation_item("error", "downtime_overlap", "目标生产或换产时间段与停机事件冲突。", payload.order_id, payload.machine_id))

    after_state = {
        "order_id": payload.order_id,
        "machine_id": payload.machine_id,
        "setup_start_time": candidate_busy_start.isoformat(),
        "start_time": payload.start_time.isoformat(),
        "end_time": payload.end_time.isoformat(),
        "setup_time_mins": max(0, int((_as_naive(payload.start_time) - _as_naive(candidate_busy_start)).total_seconds() / 60)),
        "sequence_index": payload.sequence_index,
        "lock_machine": payload.lock_machine,
        "lock_time": payload.lock_time,
    }
    hard_errors = [item for item in messages if item["severity"] == "error"]
    if hard_errors:
        cur.execute("""
            INSERT INTO schedule_adjustment_audit
                (run_id, order_id, action_type, before_state, after_state,
                 reason_code, reason_text, changed_by, validation_status,
                 validation_messages)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            run_id, payload.order_id, "MOVE_TASK", Json(before_state or {}),
            Json(after_state), payload.reason_code, payload.reason_text,
            user.username, "FAILED", Json(messages),
        ))
        db.commit()
        raise HTTPException(status_code=400, detail={"message": "人工调整未通过校验。", "items": messages})

    base = datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
    start_mins = int((_as_naive(payload.start_time) - base).total_seconds() / 60)
    end_mins = int((_as_naive(payload.end_time) - base).total_seconds() / 60)
    duration_mins = max(1, end_mins - start_mins)
    sequence_index = payload.sequence_index
    if sequence_index is None:
        cur.execute(
            "SELECT COALESCE(MAX(sequence_index), 0) + 1 AS next_seq FROM scheduled_tasks WHERE run_id=%s AND machine_id=%s",
            (run_id, payload.machine_id),
        )
        sequence_index = cur.fetchone()["next_seq"]
    tardiness_mins = max(0, int((_as_naive(payload.end_time) - _as_naive(ctx["due_date"])).total_seconds() / 60))
    after_state["tardiness_mins"] = tardiness_mins
    task_source = "ADJUSTED" if before else "MANUAL"

    if before:
        affected_machine_ids = {before["machine_id"], payload.machine_id}
        cur.execute("""
            UPDATE scheduled_tasks
            SET machine_id=%s, sequence_index=%s, setup_start_time=%s,
                start_time=%s, end_time=%s, start_mins=%s, end_mins=%s,
                duration_mins=%s, is_late=%s, tardiness_mins=%s,
                task_source=%s, manual_lock_machine=%s, manual_lock_time=%s
            WHERE id=%s
            RETURNING id
        """, (
            payload.machine_id, sequence_index, payload.start_time,
            payload.start_time, payload.end_time, start_mins, end_mins,
            duration_mins, tardiness_mins > 0, tardiness_mins,
            task_source, payload.lock_machine, payload.lock_time, before["id"],
        ))
    else:
        affected_machine_ids = {payload.machine_id}
        cur.execute("""
            INSERT INTO scheduled_tasks
                (run_id, order_id, machine_id, sequence_index,
                 setup_start_time, start_time, end_time, start_mins,
                 end_mins, duration_mins, setup_time_mins, scrap_kg,
                 net_weight_kg, actual_material_required_kg, is_late,
                 tardiness_mins, task_source, manual_lock_machine,
                 manual_lock_time)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            run_id, payload.order_id, payload.machine_id, sequence_index,
            payload.start_time, payload.start_time, payload.end_time,
            start_mins, end_mins, duration_mins,
            ctx["total_quantity_kg"], ctx["total_quantity_kg"],
            tardiness_mins > 0, tardiness_mins, task_source,
            payload.lock_machine, payload.lock_time,
        ))
    task_id = cur.fetchone()["id"]
    after_state["scheduled_task_id"] = task_id
    _recalculate_machine_setup_fields(db, run_id, list(affected_machine_ids))
    _invalidate_validation_summary(cur, run_id, "manual_adjustment")
    cur.execute("""
        UPDATE schedule_runs
        SET lifecycle_status='DRAFT'
        WHERE run_id=%s AND lifecycle_status='VALIDATED'
    """, (run_id,))
    cur.execute("""
        INSERT INTO schedule_adjustment_audit
            (run_id, order_id, action_type, before_state, after_state,
             reason_code, reason_text, changed_by, validation_status,
             validation_messages)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        run_id, payload.order_id, "MOVE_TASK", Json(before_state or {}),
        Json(after_state), payload.reason_code, payload.reason_text,
        user.username, "PASSED", Json(messages),
    ))
    db.commit()
    return get_preplan(run_id=run_id, db=db, _=user)


@router.post("/preplans/{run_id}/validate")
def validate_preplan(run_id: int, db=Depends(get_db), _=Depends(require_role("admin", "planner"))):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute("SELECT lifecycle_status FROM schedule_runs WHERE run_id=%s", (run_id,))
    run = cur.fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Preplan not found.")
    validation = _load_preplan_validation(db, run_id)
    task_signature = _schedule_task_signature(cur, run_id)
    validation_summary = _persist_validation_summary(cur, run_id, validation, task_signature)
    if validation["hard_error_count"] == 0 and run["lifecycle_status"] in {"DRAFT", "VALIDATED"}:
        cur.execute("UPDATE schedule_runs SET lifecycle_status='VALIDATED' WHERE run_id=%s", (run_id,))
    db.commit()
    return {**validation, "last_validation_summary": validation_summary}


@router.post("/preplans/{run_id}/confirm")
def confirm_preplan(run_id: int, db=Depends(get_db), user=Depends(require_role("admin", "planner"))):
    settings = _get_schedule_settings(db)
    cur = db.cursor()
    cur.execute("SELECT run_id, lifecycle_status, solver_params FROM schedule_runs WHERE run_id=%s", (run_id,))
    run = cur.fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Preplan not found.")
    if run["lifecycle_status"] not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=400, detail="只有草案可以确认发布。")
    if settings["review_required"] and run["lifecycle_status"] != "VALIDATED":
        raise HTTPException(status_code=400, detail="需要先校验方案，再确认进入制造队列。")
    validation = _load_preplan_validation(db, run_id)
    _raise_if_unpublishable(validation)
    if settings["review_required"]:
        task_signature = _schedule_task_signature(cur, run_id)
        mismatch = _validation_summary_mismatch(
            _load_validation_summary(cur, run_id),
            validation,
            current_task_signature=task_signature,
        )
        if mismatch:
            raise HTTPException(status_code=400, detail=mismatch)
    if validation["warning_count"] and not settings["publish_with_warnings_allowed"]:
        raise HTTPException(status_code=400, detail={"message": "草案存在警告，当前系统不允许带警告发布。", "validation": validation})

    cur.execute("SELECT COUNT(*) AS cnt FROM scheduled_tasks WHERE run_id=%s", (run_id,))
    if cur.fetchone()["cnt"] == 0:
        raise HTTPException(status_code=400, detail="草案没有可发布任务。")
    cur.execute("""
        SELECT run_id
        FROM schedule_runs
        WHERE is_active=TRUE AND run_id<>%s
    """, (run_id,))
    previous_run_ids = [row["run_id"] for row in cur.fetchall()]
    if previous_run_ids:
        cur.execute("""
            UPDATE production_orders o
            SET status='PENDING', updated_at=NOW()
            FROM scheduled_tasks t
            LEFT JOIN manufacturing_queue q
              ON q.run_id=t.run_id
             AND q.order_id=t.order_id
            WHERE t.run_id = ANY(%s)
              AND t.order_id=o.order_id
              AND o.status='SCHEDULED'
              AND (q.id IS NULL OR q.queue_status IN ('QUEUED', 'READY'))
              AND NOT EXISTS (
                  SELECT 1
                  FROM scheduled_tasks next_task
                  WHERE next_task.run_id=%s
                    AND next_task.order_id=o.order_id
              )
        """, (previous_run_ids, run_id))
        cur.execute("""
            UPDATE manufacturing_queue
            SET queue_status='CANCELLED'
            WHERE run_id = ANY(%s)
              AND queue_status IN ('QUEUED', 'READY')
        """, (previous_run_ids,))
    cur.execute("""
        UPDATE schedule_runs
        SET is_active=FALSE,
            lifecycle_status=CASE
                WHEN lifecycle_status='CONFIRMED' THEN 'SUPERSEDED'
                ELSE lifecycle_status
            END
        WHERE is_active=TRUE AND run_id<>%s
    """, (run_id,))
    cur.execute("""
        UPDATE schedule_runs
        SET lifecycle_status='CONFIRMED', is_active=TRUE,
            confirmed_by=%s, confirmed_at=NOW()
        WHERE run_id=%s
    """, (user.username, run_id))
    cur.execute("""
        UPDATE production_orders o
        SET status='SCHEDULED', updated_at=NOW()
        FROM scheduled_tasks t
        WHERE t.run_id=%s
          AND t.order_id=o.order_id
          AND o.status='PENDING'
    """, (run_id,))
    cur.execute("""
        INSERT INTO manufacturing_queue
            (run_id, scheduled_task_id, order_id, machine_id, sequence_index,
             planned_start_time, planned_end_time, queue_status, released_by)
        SELECT run_id, id, order_id, machine_id, sequence_index,
            start_time, end_time, 'QUEUED', %s
        FROM scheduled_tasks
        WHERE run_id=%s
        ON CONFLICT (run_id, order_id) DO UPDATE SET
            scheduled_task_id=EXCLUDED.scheduled_task_id,
            machine_id=EXCLUDED.machine_id,
            sequence_index=EXCLUDED.sequence_index,
            planned_start_time=EXCLUDED.planned_start_time,
            planned_end_time=EXCLUDED.planned_end_time,
            queue_status='QUEUED',
            released_by=EXCLUDED.released_by,
            released_at=NOW()
    """, (user.username, run_id))
    queue_row_count = cur.rowcount
    run_params = _normalize_json(run.get("solver_params"), {}) or {}
    _insert_publish_audit(cur, _publish_audit_payload(
        event_type="PUBLISH",
        run_id=run_id,
        actor=user.username,
        selected_order_count=len(run_params.get("selected_order_ids") or []),
        warning_count=validation.get("warning_count") or 0,
        queue_row_count=queue_row_count,
        details={
            "superseded_run_ids": previous_run_ids,
            "hard_error_count": validation.get("hard_error_count") or 0,
        },
    ))
    db.commit()
    return {
        "run_id": run_id,
        "status": "CONFIRMED",
        "validation": validation,
        "publish_audit": {
            "event_type": "PUBLISH",
            "queue_row_count": queue_row_count,
        },
    }


@router.post("/preplans/{run_id}/cancel")
def cancel_preplan(
    run_id: int,
    payload: CancelPreplanPayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute("SELECT lifecycle_status FROM schedule_runs WHERE run_id=%s", (run_id,))
    run = cur.fetchone()
    if not run:
        raise HTTPException(status_code=404, detail="Preplan not found.")
    if run["lifecycle_status"] not in {"DRAFT", "VALIDATED"}:
        raise HTTPException(status_code=400, detail="只有草案可以废弃。")
    cur.execute("""
        UPDATE schedule_runs
        SET lifecycle_status='CANCELLED', cancelled_by=%s,
            cancelled_at=NOW(), cancel_reason=%s
        WHERE run_id=%s
    """, (user.username, payload.reason, run_id))
    db.commit()
    return {"run_id": run_id, "status": "CANCELLED"}


@router.get("/manufacturing-queue")
def get_manufacturing_queue(
    include_history: bool = False,
    status: Optional[str] = None,
    limit: int = Query(default=500, ge=1, le=1000),
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    _ensure_planning_schema(db)
    cur = db.cursor()
    where_clauses = []
    params = []
    if include_history:
        if status:
            where_clauses.append("q.queue_status=%s")
            params.append(status)
    else:
        where_clauses.extend([
            "r.is_active=TRUE",
            "r.lifecycle_status='CONFIRMED'",
        ])
        if status:
            where_clauses.append("q.queue_status=%s")
            params.append(status)
        else:
            where_clauses.append("q.queue_status<>'CANCELLED'")
    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    cur.execute(f"""
        SELECT q.*, o.product_type, o.target_width, o.target_thickness,
            o.total_quantity_kg, o.order_class,
            qa.actor AS last_transition_actor,
            qa.details AS last_transition_details,
            qa.created_at AS last_transition_created_at
        FROM manufacturing_queue q
        JOIN production_orders o ON o.order_id=q.order_id
        JOIN schedule_runs r ON r.run_id=q.run_id
        LEFT JOIN LATERAL (
            SELECT actor, details, created_at
            FROM schedule_publish_audit a
            WHERE a.run_id=q.run_id
              AND a.event_type='QUEUE_STATUS_CHANGE'
              AND a.details->>'queue_id'=q.id::text
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 1
        ) qa ON TRUE
        {where_sql}
        ORDER BY q.planned_start_time, q.machine_id, q.sequence_index
        LIMIT %s
    """, params + [limit])
    return [_queue_row_to_dict(row) for row in cur.fetchall()]


@router.patch("/manufacturing-queue/{queue_id}")
def update_manufacturing_queue_item(
    queue_id: int,
    payload: QueueStatusUpdatePayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    target_status = (payload.queue_status or "").strip().upper()
    reason = (payload.reason or "").strip()
    if target_status not in QUEUE_ALLOWED_TRANSITIONS:
        raise HTTPException(status_code=400, detail="目标队列状态无效。")
    if target_status in {"ON_HOLD", "CANCELLED"} and not reason:
        raise HTTPException(status_code=400, detail="切换为暂停或取消必须填写原因。")

    _ensure_planning_schema(db)
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT q.*, r.is_active, r.lifecycle_status,
                o.product_type, o.target_width, o.target_thickness,
                o.total_quantity_kg, o.order_class
            FROM manufacturing_queue q
            JOIN schedule_runs r ON r.run_id=q.run_id
            JOIN production_orders o ON o.order_id=q.order_id
            WHERE q.id=%s
            FOR UPDATE
        """, (queue_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="制造队列项不存在。")
        if not row["is_active"] or row["lifecycle_status"] != "CONFIRMED":
            raise HTTPException(status_code=400, detail="只能推进当前正式排程的制造队列。")

        current_status = row["queue_status"]
        _validate_queue_transition(current_status, target_status, reason)
        if target_status == "CANCELLED" and row.get("started_at"):
            raise HTTPException(status_code=400, detail="已开工队列项不能取消回待排。")

        cur.execute("""
            UPDATE manufacturing_queue
            SET queue_status=%s,
                started_at=CASE
                    WHEN %s='IN_PRODUCTION' AND started_at IS NULL THEN NOW()
                    ELSE started_at
                END,
                completed_at=CASE
                    WHEN %s='COMPLETED' THEN NOW()
                    ELSE completed_at
                END
            WHERE id=%s
        """, (target_status, target_status, target_status, queue_id))

        order_status = _order_status_for_queue_status(target_status)
        if order_status:
            cur.execute("""
                UPDATE production_orders
                SET status=%s, updated_at=NOW()
                WHERE order_id=%s
            """, (order_status, row["order_id"]))

        details = {
            "queue_id": queue_id,
            "scheduled_task_id": row.get("scheduled_task_id"),
            "order_id": row["order_id"],
            "machine_id": row["machine_id"],
            "from_status": current_status,
            "to_status": target_status,
            "reason": reason,
        }
        _insert_publish_audit(cur, _publish_audit_payload(
            event_type="QUEUE_STATUS_CHANGE",
            run_id=row["run_id"],
            actor=user.username,
            queue_row_count=1,
            details=details,
        ))

        cur.execute("""
            SELECT q.*, o.product_type, o.target_width, o.target_thickness,
                o.total_quantity_kg, o.order_class
            FROM manufacturing_queue q
            JOIN production_orders o ON o.order_id=q.order_id
            WHERE q.id=%s
        """, (queue_id,))
        updated = cur.fetchone() or {**row, "queue_status": target_status}
        db.commit()
        result = _queue_row_to_dict(updated)
        result["last_transition"] = {
            "actor": user.username,
            "created_at": _utc_now_iso(),
            "details": details,
        }
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.post("/clear-active")
def clear_active_schedule(
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    _ensure_planning_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT run_id
        FROM schedule_runs
        WHERE is_active=TRUE
        ORDER BY run_id DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        return {"cleared": False, "run_id": None, "cancelled_queue_count": 0}
    run_id = row["run_id"]
    cur.execute("""
        UPDATE production_orders o
        SET status='PENDING', updated_at=NOW()
        FROM scheduled_tasks t
        LEFT JOIN manufacturing_queue q
            ON q.run_id=t.run_id
           AND q.order_id=t.order_id
        WHERE t.run_id=%s
          AND t.order_id=o.order_id
          AND o.status='SCHEDULED'
          AND (q.id IS NULL OR q.queue_status IN ('QUEUED', 'READY'))
    """, (run_id,))
    restored_order_count = cur.rowcount
    cur.execute("""
        UPDATE schedule_runs
        SET is_active=FALSE,
            lifecycle_status=CASE
                WHEN lifecycle_status IN ('DRAFT', 'VALIDATED', 'CONFIRMED')
                THEN 'CANCELLED'
                ELSE lifecycle_status
            END,
            cancelled_by=%s,
            cancelled_at=NOW(),
            cancel_reason='撤销当前正式排程，返回待排订单池'
        WHERE run_id=%s
    """, (user.username, run_id))
    cur.execute("""
        UPDATE manufacturing_queue
        SET queue_status='CANCELLED'
        WHERE run_id=%s
          AND queue_status IN ('QUEUED', 'READY')
    """, (run_id,))
    cancelled_queue_count = cur.rowcount
    _insert_publish_audit(cur, _publish_audit_payload(
        event_type="CLEAR_ACTIVE",
        run_id=run_id,
        actor=user.username,
        selected_order_count=restored_order_count,
        warning_count=0,
        queue_row_count=cancelled_queue_count,
        details={"restored_order_count": restored_order_count},
    ))
    db.commit()
    return {
        "cleared": True,
        "run_id": run_id,
        "cancelled_queue_count": cancelled_queue_count,
        "restored_order_count": restored_order_count,
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
def trigger_schedule(db=Depends(get_db), user=Depends(require_role("admin", "planner"))):
    settings = _get_schedule_settings(db)
    if settings["review_required"]:
        raise HTTPException(
            status_code=400,
            detail="当前系统启用了预排程人工复核，请在排程工作台选择订单并确认进入制造队列。",
        )
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
