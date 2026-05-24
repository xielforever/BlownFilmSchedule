"""
APS 排程系统 PostgreSQL 数据库访问层

提供连接管理、DDL 初始化、主数据导入和排程结果持久化。
"""

from __future__ import annotations
import hashlib
import os
import datetime
import json
import logging
from typing import Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

from src.config import DATABASE_CONFIG, BASELINE_TIME
from src.diagnostics import diagnostics_to_dicts
from src.models import BlownFilmMachineModel, ForbiddenWindow, ProductionOrderModel
from src.scheduler import ScheduleResult
from src.setup_matrices import SetupMatricesManager
from src.snapshotting import (
    ORDER_SNAPSHOT_FIELDS,
    build_input_snapshot,
    build_machine_capability_snapshot,
    build_maintenance_calendar_snapshot,
    build_order_snapshot,
    build_process_snapshot,
    build_rule_matrix_snapshot,
    stable_hash,
)

logger = logging.getLogger(__name__)

DDL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "init_schema.sql")

RULE_ENABLEMENT_TABLES = (
    "material_switch_matrix",
    "gmp_clearance_matrix",
    "spec_change_rules",
    "machine_maintenance_calendar",
)


def _enabled_clause(table: str) -> str:
    if table not in RULE_ENABLEMENT_TABLES:
        raise ValueError(f"Unsupported rule table: {table}")
    return "COALESCE(is_enabled, TRUE)=TRUE"


def _snapshot_order_value(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return value


def _build_order_snapshot(row) -> dict:
    return build_order_snapshot(row)


def _fetch_input_snapshot(
    cur,
    order_snapshots: list[dict],
    screening_snapshot: Optional[dict] = None,
) -> dict:
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

    if screening_snapshot is None:
        screening_snapshot = {
            "count": len(order_snapshots or []),
            "hash": stable_hash([
                {"order_id": item.get("order_id"), "hash": item.get("hash")}
                for item in order_snapshots or []
            ]),
        }
    return build_input_snapshot(
        order_snapshots=order_snapshots,
        machine_capability_snapshot=machine_snapshot,
        maintenance_calendar_snapshot=maintenance_snapshot,
        rule_matrix_snapshot=rule_snapshot,
        process_snapshot=process_snapshot,
        screening_snapshot=screening_snapshot,
    )


def _apply_schedule_policy_to_master_data(
    machines: List[BlownFilmMachineModel],
    orders: List[ProductionOrderModel],
    policy: Dict[str, bool],
) -> None:
    """Apply global scheduling switches to in-memory solver inputs."""
    if not policy.get("material_constraint_enabled", True):
        for order in orders:
            order.material_available_mins = 0

    if not policy.get("cleanroom_constraint_enabled", True):
        for order in orders:
            order.cleanroom_req = "Class_100K"

    if not policy.get("machine_capability_constraint_enabled", True):
        max_width = max([machine.max_width for machine in machines] + [order.target_width for order in orders] + [0])
        max_thickness = max(
            [machine.max_thickness for machine in machines] + [order.target_thickness for order in orders] + [0]
        )
        max_layers = max([machine.layer_structure for machine in machines] + [len(order.recipe_materials) for order in orders] + [0])
        for machine in machines:
            machine.min_width = min(machine.min_width, 0)
            machine.max_width = max(machine.max_width, max_width)
            machine.min_thickness = min(machine.min_thickness, 0)
            machine.max_thickness = max(machine.max_thickness, max_thickness)
            machine.layer_structure = max(machine.layer_structure, max_layers)

    if not policy.get("due_date_optimization_enabled", True):
        for order in orders:
            order.priority_override = 0


def _build_schedule_run_solver_params(
    result: ScheduleResult,
    diagnostics_payload: list,
    normalized_order_ids: list[str],
    order_snapshots: list[dict],
    mode: str,
    policy_snapshot: Optional[dict] = None,
    input_snapshot: Optional[dict] = None,
    screening_snapshot: Optional[dict] = None,
) -> dict:
    payload = {
        "diagnostics": diagnostics_payload,
        "summary": {
            "input_order_count": getattr(result, "input_order_count", len(getattr(result, "tasks", []))),
            "schedulable_order_count": getattr(result, "schedulable_order_count", len(getattr(result, "tasks", []))),
            "blocked_order_count": getattr(result, "blocked_order_count", 0),
        },
        "selected_order_ids": normalized_order_ids,
        "order_snapshots": order_snapshots,
        "mode": mode,
        "solver_metrics": getattr(result, "solver_metrics", {}),
    }
    if policy_snapshot is not None:
        payload["policy_snapshot"] = policy_snapshot
    if input_snapshot is not None:
        payload["input_snapshot"] = input_snapshot
    if screening_snapshot is not None:
        payload["preplan_screening"] = screening_snapshot
    return payload


class DatabaseManager:
    """PostgreSQL 数据库管理器"""

    def __init__(self, config: dict = None):
        self.config = config or DATABASE_CONFIG
        self.conn = None

    def connect(self):
        """建立数据库连接"""
        self.conn = psycopg2.connect(
            host=self.config["host"],
            port=self.config["port"],
            dbname=self.config["database"],
            user=self.config["username"],
            password=self.config["password"],
        )
        self.conn.autocommit = False
        logger.info("数据库连接成功: %s:%s/%s",
                     self.config["host"], self.config["port"], self.config["database"])

    def close(self):
        if self.conn and not self.conn.closed:
            self.conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    # ─── DDL 初始化 ───────────────────────────────────────

    def init_schema(self):
        """执行 DDL 建表脚本"""
        with open(DDL_PATH, "r", encoding="utf-8") as f:
            sql = f.read()
        with self.conn.cursor() as cur:
            cur.execute(sql)
        self.conn.commit()
        logger.info("数据库 Schema 初始化完成（15 张表）")

    def ensure_planning_schema(self):
        """Ensure planning lifecycle tables/columns exist on older databases."""
        with self.conn.cursor() as cur:
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
                    updated_at                          TIMESTAMPTZ DEFAULT NOW()
                )
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
                CREATE TABLE IF NOT EXISTS order_revision_audit (
                    id                      SERIAL       PRIMARY KEY,
                    order_id                VARCHAR(20)  NOT NULL REFERENCES production_orders(order_id),
                    action_type             VARCHAR(30)  NOT NULL,
                    changed_fields          JSONB        NOT NULL,
                    before_state            JSONB,
                    after_state             JSONB,
                    reason_code             VARCHAR(50),
                    reason_text             TEXT,
                    impacted_draft_run_ids  JSONB        NOT NULL DEFAULT '[]'::jsonb,
                    changed_by              VARCHAR(50),
                    changed_at              TIMESTAMPTZ  DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_revision_audit_order
                ON order_revision_audit(order_id, changed_at DESC)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_ingestion_batches (
                    id                  SERIAL       PRIMARY KEY,
                    source_name         VARCHAR(200),
                    conflict_policy     VARCHAR(50)  NOT NULL DEFAULT 'reject_duplicates',
                    total_rows          INTEGER      NOT NULL DEFAULT 0,
                    accepted_rows       INTEGER      NOT NULL DEFAULT 0,
                    rejected_rows       INTEGER      NOT NULL DEFAULT 0,
                    created_by          VARCHAR(50),
                    created_at          TIMESTAMPTZ  DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_ingestion_rows (
                    id                  SERIAL       PRIMARY KEY,
                    batch_id            INTEGER      NOT NULL REFERENCES order_ingestion_batches(id),
                    row_index           INTEGER      NOT NULL,
                    order_id            VARCHAR(20),
                    row_status          VARCHAR(30)  NOT NULL,
                    normalized_order    JSONB,
                    errors              JSONB        NOT NULL DEFAULT '[]'::jsonb,
                    warnings            JSONB        NOT NULL DEFAULT '[]'::jsonb,
                    created_order       BOOLEAN      NOT NULL DEFAULT FALSE
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_order_ingestion_rows_batch
                ON order_ingestion_rows(batch_id, row_index)
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
                CREATE INDEX IF NOT EXISTS idx_schedule_publish_audit_run
                ON schedule_publish_audit(run_id, created_at DESC)
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
        self.conn.commit()

    # ─── 主数据导入 ───────────────────────────────────────

    def save_master_data(self, machines, orders, recipes_map, setup_mgr):
        """将从 Excel 解析的主数据批量导入数据库"""
        with self.conn.cursor() as cur:
            self._save_raw_materials(cur, recipes_map, setup_mgr)
            self._save_products(cur, recipes_map)
            self._save_recipes(cur, recipes_map)
            self._save_customers(cur, orders)
            self._save_machines(cur, machines)
            self._save_orders(cur, orders)
            self._save_setup_matrices(cur, setup_mgr)
        self.conn.commit()
        logger.info("主数据导入完成")

    def load_master_data(
        self,
        fallback_setup_mgr: Optional[SetupMatricesManager] = None,
        order_ids: Optional[List[str]] = None,
        order_statuses: Optional[Tuple[str, ...]] = None,
    ) -> Tuple[
        List[BlownFilmMachineModel],
        List[ProductionOrderModel],
        Dict[str, List[str]],
        SetupMatricesManager,
    ]:
        """Load scheduler inputs from the configured database."""
        base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
        setup_mgr = fallback_setup_mgr or SetupMatricesManager.empty_rules()

        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            self._ensure_rule_enablement_schema(cur)
            policy = self._load_schedule_policy(cur)
            recipes_map = self._load_recipes_map(cur)
            if policy.get("setup_rules_enabled", True):
                self._load_setup_matrices_from_db(cur, setup_mgr)
            else:
                setup_mgr = SetupMatricesManager.empty_rules()
            machines = self._load_machines_from_db(
                cur,
                base,
                maintenance_enabled=policy.get("maintenance_constraint_enabled", True),
            )
            orders = self._load_orders_from_db(
                cur,
                base,
                recipes_map,
                order_ids=order_ids,
                order_statuses=order_statuses,
            )
            _apply_schedule_policy_to_master_data(machines, orders, policy)

        logger.info(
            "从数据库加载排程输入完成: machines=%d, orders=%d, recipes=%d",
            len(machines), len(orders), len(recipes_map),
        )
        return machines, orders, recipes_map, setup_mgr

    def _ensure_rule_enablement_schema(self, cur) -> None:
        for table in RULE_ENABLEMENT_TABLES:
            cur.execute(f"""
                ALTER TABLE {table}
                    ADD COLUMN IF NOT EXISTS is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS disabled_reason TEXT,
                    ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50),
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()
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
                ADD COLUMN IF NOT EXISTS policy_version INTEGER NOT NULL DEFAULT 1,
                ADD COLUMN IF NOT EXISTS updated_by VARCHAR(50),
                ADD COLUMN IF NOT EXISTS change_reason TEXT
        """)

    def _load_schedule_policy(self, cur) -> Dict[str, bool]:
        try:
            cur.execute("""
                SELECT material_constraint_enabled, maintenance_constraint_enabled,
                    setup_rules_enabled, cleanroom_constraint_enabled,
                    machine_capability_constraint_enabled, due_date_optimization_enabled,
                    continuous_run_limit_mins, continuous_run_enforcement_mode,
                    phase2_feasible_tardiness_tolerance_mins,
                    solver_profile, solver_time_limit_seconds, solver_relative_gap_limit,
                    solver_random_seed, solver_num_workers, solver_log_search_progress,
                    planning_must_schedule_horizon_days, planning_candidate_horizon_days
                FROM schedule_settings
                WHERE id=TRUE
            """)
            row = cur.fetchone()
        except Exception:
            row = None
        defaults = {
            "material_constraint_enabled": True,
            "maintenance_constraint_enabled": True,
            "setup_rules_enabled": True,
            "cleanroom_constraint_enabled": True,
            "machine_capability_constraint_enabled": True,
            "due_date_optimization_enabled": True,
            "continuous_run_limit_mins": 4320,
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
        }
        return {**defaults, **dict(row or {})}

    def _load_recipes_map(self, cur) -> Dict[str, List[str]]:
        cur.execute("""
            SELECT product_type, layer, material_grade
            FROM recipes
            ORDER BY product_type, layer
        """)
        recipes_map: Dict[str, List[str]] = {}
        for r in cur.fetchall():
            recipes_map.setdefault(r["product_type"], []).append(r["material_grade"])
        return recipes_map

    def _load_setup_matrices_from_db(self, cur, setup_mgr: SetupMatricesManager) -> None:
        cur.execute("""
            SELECT from_material, to_material, switch_time_mins, scrap_weight_kg
            FROM material_switch_matrix
            WHERE COALESCE(is_enabled, TRUE)=TRUE
        """)
        for r in cur.fetchall():
            key = (r["from_material"], r["to_material"])
            setup_mgr.material_switch_matrix[key] = int(r["switch_time_mins"])
            if r["scrap_weight_kg"] is not None:
                setup_mgr.material_switch_scrap_matrix[key] = float(r["scrap_weight_kg"])

        cur.execute("""
            SELECT from_order_class, to_order_class, clearance_time_mins
            FROM gmp_clearance_matrix
            WHERE COALESCE(is_enabled, TRUE)=TRUE
        """)
        for r in cur.fetchall():
            from_class = r["from_order_class"]
            to_class = r["to_order_class"]
            mins = int(r["clearance_time_mins"])
            if from_class == "CONTINUOUS_RUN":
                setup_mgr.continuous_run_cleaning_time = mins
            else:
                setup_mgr.gmp_clearance_matrix[(from_class, to_class)] = mins

        cur.execute("""
            SELECT attribute, condition_desc, threshold_lower, threshold_upper,
                change_time_mins, scrap_weight_kg
            FROM spec_change_rules
            WHERE COALESCE(is_enabled, TRUE)=TRUE
            ORDER BY attribute, threshold_upper NULLS LAST, id
        """)
        spec_rows = cur.fetchall()
        if spec_rows:
            setup_mgr.width_up_rules = []
            setup_mgr.width_down_rules = []
            setup_mgr.thickness_rules = []
            setup_mgr.width_up_scrap_rules = []
            setup_mgr.width_down_scrap_rules = []
            setup_mgr.thickness_scrap_rules = []
        for r in spec_rows:
            attr = r["attribute"]
            mins = int(r["change_time_mins"])
            scrap = (
                float(r["scrap_weight_kg"])
                if r["scrap_weight_kg"] is not None
                else None
            )
            threshold = r["threshold_upper"] or r["threshold_lower"]
            if threshold is None:
                threshold = setup_mgr._parse_threshold(r["condition_desc"] or "")
            threshold = int(threshold)

            if attr == "Width_Up":
                setup_mgr.width_up_rules.append((threshold, mins))
                setup_mgr.width_up_scrap_rules.append((threshold, scrap))
            elif attr == "Width_Down":
                setup_mgr.width_down_rules.append((threshold, mins))
                setup_mgr.width_down_scrap_rules.append((threshold, scrap))
            elif attr == "Thickness":
                setup_mgr.thickness_rules.append((threshold, mins))
                setup_mgr.thickness_scrap_rules.append((threshold, scrap))
            elif attr == "Die_Change":
                setup_mgr.die_change_time = mins
                setup_mgr.die_change_scrap_kg = scrap
            elif attr == "Corona":
                setup_mgr.corona_switch_time = mins
                setup_mgr.corona_switch_scrap_kg = scrap
            elif attr == "Core_Size":
                setup_mgr.core_size_switch_time = mins
                setup_mgr.core_size_switch_scrap_kg = scrap

        setup_mgr.width_up_rules.sort(key=lambda x: x[0])
        setup_mgr.width_down_rules.sort(key=lambda x: x[0])
        setup_mgr.thickness_rules.sort(key=lambda x: x[0])
        setup_mgr.width_up_scrap_rules.sort(key=lambda x: x[0])
        setup_mgr.width_down_scrap_rules.sort(key=lambda x: x[0])
        setup_mgr.thickness_scrap_rules.sort(key=lambda x: x[0])

    def _load_machines_from_db(
        self,
        cur,
        base: datetime.datetime,
        maintenance_enabled: bool = True,
    ) -> List[BlownFilmMachineModel]:
        cur.execute("""
            SELECT m.*, s.current_material_lanes, s.current_width,
                s.current_thickness, s.current_corona, s.current_core_size,
                s.continuous_run_mins
            FROM machines m
            LEFT JOIN machine_current_state s ON m.machine_id = s.machine_id
            WHERE m.status='ACTIVE'
            ORDER BY m.machine_id
        """)
        machine_rows = cur.fetchall()

        calendar_by_machine: Dict[str, List[ForbiddenWindow]] = {}
        seen_windows = set()
        if maintenance_enabled:
            cur.execute("""
                SELECT machine_id, start_time, end_time, reason
                FROM machine_maintenance_calendar
                WHERE COALESCE(is_enabled, TRUE)=TRUE
                ORDER BY start_time
            """)
            for r in cur.fetchall():
                key = (
                    r["machine_id"],
                    r["start_time"],
                    r["end_time"],
                    r["reason"] or "Maintenance",
                )
                if key in seen_windows:
                    continue
                seen_windows.add(key)
                calendar_by_machine.setdefault(r["machine_id"], []).append(ForbiddenWindow(
                    start_mins=self._dt_to_mins(r["start_time"], base),
                    end_mins=self._dt_to_mins(r["end_time"], base),
                    reason=r["reason"] or "Maintenance",
                ))

        machines = []
        for r in machine_rows:
            machines.append(BlownFilmMachineModel(
                machine_id=r["machine_id"],
                name=r["name"],
                cleanroom_level=r["cleanroom_level"],
                layer_structure=int(r["layer_structure"]),
                die_diameter_mm=int(r["die_diameter_mm"]),
                min_width=int(r["min_width"]),
                max_width=int(r["max_width"]),
                min_thickness=int(r["min_thickness"]),
                max_thickness=int(r["max_thickness"]),
                hourly_output_kg=int(r["hourly_output_kg"]),
                max_slitting_lanes=int(r["max_slitting_lanes"]),
                initial_material_lanes=list(r["current_material_lanes"] or []),
                initial_width=int(r["current_width"] or 0),
                initial_thickness=int(r["current_thickness"] or 0),
                initial_corona=bool(r["current_corona"]) if r["current_corona"] is not None else False,
                initial_core_size=int(r["current_core_size"] or 3),
                initial_continuous_run_mins=int(r["continuous_run_mins"] or 0),
                forbidden_calendar=calendar_by_machine.get(r["machine_id"], []),
            ))
        return machines

    def _load_orders_from_db(
        self,
        cur,
        base: datetime.datetime,
        recipes_map: Dict[str, List[str]],
        order_ids: Optional[List[str]] = None,
        order_statuses: Optional[Tuple[str, ...]] = None,
    ) -> List[ProductionOrderModel]:
        statuses = tuple(order_statuses or ("PENDING", "SCHEDULED"))
        params = [list(statuses)]
        where_extra = ""
        if order_ids:
            where_extra = " AND o.order_id = ANY(%s)"
            params.append(list(order_ids))
        cur.execute(f"""
            SELECT o.*, COALESCE(c.customer_class, 'STANDARD') AS customer_class
            FROM production_orders o
            LEFT JOIN customers c ON o.customer_id = c.customer_id
            WHERE o.status = ANY(%s)
            {where_extra}
            ORDER BY o.due_date, o.order_id
        """, params)
        orders = []
        for r in cur.fetchall():
            recipe_materials = recipes_map.get(r["product_type"], ["Standard_Med_LDPE"])
            orders.append(ProductionOrderModel(
                order_id=r["order_id"],
                product_type=r["product_type"],
                target_width=int(r["target_width"]),
                target_thickness=int(r["target_thickness"]),
                total_quantity_kg=int(r["total_quantity_kg"]),
                cleanroom_req=r["cleanroom_req"],
                customer_class=r["customer_class"],
                order_class=r["order_class"],
                corona_req=bool(r["corona_req"]),
                core_size_inch=int(r["core_size_inch"] or 3),
                order_date_mins=self._dt_to_mins(r["order_date"], base) if r["order_date"] else 0,
                due_date_mins=self._dt_to_mins(r["due_date"], base),
                material_available_mins=(
                    self._dt_to_mins(r["material_available_time"], base)
                    if r["material_available_time"] else 0
                ),
                priority_override=(
                    int(r["priority_override"])
                    if r["priority_override"] is not None
                    else None
                ),
                recipe_materials=recipe_materials,
            ))
        return orders

    @staticmethod
    def _dt_to_mins(value, base: datetime.datetime) -> int:
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return int((value - base).total_seconds() / 60)

    def _save_raw_materials(self, cur, recipes_map, setup_mgr):
        """导入原料牌号"""
        grades = set()
        for materials in recipes_map.values():
            grades.update(materials)
        # 从机台初始挂料和换产矩阵中收集更多牌号
        for key in setup_mgr.material_switch_matrix:
            grades.add(key[0])
            grades.add(key[1])

        for g in grades:
            is_special = "Special" in g
            category = "SPECIAL" if is_special else (
                "MEDICAL_HIGH" if "Borealis" in g else (
                "PACKAGING" if ("Dow" in g or "Bird" in g) else "MEDICAL_STD"
            ))
            cur.execute("""
                INSERT INTO raw_materials (material_grade, material_category, is_special)
                VALUES (%s, %s, %s)
                ON CONFLICT (material_grade) DO NOTHING
            """, (g, category, is_special))

    def _save_products(self, cur, recipes_map):
        """导入产品类型"""
        for prod_type, mats in recipes_map.items():
            layer_type = "5层共挤" if len(mats) == 5 else "3层共挤"
            cur.execute("""
                INSERT INTO products (product_type, layer_type)
                VALUES (%s, %s)
                ON CONFLICT (product_type) DO NOTHING
            """, (prod_type, layer_type))

    def _save_recipes(self, cur, recipes_map):
        """导入工艺配方"""
        layer_labels = ["A", "B", "C", "D", "E"]
        for prod_type, materials in recipes_map.items():
            for i, mat in enumerate(materials):
                layer = layer_labels[i] if i < len(layer_labels) else str(i)
                cur.execute("""
                    INSERT INTO recipes (recipe_id, product_type, layer, material_grade)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_type, layer) DO NOTHING
                """, (f"REC-{prod_type[:3].upper()}-{i:02d}", prod_type, layer, mat))

    def _save_customers(self, cur, orders):
        """从订单中提取并去重导入客户"""
        seen = set()
        for o in orders:
            cid = o.customer_class  # 暂用 VIP/STANDARD 作为客户ID
            if cid not in seen:
                seen.add(cid)
                cur.execute("""
                    INSERT INTO customers (customer_id, customer_name, customer_class)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (customer_id) DO NOTHING
                """, (cid, f"{cid} 客户群", cid))

    def _save_machines(self, cur, machines):
        """导入机台主数据和初始状态"""
        for m in machines:
            cur.execute("""
                INSERT INTO machines (machine_id, name, cleanroom_level, layer_structure,
                    die_diameter_mm, min_width, max_width, min_thickness, max_thickness,
                    hourly_output_kg, max_slitting_lanes)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (machine_id) DO UPDATE SET
                    name=EXCLUDED.name, updated_at=NOW()
            """, (m.machine_id, m.name, m.cleanroom_level, m.layer_structure,
                  m.die_diameter_mm, m.min_width, m.max_width, m.min_thickness,
                  m.max_thickness, m.hourly_output_kg, m.max_slitting_lanes))
            # 初始状态
            cur.execute("""
                INSERT INTO machine_current_state
                    (machine_id, current_material_lanes, current_width,
                     current_thickness, current_corona, current_core_size)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (machine_id) DO UPDATE SET
                    current_material_lanes=EXCLUDED.current_material_lanes,
                    current_width=EXCLUDED.current_width,
                    current_thickness=EXCLUDED.current_thickness,
                    current_corona=EXCLUDED.current_corona,
                    current_core_size=EXCLUDED.current_core_size,
                    updated_at=NOW()
            """, (m.machine_id, m.initial_material_lanes,
                  m.initial_width, m.initial_thickness,
                  m.initial_corona, m.initial_core_size))
            # 维保日历
            for fw in m.forbidden_calendar:
                base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
                st = base + datetime.timedelta(minutes=fw.start_mins)
                et = base + datetime.timedelta(minutes=fw.end_mins)
                cur.execute("""
                    INSERT INTO machine_maintenance_calendar
                        (machine_id, start_time, end_time, maintenance_type, reason, is_recurring)
                    VALUES (%s, %s, %s, 'GMP_CLEANING', %s, TRUE)
                """, (m.machine_id, st, et, fw.reason))

    def _save_orders(self, cur, orders):
        """导入生产订单"""
        base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
        for o in orders:
            order_date = base + datetime.timedelta(minutes=o.order_date_mins) if o.order_date_mins else None
            due_date = base + datetime.timedelta(minutes=o.due_date_mins)
            mat_avail = base + datetime.timedelta(minutes=o.material_available_mins) if o.material_available_mins > 0 else None
            cur.execute("""
                INSERT INTO production_orders
                    (order_id, customer_id, product_type, target_width, target_thickness,
                     total_quantity_kg, cleanroom_req, order_class, corona_req,
                     core_size_inch, order_date, due_date, material_available_time)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (order_id) DO NOTHING
            """, (o.order_id, o.customer_class, o.product_type,
                  o.target_width, o.target_thickness, o.total_quantity_kg,
                  o.cleanroom_req, o.order_class, o.corona_req,
                  o.core_size_inch, order_date, due_date, mat_avail))

    def _save_setup_matrices(self, cur, setup_mgr):
        """导入换产矩阵"""
        for (f, t), mins in setup_mgr.material_switch_matrix.items():
            scrap = setup_mgr.material_switch_scrap_matrix.get((f, t))
            cur.execute("""
                INSERT INTO material_switch_matrix
                    (from_material, to_material, switch_time_mins, scrap_weight_kg)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (from_material, to_material) DO UPDATE SET
                    switch_time_mins=EXCLUDED.switch_time_mins,
                    scrap_weight_kg=COALESCE(
                        EXCLUDED.scrap_weight_kg,
                        material_switch_matrix.scrap_weight_kg
                    )
            """, (f, t, mins, scrap))
        for (fc, tc), mins in setup_mgr.gmp_clearance_matrix.items():
            cur.execute("""
                INSERT INTO gmp_clearance_matrix (from_order_class, to_order_class, clearance_time_mins)
                VALUES (%s, %s, %s)
                ON CONFLICT (from_order_class, to_order_class) DO UPDATE SET
                    clearance_time_mins=EXCLUDED.clearance_time_mins
            """, (fc, tc, mins))
        for rule in setup_mgr.iter_spec_rules():
            cur.execute("""
                UPDATE spec_change_rules SET
                    threshold_lower=%s,
                    threshold_upper=%s,
                    change_time_mins=%s,
                    scrap_weight_kg=COALESCE(%s, scrap_weight_kg),
                    description=COALESCE(description, %s)
                WHERE attribute=%s AND condition_desc=%s
            """, (
                rule["threshold_lower"],
                rule["threshold_upper"],
                rule["change_time_mins"],
                rule["scrap_weight_kg"],
                rule["description"],
                rule["attribute"],
                rule["condition_desc"],
            ))
            if cur.rowcount:
                continue
            cur.execute("""
                INSERT INTO spec_change_rules
                    (attribute, condition_desc, threshold_lower, threshold_upper,
                     change_time_mins, scrap_weight_kg, description)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                rule["attribute"],
                rule["condition_desc"],
                rule["threshold_lower"],
                rule["threshold_upper"],
                rule["change_time_mins"],
                rule["scrap_weight_kg"],
                rule["description"],
            ))

    # ─── 排程结果持久化 ───────────────────────────────────

    def save_schedule_result(
        self,
        result: ScheduleResult,
        triggered_by: Optional[str] = None,
        activate: bool = True,
        allow_invalid: bool = False,
        publish_orders: bool = True,
        mode: str = "AUTO",
        lifecycle_status: Optional[str] = None,
        selected_order_ids: Optional[List[str]] = None,
        policy_snapshot: Optional[dict] = None,
        screening_snapshot: Optional[dict] = None,
        input_screening_snapshot: Optional[dict] = None,
    ):
        """保存排程结果到数据库"""
        self.ensure_planning_schema()
        if getattr(result, "validation_errors", None) and not allow_invalid:
            raise ValueError(
                "排程结果未通过校验，拒绝入库: "
                + "; ".join(result.validation_errors[:5])
            )
        if getattr(result, "status", None) == "INVALID" and not allow_invalid:
            raise ValueError("Invalid schedule result cannot be published.")

        base = datetime.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")

        with self.conn.cursor() as cur:
            # 将之前的排程标记为非活跃
            if activate:
                cur.execute("UPDATE schedule_runs SET is_active = FALSE WHERE is_active = TRUE")

            total_setup = sum(t.setup_time for t in result.tasks)
            total_scrap = sum(t.scrap_kg for t in result.tasks)
            late = [t for t in result.tasks if t.end_mins > t.order.due_date_mins]
            vip_late = [t for t in late
                        if t.order.customer_class == "VIP" or t.order.order_class == "URGENT"]

            phase1_score = min(result.phase1_score, 2000000000)
            phase2_score = min(result.phase2_score, 2000000000)

            cur.execute("""
                INSERT INTO schedule_runs
                    (baseline_time, triggered_by, status, total_orders, total_machines_used,
                     phase1_tardiness_score, phase2_setup_score,
                     total_setup_time_mins, total_scrap_kg,
                     total_late_orders, vip_late_orders, is_active,
                     mode, lifecycle_status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING run_id
            """, (base, triggered_by, result.status, len(result.tasks),
                  len(result.machine_sequences),
                  phase1_score, phase2_score,
                  total_setup, total_scrap,
                  len(late), len(vip_late), activate,
                  mode, lifecycle_status or ("CONFIRMED" if activate else "DRAFT")))
            run_id = cur.fetchone()[0]

            order_snapshots = []
            normalized_order_ids = [order_id for order_id in dict.fromkeys(selected_order_ids or []) if order_id]
            if normalized_order_ids:
                with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as order_cur:
                    order_cur.execute("""
                        SELECT order_id, product_type, target_width, target_thickness,
                            total_quantity_kg, cleanroom_req, order_class, due_date,
                            material_available_time, status, priority_override, updated_at
                        FROM production_orders
                        WHERE order_id = ANY(%s)
                    """, (normalized_order_ids,))
                    order_rows = {row["order_id"]: row for row in order_cur.fetchall()}
                for order_id in normalized_order_ids:
                    row = order_rows.get(order_id)
                    if row:
                        order_snapshots.append(_build_order_snapshot(row))
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as snapshot_cur:
                input_snapshot = _fetch_input_snapshot(
                    snapshot_cur,
                    order_snapshots,
                    screening_snapshot=input_screening_snapshot,
                )

            diagnostics_payload = diagnostics_to_dicts(
                getattr(result, "diagnostics", []),
                run_id=run_id,
            )
            cur.execute(
                "UPDATE schedule_runs SET solver_params=%s WHERE run_id=%s",
                (Json(_build_schedule_run_solver_params(
                    result=result,
                    diagnostics_payload=diagnostics_payload,
                    normalized_order_ids=normalized_order_ids,
                    order_snapshots=order_snapshots,
                    mode=mode,
                    policy_snapshot=policy_snapshot,
                    input_snapshot=input_snapshot,
                    screening_snapshot=screening_snapshot,
                )), run_id),
            )

            # 保存任务明细
            for mid in sorted(result.machine_sequences.keys()):
                tasks = sorted(result.machine_sequences[mid], key=lambda x: x.start_mins)
                prev_oid = None
                for t in tasks:
                    st = base + datetime.timedelta(minutes=t.start_mins)
                    et = base + datetime.timedelta(minutes=t.end_mins)
                    setup_st = base + datetime.timedelta(minutes=max(0, t.start_mins - t.setup_time))

                    cur.execute("""
                        INSERT INTO scheduled_tasks
                            (run_id, order_id, machine_id, sequence_index,
                             setup_start_time, start_time, end_time,
                             start_mins, end_mins, duration_mins, setup_time_mins,
                             scrap_kg, net_weight_kg, actual_material_required_kg,
                              is_late, tardiness_mins, prev_order_id, setup_detail, task_source)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (run_id, t.order.order_id, t.machine.machine_id,
                          t.sequence_index, setup_st, st, et,
                          t.start_mins, t.end_mins,
                          t.end_mins - t.start_mins, t.setup_time,
                          t.scrap_kg, t.order.total_quantity_kg,
                          t.order.total_quantity_kg + t.scrap_kg,
                          t.end_mins > t.order.due_date_mins,
                          max(0, t.end_mins - t.order.due_date_mins),
                          prev_oid, Json(getattr(t, "setup_detail", None) or {}),
                          "AUTO"))
                    prev_oid = t.order.order_id

            # 更新订单状态
            if publish_orders:
                for t in result.tasks:
                    cur.execute("""
                        UPDATE production_orders SET status='SCHEDULED', updated_at=NOW()
                        WHERE order_id=%s AND status='PENDING'
                    """, (t.order.order_id,))

        self.conn.commit()
        logger.info("排程结果已入库: run_id=%d, %d 个任务", run_id, len(result.tasks))
        return run_id
