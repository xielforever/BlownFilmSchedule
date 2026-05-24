"""Orders API"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from psycopg2.extras import Json

from api.deps import get_db
from api.auth import get_current_user, require_role
from src.config import BASELINE_TIME
from src.models import BlownFilmMachineModel, ProductionOrderModel
from src.order_screening import screen_orders

router = APIRouter(prefix="/api/orders", tags=["Orders"])


ORDER_ALLOWED_STATUS = {"PENDING", "SCHEDULED", "IN_PRODUCTION", "COMPLETED", "CANCELLED"}
ORDER_ALLOWED_CLASS = {"URGENT", "NORMAL", "SAMPLE"}
ORDER_ALLOWED_CLEANROOM = {"Class_10K", "Class_100K"}
SCREENING_ACTION_TYPE_OPTIONS = (
    ("request_data_fix", "退回订单数据修正"),
    ("update_master_data", "维护机台/工艺主数据"),
    ("confirm_material", "确认物料方案"),
    ("reconfirm_due_date", "重新确认交期"),
    ("mark_reviewed", "标记已复核"),
    ("mark_resolved", "标记已处理"),
)
SCREENING_HANDLING_STATUS_OPTIONS = (
    ("open", "待处理"),
    ("in_progress", "处理中"),
    ("waiting_external", "等待外部确认"),
    ("resolved", "已处理"),
)
SCREENING_ACTION_FILTER_STATUS_OPTIONS = (
    ("unhandled", "未处理"),
    *SCREENING_HANDLING_STATUS_OPTIONS,
)
SCREENING_ACTION_TYPES = {value for value, _ in SCREENING_ACTION_TYPE_OPTIONS}
SCREENING_HANDLING_STATUSES = {value for value, _ in SCREENING_HANDLING_STATUS_OPTIONS}
ORDER_SCHEDULING_FIELDS = {
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
}
REVISION_REASON_FIELDS = {"reason_code", "reason_text"}
ORDER_AUDIT_FIELDS = (
    "order_id",
    "customer_id",
    "product_type",
    "target_width",
    "target_thickness",
    "total_quantity_kg",
    "cleanroom_req",
    "order_class",
    "corona_req",
    "core_size_inch",
    "order_date",
    "due_date",
    "material_available_time",
    "status",
    "priority_override",
)


class OrderCreatePayload(BaseModel):
    order_id: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    target_width: int = Field(gt=0)
    target_thickness: int = Field(gt=0)
    total_quantity_kg: int = Field(gt=0)
    cleanroom_req: str
    order_class: str
    due_date: datetime
    material_available_time: Optional[datetime] = None
    customer_id: Optional[str] = None
    customer_class: str = "STANDARD"
    corona_req: bool = False
    core_size_inch: int = Field(default=3, gt=0)
    order_date: Optional[datetime] = None
    status: str = "PENDING"
    priority_override: Optional[int] = Field(default=None, ge=0)
    reason_code: str = "ORDER_CREATE"
    reason_text: str = ""


class OrderUpdatePayload(BaseModel):
    product_type: Optional[str] = None
    target_width: Optional[int] = Field(default=None, gt=0)
    target_thickness: Optional[int] = Field(default=None, gt=0)
    total_quantity_kg: Optional[int] = Field(default=None, gt=0)
    cleanroom_req: Optional[str] = None
    order_class: Optional[str] = None
    corona_req: Optional[bool] = None
    core_size_inch: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[datetime] = None
    material_available_time: Optional[datetime] = None
    status: Optional[str] = None
    priority_override: Optional[int] = Field(default=None, ge=0)
    reason_code: str = "ORDER_UPDATE"
    reason_text: str = ""

    def changed_fields(self) -> dict[str, Any]:
        fields = self.model_dump(exclude_unset=True)
        for key in REVISION_REASON_FIELDS:
            fields.pop(key, None)
        return fields


OrderUpdate = OrderUpdatePayload


class OrderScreeningPayload(BaseModel):
    order_ids: list[str] = Field(default_factory=list)
    scope: str = "selected"
    screening_status: Optional[str] = None
    screening_bucket: Optional[str] = None


class OrderScreeningOverridePayload(BaseModel):
    reason_text: str = ""
    reason_code: str = "SCREENING_OVERRIDE"
    mode: str = "formal"


class OrderScreeningActionPayload(BaseModel):
    action_type: str
    handling_status: str = "in_progress"
    reason_text: str = Field(min_length=1)
    assignee: Optional[str] = None


class OrderImportPreviewPayload(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    conflict_policy: str = "reject_duplicates"


class OrderImportCommitPayload(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    conflict_policy: str = "reject_duplicates"
    source_name: str = "UI import"


def _normalize_order_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _order_row_state(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    state = {}
    for key in ORDER_AUDIT_FIELDS:
        state[key] = _normalize_order_value(row.get(key))
    return state


def _order_revision_diff(before: dict[str, Any], changed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    diff = {}
    for key, after in changed.items():
        before_value = before.get(key)
        if _normalize_order_value(before_value) == _normalize_order_value(after):
            continue
        diff[key] = {
            "before": _normalize_order_value(before_value),
            "after": _normalize_order_value(after),
            "scheduling_relevant": key in ORDER_SCHEDULING_FIELDS,
        }
    return diff


def _validate_order_enums(fields: dict[str, Any]) -> None:
    if "status" in fields and fields["status"] not in ORDER_ALLOWED_STATUS:
        raise HTTPException(status_code=400, detail="订单状态无效。")
    if "order_class" in fields and fields["order_class"] not in ORDER_ALLOWED_CLASS:
        raise HTTPException(status_code=400, detail="订单类型无效。")
    if "cleanroom_req" in fields and fields["cleanroom_req"] not in ORDER_ALLOWED_CLEANROOM:
        raise HTTPException(status_code=400, detail="洁净等级无效。")
    if "customer_class" in fields and fields["customer_class"] not in {"VIP", "STANDARD"}:
        raise HTTPException(status_code=400, detail="客户等级无效。")


def _ensure_order_revision_schema(db) -> None:
    cur = db.cursor()
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


def _ensure_order_import_schema(db) -> None:
    cur = db.cursor()
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


def _ensure_order_screening_schema(db) -> None:
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_screening_cache (
            order_id            VARCHAR(20)  PRIMARY KEY REFERENCES production_orders(order_id),
            screening_status    VARCHAR(20)  NOT NULL,
            business_bucket     VARCHAR(80),
            code                VARCHAR(80),
            root_cause          TEXT,
            result              JSONB        NOT NULL,
            summary             JSONB        NOT NULL DEFAULT '{}'::jsonb,
            scope               VARCHAR(30)  NOT NULL DEFAULT 'selected',
            is_stale            BOOLEAN      NOT NULL DEFAULT FALSE,
            stale_reason        VARCHAR(120),
            stale_at            TIMESTAMPTZ,
            computed_at         TIMESTAMPTZ  DEFAULT NOW()
        )
    """)
    cur.execute("""
        ALTER TABLE order_screening_cache
            ADD COLUMN IF NOT EXISTS business_bucket VARCHAR(80)
    """)
    cur.execute("""
        UPDATE order_screening_cache
        SET business_bucket = result->>'business_bucket'
        WHERE business_bucket IS NULL
          AND result ? 'business_bucket'
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_order_screening_cache_status
        ON order_screening_cache(screening_status, is_stale)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_order_screening_cache_bucket
        ON order_screening_cache(business_bucket, is_stale)
    """)


def _ensure_order_screening_override_schema(db) -> None:
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_screening_override_audit (
            id                  SERIAL       PRIMARY KEY,
            order_id            VARCHAR(20)  NOT NULL REFERENCES production_orders(order_id),
            screening_status    VARCHAR(20)  NOT NULL,
            screening_code      VARCHAR(80),
            override_policy     VARCHAR(30)  NOT NULL,
            reason_code         VARCHAR(80)  NOT NULL,
            reason_text         TEXT         NOT NULL,
            mode                VARCHAR(30)  NOT NULL DEFAULT 'formal',
            policy_version      INTEGER      NOT NULL DEFAULT 1,
            actor               VARCHAR(50),
            details             JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ  DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_order_screening_override_order
        ON order_screening_override_audit(order_id, created_at DESC)
    """)


def _ensure_order_screening_action_schema(db) -> None:
    cur = db.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_screening_action_audit (
            id                  SERIAL       PRIMARY KEY,
            order_id            VARCHAR(20)  NOT NULL REFERENCES production_orders(order_id),
            screening_status    VARCHAR(20)  NOT NULL,
            business_bucket     VARCHAR(80),
            screening_code      VARCHAR(80),
            action_type         VARCHAR(50)  NOT NULL,
            handling_status     VARCHAR(30)  NOT NULL,
            reason_text         TEXT         NOT NULL,
            assignee            VARCHAR(80),
            actor               VARCHAR(50),
            details             JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at          TIMESTAMPTZ  DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_order_screening_action_order
        ON order_screening_action_audit(order_id, created_at DESC)
    """)


def _find_impacted_draft_run_ids(cur, order_id: str) -> list[int]:
    cur.execute("""
        SELECT run_id
        FROM schedule_runs
        WHERE lifecycle_status IN ('DRAFT', 'VALIDATED')
          AND COALESCE(solver_params->'selected_order_ids', '[]'::jsonb) ? %s
        ORDER BY run_id DESC
    """, (order_id,))
    return [int(row["run_id"]) for row in cur.fetchall()]


def _insert_order_revision_audit(
    cur,
    *,
    order_id: str,
    action_type: str,
    changed_fields: dict[str, Any],
    before_state: dict[str, Any] | None,
    after_state: dict[str, Any],
    reason_code: str,
    reason_text: str,
    impacted_draft_run_ids: list[int],
    changed_by: str,
) -> int:
    cur.execute("""
        INSERT INTO order_revision_audit
            (order_id, action_type, changed_fields, before_state, after_state,
             reason_code, reason_text, impacted_draft_run_ids, changed_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        order_id,
        action_type,
        Json(changed_fields),
        Json(before_state or {}),
        Json(after_state),
        reason_code,
        reason_text,
        Json(impacted_draft_run_ids),
        changed_by,
    ))
    row = cur.fetchone()
    return int(row["id"] if isinstance(row, dict) else row[0])


IMPORT_FIELD_ALIASES = {
    "订单号": "order_id",
    "订单id": "order_id",
    "订单ID": "order_id",
    "工单号": "order_id",
    "产品类型": "product_type",
    "产品": "product_type",
    "幅宽": "target_width",
    "幅宽mm": "target_width",
    "厚度": "target_thickness",
    "厚度um": "target_thickness",
    "重量": "total_quantity_kg",
    "数量": "total_quantity_kg",
    "重量kg": "total_quantity_kg",
    "洁净等级": "cleanroom_req",
    "洁净度": "cleanroom_req",
    "订单类型": "order_class",
    "交期": "due_date",
    "材料可用时间": "material_available_time",
    "物料齐套时间": "material_available_time",
    "客户": "customer_id",
    "客户id": "customer_id",
    "客户等级": "customer_class",
    "电晕": "corona_req",
    "纸芯": "core_size_inch",
    "下单时间": "order_date",
    "状态": "status",
    "优先级": "priority_override",
}


def _normalize_import_field_name(name: str) -> str:
    text = str(name or "").strip()
    if text in IMPORT_FIELD_ALIASES:
        return IMPORT_FIELD_ALIASES[text]
    key = text.lower().strip().replace(" ", "_").replace("-", "_")
    return IMPORT_FIELD_ALIASES.get(key, key)


def _clean_import_value(value):
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    return value


def _normalize_import_row(raw_row: dict[str, Any]) -> dict[str, Any]:
    normalized = {}
    for key, value in (raw_row or {}).items():
        field = _normalize_import_field_name(key)
        normalized[field] = _clean_import_value(value)
    if normalized.get("cleanroom_req") == "NO":
        normalized["cleanroom_req"] = "Class_100K"
    if isinstance(normalized.get("corona_req"), str):
        normalized["corona_req"] = normalized["corona_req"].strip().upper() in {"YES", "TRUE", "Y", "1"}
    normalized.setdefault("status", "PENDING")
    normalized.setdefault("customer_class", "STANDARD")
    normalized.setdefault("core_size_inch", 3)
    normalized.setdefault("corona_req", False)
    return normalized


def _payload_to_preview_order(payload: OrderCreatePayload) -> dict[str, Any]:
    data = payload.model_dump()
    return {key: _normalize_order_value(value) for key, value in data.items()}


def _preview_import_rows(
    rows: list[dict[str, Any]],
    *,
    existing_order_ids: set[str],
    product_types: set[str],
    conflict_policy: str = "reject_duplicates",
) -> dict[str, Any]:
    if conflict_policy != "reject_duplicates":
        raise HTTPException(status_code=400, detail="当前仅支持 reject_duplicates 导入策略。")

    seen_input_ids: set[str] = set()
    preview_rows = []
    for index, raw_row in enumerate(rows, start=1):
        normalized = _normalize_import_row(raw_row)
        errors = []
        warnings = []
        payload = None
        try:
            payload = OrderCreatePayload(**normalized)
            _validate_order_enums(payload.model_dump(exclude_unset=True))
        except ValidationError as exc:
            errors.extend([
                f"{'.'.join(str(part) for part in err.get('loc', []))}: {err.get('msg')}"
                for err in exc.errors()
            ])
        except HTTPException as exc:
            errors.append(str(exc.detail))

        order_id = str(normalized.get("order_id") or "").strip()
        product_type = str(normalized.get("product_type") or "").strip()
        if product_type and product_type not in product_types:
            errors.append(f"产品类型不存在: {product_type}")

        row_status = "new"
        if errors:
            row_status = "rejected"
        elif order_id in seen_input_ids:
            row_status = "duplicate_input"
            errors.append("导入文件中订单号重复。")
        elif order_id in existing_order_ids:
            row_status = "conflict"
            errors.append("订单已存在，当前导入策略为 reject_duplicates。")

        if order_id:
            seen_input_ids.add(order_id)

        preview_rows.append({
            "row_index": index,
            "order_id": order_id or None,
            "row_status": row_status,
            "normalized_order": _payload_to_preview_order(payload) if payload and row_status == "new" else None,
            "errors": errors,
            "warnings": warnings,
            "raw_row": raw_row,
        })

    summary = {
        "total_rows": len(preview_rows),
        "new_count": sum(1 for row in preview_rows if row["row_status"] == "new"),
        "conflict_count": sum(1 for row in preview_rows if row["row_status"] == "conflict"),
        "duplicate_input_count": sum(1 for row in preview_rows if row["row_status"] == "duplicate_input"),
        "rejected_count": sum(1 for row in preview_rows if row["row_status"] == "rejected"),
    }
    return {
        "mode": "preview",
        "conflict_policy": conflict_policy,
        "summary": summary,
        "rows": preview_rows,
    }


def _accepted_import_orders(preview_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["normalized_order"]
        for row in preview_rows
        if row.get("row_status") == "new" and row.get("normalized_order")
    ]


def _ensure_import_has_accepted_rows(preview_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = _accepted_import_orders(preview_rows)
    if not accepted:
        raise HTTPException(status_code=400, detail="导入预览中没有可提交的新订单。")
    return accepted


def _load_import_reference_sets(cur, rows: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    order_ids = []
    for raw_row in rows:
        order_id = str(_normalize_import_row(raw_row).get("order_id") or "").strip()
        if order_id:
            order_ids.append(order_id)
    existing_order_ids: set[str] = set()
    if order_ids:
        cur.execute(
            "SELECT order_id FROM production_orders WHERE order_id = ANY(%s)",
            (list(dict.fromkeys(order_ids)),),
        )
        existing_order_ids = {row["order_id"] for row in cur.fetchall()}
    cur.execute("SELECT product_type FROM products")
    product_types = {row["product_type"] for row in cur.fetchall()}
    return existing_order_ids, product_types


def _insert_order_from_import(cur, normalized_order: dict[str, Any], username: str) -> int:
    payload = OrderCreatePayload(**normalized_order)
    customer_id = payload.customer_id or payload.customer_class
    cur.execute("""
        INSERT INTO customers (customer_id, customer_name, customer_class)
        VALUES (%s, %s, %s)
        ON CONFLICT (customer_id) DO NOTHING
    """, (customer_id, f"{customer_id} 客户", payload.customer_class))
    cur.execute("""
        INSERT INTO production_orders
            (order_id, customer_id, product_type, target_width, target_thickness,
             total_quantity_kg, cleanroom_req, order_class, corona_req,
             core_size_inch, order_date, due_date, material_available_time,
             status, priority_override)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        payload.order_id,
        customer_id,
        payload.product_type,
        payload.target_width,
        payload.target_thickness,
        payload.total_quantity_kg,
        payload.cleanroom_req,
        payload.order_class,
        payload.corona_req,
        payload.core_size_inch,
        payload.order_date,
        payload.due_date,
        payload.material_available_time,
        "PENDING",
        payload.priority_override,
    ))
    cur.execute("SELECT * FROM production_orders WHERE order_id=%s", (payload.order_id,))
    created_row = cur.fetchone()
    after_state = _order_row_state(created_row)
    return _insert_order_revision_audit(
        cur,
        order_id=payload.order_id,
        action_type="CREATE_IMPORT",
        changed_fields=_order_revision_diff({}, after_state),
        before_state={},
        after_state=after_state,
        reason_code=payload.reason_code or "ORDER_IMPORT",
        reason_text=payload.reason_text or "批量导入创建订单",
        impacted_draft_run_ids=[],
        changed_by=username,
    )


def _dt_to_baseline_mins(value) -> int:
    if not value:
        return 0
    base = datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    return int((value - base).total_seconds() / 60)


def _screening_order_from_row(row) -> ProductionOrderModel:
    recipe_materials = list(row.get("recipe_materials") or [])
    return ProductionOrderModel(
        order_id=row["order_id"],
        product_type=row["product_type"],
        target_width=int(row["target_width"]),
        target_thickness=int(row["target_thickness"]),
        total_quantity_kg=int(row["total_quantity_kg"]),
        cleanroom_req=row["cleanroom_req"],
        customer_class=row.get("customer_class") or "STANDARD",
        order_class=row["order_class"],
        corona_req=bool(row.get("corona_req")),
        core_size_inch=int(row.get("core_size_inch") or 3),
        order_date_mins=_dt_to_baseline_mins(row.get("order_date")),
        due_date_mins=_dt_to_baseline_mins(row.get("due_date")),
        material_available_mins=_dt_to_baseline_mins(row.get("material_available_time")),
        priority_override=(
            int(row["priority_override"])
            if row.get("priority_override") is not None
            else None
        ),
        recipe_materials=recipe_materials,
    )


def _screening_machine_from_row(row) -> BlownFilmMachineModel:
    return BlownFilmMachineModel(
        machine_id=row["machine_id"],
        name=row.get("name") or row["machine_id"],
        cleanroom_level=row["cleanroom_level"],
        layer_structure=int(row["layer_structure"]),
        die_diameter_mm=int(row["die_diameter_mm"]),
        min_width=int(row["min_width"]),
        max_width=int(row["max_width"]),
        min_thickness=int(row["min_thickness"]),
        max_thickness=int(row["max_thickness"]),
        hourly_output_kg=int(row["hourly_output_kg"]),
        max_slitting_lanes=int(row.get("max_slitting_lanes") or 1),
    )


def _load_order_screening_policy(cur) -> dict[str, Any]:
    try:
        cur.execute("""
            SELECT screening_due_risk_min_slack_mins,
                screening_due_risk_duration_multiplier
            FROM schedule_settings
            WHERE id=TRUE
        """)
        row = cur.fetchone() or {}
    except Exception:
        row = {}
    return {
        "due_risk_min_slack_mins": int(row.get("screening_due_risk_min_slack_mins") or 240),
        "due_risk_duration_multiplier": float(row.get("screening_due_risk_duration_multiplier") or 1.5),
    }


def _load_screening_order_rows(cur, order_ids: list[str] | None):
    params = []
    where = "WHERE o.status='PENDING'"
    if order_ids:
        where = "WHERE o.order_id = ANY(%s)"
        params.append(order_ids)
    cur.execute(f"""
        SELECT o.*, COALESCE(c.customer_class, 'STANDARD') AS customer_class,
            (p.product_type IS NOT NULL) AS product_exists,
            COALESCE(recipe_layers.layers, 0) AS recipe_layers,
            COALESCE(recipe_layers.materials, ARRAY[]::VARCHAR[]) AS recipe_materials
        FROM production_orders o
        LEFT JOIN customers c ON c.customer_id=o.customer_id
        LEFT JOIN products p ON p.product_type=o.product_type
        LEFT JOIN (
            SELECT product_type,
                COUNT(*) AS layers,
                ARRAY_AGG(material_grade ORDER BY layer) AS materials
            FROM recipes
            GROUP BY product_type
        ) recipe_layers ON recipe_layers.product_type=o.product_type
        {where}
        ORDER BY o.due_date, o.order_id
    """, params)
    rows = cur.fetchall()
    if order_ids:
        found = {row["order_id"] for row in rows}
        missing = [order_id for order_id in order_ids if order_id not in found]
        if missing:
            raise HTTPException(status_code=404, detail=f"订单不存在: {', '.join(missing[:5])}")
    return rows


def _run_order_screening(db, *, order_ids: list[str] | None, scope: str):
    cur = db.cursor()
    order_rows = _load_screening_order_rows(cur, order_ids)
    cur.execute("""
        SELECT machine_id, name, cleanroom_level, layer_structure,
            die_diameter_mm, min_width, max_width, min_thickness,
            max_thickness, hourly_output_kg, max_slitting_lanes
        FROM machines
        WHERE status='ACTIVE'
        ORDER BY machine_id
    """)
    machines = [_screening_machine_from_row(row) for row in cur.fetchall()]
    orders = [_screening_order_from_row(row) for row in order_rows]
    screening_policy = _load_order_screening_policy(cur)
    result = screen_orders(
        orders,
        machines,
        status_by_order_id={row["order_id"]: row["status"] for row in order_rows},
        product_exists_by_order_id={row["order_id"]: bool(row.get("product_exists")) for row in order_rows},
        scope=scope,
        screening_policy=screening_policy,
    )
    result["requested_order_ids"] = order_ids or []
    return result


def _persist_order_screening_result(cur, result: dict) -> None:
    summary = result.get("summary") or {}
    scope = result.get("scope") or "selected"
    for item in result.get("items", []):
        cur.execute("""
            INSERT INTO order_screening_cache
                (order_id, screening_status, business_bucket, code, root_cause, result, summary, scope, is_stale)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
            ON CONFLICT (order_id) DO UPDATE SET
                screening_status=EXCLUDED.screening_status,
                business_bucket=EXCLUDED.business_bucket,
                code=EXCLUDED.code,
                root_cause=EXCLUDED.root_cause,
                result=EXCLUDED.result,
                summary=EXCLUDED.summary,
                scope=EXCLUDED.scope,
                is_stale=FALSE,
                computed_at=NOW()
        """, (
            item.get("order_id"),
            item.get("screening_status"),
            item.get("business_bucket"),
            item.get("code"),
            item.get("root_cause"),
            Json(item),
            Json(summary),
            scope,
        ))


def _mark_order_screening_cache_stale(
    cur,
    *,
    order_ids: list[str] | None = None,
    reason: str = "dependency_changed",
) -> int:
    if order_ids:
        order_ids = list(dict.fromkeys(order_id for order_id in order_ids if order_id))
        if not order_ids:
            return 0
        cur.execute("""
            UPDATE order_screening_cache
            SET is_stale=TRUE, stale_reason=%s, stale_at=NOW()
            WHERE order_id = ANY(%s)
              AND is_stale=FALSE
        """, (reason, order_ids))
    else:
        cur.execute("""
            UPDATE order_screening_cache
            SET is_stale=TRUE, stale_reason=%s, stale_at=NOW()
            WHERE is_stale=FALSE
        """, (reason,))
    return int(getattr(cur, "rowcount", 0) or 0)


def _insert_order_screening_override_audit(
    cur,
    *,
    order_id: str,
    screening_item: dict[str, Any],
    override_decision: dict[str, Any],
    payload: OrderScreeningOverridePayload,
    policy_version: int,
    actor: str,
) -> int:
    cur.execute("""
        INSERT INTO order_screening_override_audit
            (order_id, screening_status, screening_code, override_policy,
             reason_code, reason_text, mode, policy_version, actor, details)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        order_id,
        screening_item.get("screening_status"),
        screening_item.get("code"),
        override_decision.get("policy"),
        payload.reason_code,
        payload.reason_text.strip(),
        payload.mode,
        policy_version,
        actor,
        Json({
            "override_decision": override_decision,
            "screening": screening_item,
        }),
    ))
    row = cur.fetchone()
    return int(row["id"] if isinstance(row, dict) else row[0])


def _screening_override_audit_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "screening_status": row["screening_status"],
        "screening_code": row.get("screening_code"),
        "override_policy": row["override_policy"],
        "reason_code": row["reason_code"],
        "reason_text": row["reason_text"],
        "mode": row["mode"],
        "policy_version": row["policy_version"],
        "actor": row.get("actor"),
        "details": row.get("details") or {},
        "created_at": _iso(row.get("created_at")),
    }


def _latest_screening_override_from_order_row(row) -> dict[str, Any] | None:
    if not row.get("screening_override_id"):
        return None
    return {
        "id": row["screening_override_id"],
        "order_id": row["order_id"],
        "screening_status": row.get("screening_override_status"),
        "screening_code": row.get("screening_override_code"),
        "override_policy": row.get("screening_override_policy"),
        "reason_code": row.get("screening_override_reason_code"),
        "reason_text": row.get("screening_override_reason_text"),
        "mode": row.get("screening_override_mode"),
        "policy_version": row.get("screening_override_policy_version"),
        "actor": row.get("screening_override_actor"),
        "details": row.get("screening_override_details") or {},
        "created_at": _iso(row.get("screening_override_created_at")),
    }


def _screening_action_audit_row_to_dict(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "screening_status": row["screening_status"],
        "business_bucket": row.get("business_bucket"),
        "screening_code": row.get("screening_code"),
        "action_type": row["action_type"],
        "handling_status": row["handling_status"],
        "reason_text": row["reason_text"],
        "assignee": row.get("assignee"),
        "actor": row.get("actor"),
        "details": row.get("details") or {},
        "created_at": _iso(row.get("created_at")),
    }


def _latest_screening_action_from_order_row(row) -> dict[str, Any] | None:
    if not row.get("screening_action_id"):
        return None
    return _screening_action_audit_row_to_dict({
        "id": row["screening_action_id"],
        "order_id": row["order_id"],
        "screening_status": row.get("screening_action_status"),
        "business_bucket": row.get("screening_action_bucket"),
        "screening_code": row.get("screening_action_code"),
        "action_type": row.get("screening_action_type"),
        "handling_status": row.get("screening_action_handling_status"),
        "reason_text": row.get("screening_action_reason_text"),
        "assignee": row.get("screening_action_assignee"),
        "actor": row.get("screening_action_actor"),
        "details": row.get("screening_action_details") or {},
        "created_at": row.get("screening_action_created_at"),
    })


def _screening_summary(items: list[dict]) -> dict:
    return {
        "total_orders": len(items),
        "ready_count": sum(1 for item in items if item.get("screening_status") == "ready"),
        "risk_count": sum(1 for item in items if item.get("screening_status") == "risk"),
        "blocked_count": sum(1 for item in items if item.get("screening_status") == "blocked"),
        "business_bucket_counts": {
            bucket: sum(1 for item in items if item.get("business_bucket") == bucket)
            for bucket in sorted({item.get("business_bucket") for item in items if item.get("business_bucket")})
        },
    }


SCREENING_BUSINESS_BUCKETS = {
    "ready",
    "risk",
    "blocked_data_error",
    "blocked_machine_capability",
    "blocked_cleanroom",
    "blocked_material",
    "blocked_policy",
}


def _filter_screening_result(
    result: dict,
    screening_status: str | None,
    screening_bucket: str | None = None,
) -> dict:
    status = screening_status.lower() if screening_status else None
    bucket = screening_bucket.lower() if screening_bucket else None
    if status and status not in {"ready", "risk", "blocked"}:
        raise HTTPException(status_code=400, detail="初筛状态无效。")
    if bucket and bucket not in SCREENING_BUSINESS_BUCKETS:
        raise HTTPException(status_code=400, detail="初筛业务桶无效。")
    if not status and not bucket:
        return result
    items = [
        item
        for item in result.get("items", [])
        if (not status or item.get("screening_status") == status)
        and (not bucket or item.get("business_bucket") == bucket)
    ]
    filtered = {
        **result,
        "items": items,
        "summary": _screening_summary(items),
    }
    if status:
        filtered["screening_status_filter"] = status
    if bucket:
        filtered["screening_bucket_filter"] = bucket
    return filtered


@router.get("")
def list_orders(
    status: str = None,
    screening_status: Optional[str] = None,
    screening_bucket: Optional[str] = None,
    screening_stale: Optional[bool] = None,
    screening_action_status: Optional[str] = None,
    screening_action_type: Optional[str] = None,
    screening_action_assignee: Optional[str] = None,
    q: Optional[str] = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    _ensure_order_screening_override_schema(db)
    _ensure_order_screening_action_schema(db)
    cur = db.cursor()
    where_clauses = ["1=1"]
    params = []
    if status:
        where_clauses.append("o.status=%s")
        params.append(status)
    if screening_status:
        normalized_screening_status = screening_status.lower()
        if normalized_screening_status not in {"ready", "risk", "blocked"}:
            raise HTTPException(status_code=400, detail="Invalid screening status.")
        where_clauses.append("LOWER(osc.screening_status)=%s")
        params.append(normalized_screening_status)
    if screening_bucket:
        normalized_screening_bucket = screening_bucket.lower()
        if normalized_screening_bucket not in SCREENING_BUSINESS_BUCKETS:
            raise HTTPException(status_code=400, detail="Invalid screening bucket.")
        where_clauses.append("LOWER(COALESCE(osc.business_bucket, osc.result->>'business_bucket'))=%s")
        params.append(normalized_screening_bucket)
    if screening_stale is not None:
        where_clauses.append("COALESCE(osc.is_stale, FALSE)=%s")
        params.append(bool(screening_stale))
    if screening_action_status:
        normalized_action_status = screening_action_status.lower()
        if normalized_action_status == "unhandled":
            where_clauses.append("latest_action.handling_status IS NULL")
        elif normalized_action_status not in SCREENING_HANDLING_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid screening action status.")
        else:
            where_clauses.append("LOWER(latest_action.handling_status)=%s")
            params.append(normalized_action_status)
    if screening_action_type:
        normalized_action_type = screening_action_type.lower()
        if normalized_action_type not in SCREENING_ACTION_TYPES:
            raise HTTPException(status_code=400, detail="Invalid screening action type.")
        where_clauses.append("LOWER(latest_action.action_type)=%s")
        params.append(normalized_action_type)
    if screening_action_assignee:
        normalized_action_assignee = screening_action_assignee.strip().lower()
        if normalized_action_assignee == "unassigned":
            where_clauses.append("latest_action.assignee IS NULL")
        else:
            where_clauses.append("LOWER(latest_action.assignee)=%s")
            params.append(normalized_action_assignee)
    if q:
        like = f"%{q.strip()}%"
        where_clauses.append(
            """(
                o.order_id ILIKE %s
                OR o.product_type ILIKE %s
                OR o.customer_id ILIKE %s
                OR c.customer_name ILIKE %s
                OR o.status ILIKE %s
                OR t.machine_id ILIKE %s
            )"""
        )
        params.extend([like, like, like, like, like, like])

    where = "WHERE " + " AND ".join(where_clauses)
    offset = (page - 1) * size

    cur.execute(f"""
        SELECT o.*, c.customer_name, c.customer_class,
            t.machine_id AS assigned_machine, t.start_time AS sched_start,
            t.end_time AS sched_end, t.scrap_kg, t.setup_time_mins,
            t.actual_material_required_kg,
            osc.screening_status, osc.code AS screening_code,
            osc.root_cause AS screening_root_cause, osc.is_stale AS screening_is_stale,
            osc.stale_reason AS screening_stale_reason,
            osc.business_bucket AS screening_business_bucket,
            osc.result AS screening_result,
            latest_override.id AS screening_override_id,
            latest_override.screening_status AS screening_override_status,
            latest_override.screening_code AS screening_override_code,
            latest_override.override_policy AS screening_override_policy,
            latest_override.reason_code AS screening_override_reason_code,
            latest_override.reason_text AS screening_override_reason_text,
            latest_override.mode AS screening_override_mode,
            latest_override.policy_version AS screening_override_policy_version,
            latest_override.actor AS screening_override_actor,
            latest_override.details AS screening_override_details,
            latest_override.created_at AS screening_override_created_at,
            latest_action.id AS screening_action_id,
            latest_action.screening_status AS screening_action_status,
            latest_action.business_bucket AS screening_action_bucket,
            latest_action.screening_code AS screening_action_code,
            latest_action.action_type AS screening_action_type,
            latest_action.handling_status AS screening_action_handling_status,
            latest_action.reason_text AS screening_action_reason_text,
            latest_action.assignee AS screening_action_assignee,
            latest_action.actor AS screening_action_actor,
            latest_action.details AS screening_action_details,
            latest_action.created_at AS screening_action_created_at
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        LEFT JOIN order_screening_cache osc ON osc.order_id = o.order_id
        LEFT JOIN LATERAL (
            SELECT id, screening_status, screening_code, override_policy,
                   reason_code, reason_text, mode, policy_version, actor, details, created_at
            FROM order_screening_override_audit soa
            WHERE soa.order_id = o.order_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) latest_override ON TRUE
        LEFT JOIN LATERAL (
            SELECT id, screening_status, business_bucket, screening_code,
                   action_type, handling_status, reason_text, assignee, actor, details, created_at
            FROM order_screening_action_audit saa
            WHERE saa.order_id = o.order_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) latest_action ON TRUE
        {where}
        ORDER BY o.due_date
        LIMIT %s OFFSET %s
    """, params + [size, offset])
    items = []
    for r in cur.fetchall():
        screening_result = r.get("screening_result") or {}
        items.append({
            "order_id": r["order_id"],
            "product_type": r["product_type"],
            "target_width": r["target_width"],
            "target_thickness": r["target_thickness"],
            "total_quantity_kg": r["total_quantity_kg"],
            "cleanroom_req": r["cleanroom_req"],
            "order_class": r["order_class"],
            "customer_class": r["customer_class"],
            "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            "material_available_time": r["material_available_time"].isoformat() if r["material_available_time"] else None,
            "status": r["status"],
            "corona_req": r["corona_req"],
            "core_size_inch": r["core_size_inch"],
            "priority_override": r["priority_override"],
            "assigned_machine": r["assigned_machine"],
            "screening": {
                "screening_status": r.get("screening_status"),
                "business_bucket": r.get("screening_business_bucket") or screening_result.get("business_bucket"),
                "code": r.get("screening_code"),
                "root_cause": r.get("screening_root_cause"),
                "is_stale": r.get("screening_is_stale"),
                "stale_reason": r.get("screening_stale_reason"),
                "recommendations": screening_result.get("recommendations") or [],
                "evidence": screening_result.get("evidence") or [],
                "override_decision": screening_result.get("override_decision"),
                "latest_override": _latest_screening_override_from_order_row(r),
                "latest_action": _latest_screening_action_from_order_row(r),
            } if r.get("screening_status") else None,
            "sched_start": r["sched_start"].isoformat() if r["sched_start"] else None,
            "sched_end": r["sched_end"].isoformat() if r["sched_end"] else None,
            "scrap_kg": float(r["scrap_kg"]) if r["scrap_kg"] else 0,
            "setup_mins": r["setup_time_mins"] if r["setup_time_mins"] else 0,
            "actual_material_kg": float(r["actual_material_required_kg"]) if r["actual_material_required_kg"] else 0,
        })

    cur.execute(f"""
        SELECT count(DISTINCT o.order_id) AS cnt
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        LEFT JOIN order_screening_cache osc ON osc.order_id = o.order_id
        LEFT JOIN LATERAL (
            SELECT action_type, handling_status, assignee
            FROM order_screening_action_audit saa
            WHERE saa.order_id = o.order_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) latest_action ON TRUE
        {where}
    """, params)
    total = cur.fetchone()["cnt"]
    action_status_counts = {value: 0 for value in SCREENING_HANDLING_STATUSES}
    action_status_counts["unhandled"] = 0
    cur.execute(f"""
        SELECT COALESCE(latest_action.handling_status, 'unhandled') AS handling_status,
               count(DISTINCT o.order_id) AS cnt
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        LEFT JOIN order_screening_cache osc ON osc.order_id = o.order_id
        LEFT JOIN LATERAL (
            SELECT action_type, handling_status, assignee
            FROM order_screening_action_audit saa
            WHERE saa.order_id = o.order_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) latest_action ON TRUE
        {where}
        GROUP BY COALESCE(latest_action.handling_status, 'unhandled')
    """, params)
    for row in cur.fetchall():
        status_key = row.get("handling_status") or "unhandled"
        action_status_counts[status_key] = int(row.get("cnt") or 0)
    action_type_counts = {value: 0 for value in SCREENING_ACTION_TYPES}
    action_type_counts["unhandled"] = 0
    cur.execute(f"""
        SELECT COALESCE(latest_action.action_type, 'unhandled') AS action_type,
               count(DISTINCT o.order_id) AS cnt
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        LEFT JOIN order_screening_cache osc ON osc.order_id = o.order_id
        LEFT JOIN LATERAL (
            SELECT action_type, handling_status, assignee
            FROM order_screening_action_audit saa
            WHERE saa.order_id = o.order_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) latest_action ON TRUE
        {where}
        GROUP BY COALESCE(latest_action.action_type, 'unhandled')
    """, params)
    for row in cur.fetchall():
        action_type_key = row.get("action_type") or "unhandled"
        action_type_counts[action_type_key] = int(row.get("cnt") or 0)
    action_assignee_counts = {}
    cur.execute(f"""
        SELECT COALESCE(latest_action.assignee, 'unassigned') AS assignee,
               count(DISTINCT o.order_id) AS cnt
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        LEFT JOIN order_screening_cache osc ON osc.order_id = o.order_id
        LEFT JOIN LATERAL (
            SELECT action_type, handling_status, assignee
            FROM order_screening_action_audit saa
            WHERE saa.order_id = o.order_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) latest_action ON TRUE
        {where}
        GROUP BY COALESCE(latest_action.assignee, 'unassigned')
    """, params)
    for row in cur.fetchall():
        assignee_key = row.get("assignee") or "unassigned"
        action_assignee_counts[assignee_key] = int(row.get("cnt") or 0)
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "screening_action_status_counts": action_status_counts,
        "screening_action_type_counts": action_type_counts,
        "screening_action_assignee_counts": action_assignee_counts,
    }


@router.post("")
def create_order(
    payload: OrderCreatePayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    _validate_order_enums(fields)

    if payload.status != "PENDING":
        raise HTTPException(status_code=400, detail="新建订单必须为待排状态。")

    customer_id = payload.customer_id or payload.customer_class
    if not customer_id:
        raise HTTPException(status_code=400, detail="客户信息不能为空。")

    _ensure_order_revision_schema(db)
    _ensure_order_screening_schema(db)
    cur = db.cursor()
    try:
        cur.execute("SELECT 1 FROM production_orders WHERE order_id=%s", (payload.order_id,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="订单已存在。")

        cur.execute("SELECT 1 FROM products WHERE product_type=%s", (payload.product_type,))
        if not cur.fetchone():
            raise HTTPException(status_code=400, detail="产品类型不存在。")

        cur.execute("""
            INSERT INTO customers (customer_id, customer_name, customer_class)
            VALUES (%s, %s, %s)
            ON CONFLICT (customer_id) DO NOTHING
        """, (customer_id, f"{customer_id} 客户", payload.customer_class))

        cur.execute("""
            INSERT INTO production_orders
                (order_id, customer_id, product_type, target_width, target_thickness,
                 total_quantity_kg, cleanroom_req, order_class, corona_req,
                 core_size_inch, order_date, due_date, material_available_time,
                 status, priority_override)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            payload.order_id,
            customer_id,
            payload.product_type,
            payload.target_width,
            payload.target_thickness,
            payload.total_quantity_kg,
            payload.cleanroom_req,
            payload.order_class,
            payload.corona_req,
            payload.core_size_inch,
            payload.order_date,
            payload.due_date,
            payload.material_available_time,
            "PENDING",
            payload.priority_override,
        ))

        cur.execute("SELECT * FROM production_orders WHERE order_id=%s", (payload.order_id,))
        created_row = cur.fetchone()
        after_state = _order_row_state(created_row)
        changed_fields = _order_revision_diff({}, after_state)
        revision_id = _insert_order_revision_audit(
            cur,
            order_id=payload.order_id,
            action_type="CREATE",
            changed_fields=changed_fields,
            before_state={},
            after_state=after_state,
            reason_code=payload.reason_code,
            reason_text=payload.reason_text,
            impacted_draft_run_ids=[],
            changed_by=user.username,
        )
        screening_result = _run_order_screening(db, order_ids=[payload.order_id], scope="selected")
        screening_item = screening_result["items"][0] if screening_result.get("items") else None
        _persist_order_screening_result(cur, screening_result)
        db.commit()
        return {
            "order_id": payload.order_id,
            "created": True,
            "revision_id": revision_id,
            "impacted_draft_run_ids": [],
            "screening": screening_item,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.post("/screening")
def screen_orders_endpoint(
    payload: OrderScreeningPayload,
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    scope = payload.scope.lower()
    if scope not in {"selected", "pending"}:
        raise HTTPException(status_code=400, detail="初筛范围无效。")

    order_ids = [item.strip() for item in payload.order_ids if item and item.strip()]
    order_ids = list(dict.fromkeys(order_ids))
    effective_scope = "selected" if order_ids and scope == "selected" else "pending"
    result = _run_order_screening(
        db,
        order_ids=order_ids if effective_scope == "selected" else None,
        scope=effective_scope,
    )
    _ensure_order_screening_schema(db)
    _persist_order_screening_result(db.cursor(), result)
    db.commit()
    return _filter_screening_result(result, payload.screening_status, payload.screening_bucket)


@router.get("/{order_id}/screening")
def get_order_screening(
    order_id: str,
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    _ensure_order_screening_schema(db)
    result = _run_order_screening(db, order_ids=[order_id], scope="selected")
    item = result["items"][0] if result["items"] else None
    if not item:
        raise HTTPException(status_code=404, detail="Order not found.")
    _persist_order_screening_result(db.cursor(), result)
    db.commit()
    return {
        **result,
        "item": item,
    }


@router.get("/screening-action-options")
def get_order_screening_action_options(
    _=Depends(get_current_user),
):
    return {
        "action_types": [
            {"value": value, "label": label}
            for value, label in SCREENING_ACTION_TYPE_OPTIONS
        ],
        "handling_statuses": [
            {"value": value, "label": label}
            for value, label in SCREENING_ACTION_FILTER_STATUS_OPTIONS
        ],
    }


@router.post("/{order_id}/screening-override")
def create_order_screening_override(
    order_id: str,
    payload: OrderScreeningOverridePayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    mode = payload.mode.lower()
    if mode not in {"formal", "experimental"}:
        raise HTTPException(status_code=400, detail="Invalid screening override mode.")

    _ensure_order_screening_schema(db)
    _ensure_order_screening_override_schema(db)
    cur = db.cursor()
    try:
        screening_result = _run_order_screening(db, order_ids=[order_id], scope="selected")
        screening_item = screening_result["items"][0] if screening_result.get("items") else None
        if not screening_item:
            raise HTTPException(status_code=404, detail="Order not found.")
        _persist_order_screening_result(cur, screening_result)

        override_decision = screening_item.get("override_decision") or {}
        if not override_decision.get("allowed"):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "screening_override_prohibited",
                    "order_id": order_id,
                    "override_decision": override_decision,
                },
            )
        if override_decision.get("requires_reason") and not payload.reason_text.strip():
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "screening_override_reason_required",
                    "order_id": order_id,
                    "override_decision": override_decision,
                },
            )

        cur.execute("SELECT policy_version FROM schedule_settings WHERE id=TRUE")
        row = cur.fetchone() or {}
        policy_version = int(row.get("policy_version") or 1)
        payload = payload.model_copy(update={"mode": mode})
        audit_id = _insert_order_screening_override_audit(
            cur,
            order_id=order_id,
            screening_item=screening_item,
            override_decision=override_decision,
            payload=payload,
            policy_version=policy_version,
            actor=user.username,
        )
        db.commit()
        return {
            "order_id": order_id,
            "override_audit_id": audit_id,
            "override": override_decision,
            "screening": screening_item,
            "mode": mode,
            "policy_version": policy_version,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.post("/{order_id}/screening-action")
def create_order_screening_action(
    order_id: str,
    payload: OrderScreeningActionPayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    action_type = payload.action_type.strip().lower()
    handling_status = payload.handling_status.strip().lower()
    reason_text = payload.reason_text.strip()
    if action_type not in SCREENING_ACTION_TYPES:
        raise HTTPException(status_code=400, detail="Invalid screening action type.")
    if handling_status not in SCREENING_HANDLING_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid screening handling status.")
    if not reason_text:
        raise HTTPException(status_code=400, detail="筛选异常处理原因不能为空。")

    _ensure_order_screening_schema(db)
    _ensure_order_screening_action_schema(db)
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT o.order_id, osc.screening_status, osc.business_bucket,
                   osc.code AS screening_code, osc.root_cause, osc.result AS screening_result
            FROM production_orders o
            LEFT JOIN order_screening_cache osc ON osc.order_id = o.order_id
            WHERE o.order_id=%s
        """, (order_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found.")
        if not row.get("screening_status"):
            raise HTTPException(
                status_code=400,
                detail={"code": "order_screening_required", "message": "请先完成订单筛选后再记录处理动作。"},
            )
        screening_status = str(row["screening_status"]).lower()
        if screening_status not in {"risk", "blocked"}:
            raise HTTPException(
                status_code=400,
                detail={"code": "screening_action_not_required", "message": "当前订单不需要异常处理动作。"},
            )

        screening_result = row.get("screening_result") or {}
        business_bucket = row.get("business_bucket") or screening_result.get("business_bucket")
        details = {
            "root_cause": row.get("root_cause"),
            "screening_result": screening_result,
        }
        cur.execute("""
            INSERT INTO order_screening_action_audit
                (order_id, screening_status, business_bucket, screening_code,
                 action_type, handling_status, reason_text, assignee, actor, details)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id, order_id, screening_status, business_bucket, screening_code,
                      action_type, handling_status, reason_text, assignee, actor, details, created_at
        """, (
            order_id,
            screening_status,
            business_bucket,
            row.get("screening_code"),
            action_type,
            handling_status,
            reason_text,
            payload.assignee.strip() if payload.assignee else None,
            user.username,
            Json(details),
        ))
        audit_row = cur.fetchone()
        db.commit()
        latest_action = _screening_action_audit_row_to_dict(audit_row)
        return {
            "order_id": order_id,
            "action_audit_id": latest_action["id"],
            "latest_action": latest_action,
        }
    except Exception:
        db.rollback()
        raise


@router.get("/{order_id}/screening-overrides")
def get_order_screening_overrides(
    order_id: str,
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    _ensure_order_screening_override_schema(db)
    cur = db.cursor()
    cur.execute("""
        SELECT id, order_id, screening_status, screening_code, override_policy,
            reason_code, reason_text, mode, policy_version, actor, details,
            created_at
        FROM order_screening_override_audit
        WHERE order_id=%s
        ORDER BY created_at DESC, id DESC
        LIMIT 50
    """, (order_id,))
    return {
        "order_id": order_id,
        "items": [
            _screening_override_audit_row_to_dict(row)
            for row in cur.fetchall()
        ],
    }


@router.get("/{order_id}/screening-actions")
def get_order_screening_actions(
    order_id: str,
    handling_status: Optional[str] = None,
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    _ensure_order_screening_action_schema(db)
    cur = db.cursor()
    where = "WHERE order_id=%s"
    params: list[Any] = [order_id]
    if handling_status:
        normalized_status = handling_status.lower()
        if normalized_status not in SCREENING_HANDLING_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid screening action status.")
        where += " AND handling_status=%s"
        params.append(normalized_status)
    cur.execute("""
        SELECT id, order_id, screening_status, business_bucket, screening_code,
            action_type, handling_status, reason_text, assignee, actor, details,
            created_at
        FROM order_screening_action_audit
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT 50
    """.format(where=where), params)
    return {
        "order_id": order_id,
        "items": [
            _screening_action_audit_row_to_dict(row)
            for row in cur.fetchall()
        ],
    }


@router.post("/import-preview")
def import_orders_preview(
    payload: OrderImportPreviewPayload,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    if not payload.rows:
        raise HTTPException(status_code=400, detail="请提供至少一行订单数据。")
    cur = db.cursor()
    existing_order_ids, product_types = _load_import_reference_sets(cur, payload.rows)
    return _preview_import_rows(
        payload.rows,
        existing_order_ids=existing_order_ids,
        product_types=product_types,
        conflict_policy=payload.conflict_policy,
    )


@router.post("/import-commit")
def import_orders_commit(
    payload: OrderImportCommitPayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    if not payload.rows:
        raise HTTPException(status_code=400, detail="请提供至少一行订单数据。")
    _ensure_order_revision_schema(db)
    _ensure_order_import_schema(db)
    _ensure_order_screening_schema(db)
    cur = db.cursor()
    try:
        existing_order_ids, product_types = _load_import_reference_sets(cur, payload.rows)
        preview = _preview_import_rows(
            payload.rows,
            existing_order_ids=existing_order_ids,
            product_types=product_types,
            conflict_policy=payload.conflict_policy,
        )
        accepted = _ensure_import_has_accepted_rows(preview["rows"])
        cur.execute("""
            INSERT INTO order_ingestion_batches
                (source_name, conflict_policy, total_rows, accepted_rows, rejected_rows, created_by)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            payload.source_name,
            payload.conflict_policy,
            preview["summary"]["total_rows"],
            len(accepted),
            preview["summary"]["rejected_count"] + preview["summary"]["conflict_count"] + preview["summary"]["duplicate_input_count"],
            user.username,
        ))
        batch_id = cur.fetchone()["id"]

        created_order_ids = []
        for row in preview["rows"]:
            created_order = row["row_status"] == "new"
            if created_order:
                _insert_order_from_import(cur, row["normalized_order"], user.username)
                created_order_ids.append(row["order_id"])
            cur.execute("""
                INSERT INTO order_ingestion_rows
                    (batch_id, row_index, order_id, row_status,
                     normalized_order, errors, warnings, created_order)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                batch_id,
                row["row_index"],
                row["order_id"],
                row["row_status"],
                Json(row["normalized_order"] or {}),
                Json(row["errors"]),
                Json(row["warnings"]),
                created_order,
            ))

        screening_result = _run_order_screening(db, order_ids=created_order_ids, scope="selected")
        _persist_order_screening_result(cur, screening_result)
        db.commit()
        return {
            "batch_id": batch_id,
            "created_order_ids": created_order_ids,
            "created_count": len(created_order_ids),
            "summary": preview["summary"],
            "screening": screening_result,
            "rows": preview["rows"],
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


@router.post("/reset-to-pending")
def reset_orders_to_pending(
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    cur = db.cursor()
    cur.execute("""
        WITH active_queue_orders AS (
            SELECT DISTINCT q.order_id
            FROM manufacturing_queue q
            JOIN schedule_runs r ON r.run_id=q.run_id
            WHERE r.is_active=TRUE
              AND r.lifecycle_status='CONFIRMED'
              AND q.queue_status IN ('QUEUED', 'READY', 'ON_HOLD', 'IN_PRODUCTION', 'COMPLETED')
        ),
        reset_rows AS (
            UPDATE production_orders o
            SET status='PENDING', updated_at=NOW()
            WHERE o.status='SCHEDULED'
              AND NOT EXISTS (
                  SELECT 1
                  FROM active_queue_orders aq
                  WHERE aq.order_id=o.order_id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM manufacturing_queue q
                  WHERE q.order_id=o.order_id
                    AND q.queue_status IN ('IN_PRODUCTION', 'COMPLETED')
              )
            RETURNING o.order_id
        )
        SELECT COUNT(*) AS updated_count FROM reset_rows
    """)
    updated = cur.fetchone()["updated_count"]
    cur.execute("SELECT COUNT(*) AS cnt FROM production_orders")
    total = cur.fetchone()["cnt"]
    db.commit()
    return {"scope": "orphaned_scheduled_orders", "updated_count": updated, "total_orders": total}


@router.patch("/{order_id}")
def update_order(
    order_id: str,
    payload: OrderUpdatePayload,
    db=Depends(get_db),
    user=Depends(require_role("admin", "planner")),
):
    fields = payload.changed_fields()
    if not fields:
        raise HTTPException(status_code=400, detail="No order fields to update.")

    _validate_order_enums(fields)

    _ensure_order_revision_schema(db)
    _ensure_order_screening_schema(db)
    cur = db.cursor()
    try:
        cur.execute("SELECT * FROM production_orders WHERE order_id=%s", (order_id,))
        before_row = cur.fetchone()
        if not before_row:
            raise HTTPException(status_code=404, detail="Order not found.")

        before_state = _order_row_state(before_row)
        if "product_type" in fields:
            cur.execute("SELECT 1 FROM products WHERE product_type=%s", (fields["product_type"],))
            if not cur.fetchone():
                raise HTTPException(status_code=400, detail="产品类型不存在。")

        diff = _order_revision_diff(before_state, fields)
        if not diff:
            db.rollback()
            return {"order_id": order_id, "updated": [], "revision_id": None, "impacted_draft_run_ids": []}

        assignments = []
        params = []
        for key, value in fields.items():
            assignments.append(f"{key}=%s")
            params.append(value)
        assignments.append("updated_at=NOW()")
        params.append(order_id)

        cur.execute(
            f"UPDATE production_orders SET {', '.join(assignments)} WHERE order_id=%s",
            params,
        )

        cur.execute("SELECT * FROM production_orders WHERE order_id=%s", (order_id,))
        after_row = cur.fetchone()
        after_state = _order_row_state(after_row)
        impacted_draft_run_ids = _find_impacted_draft_run_ids(cur, order_id)
        revision_id = _insert_order_revision_audit(
            cur,
            order_id=order_id,
            action_type="UPDATE",
            changed_fields=diff,
            before_state=before_state,
            after_state=after_state,
            reason_code=payload.reason_code,
            reason_text=payload.reason_text,
            impacted_draft_run_ids=impacted_draft_run_ids,
            changed_by=user.username,
        )
        screening_result = _run_order_screening(db, order_ids=[order_id], scope="selected")
        screening_item = screening_result["items"][0] if screening_result.get("items") else None
        _persist_order_screening_result(cur, screening_result)
        db.commit()
        return {
            "order_id": order_id,
            "updated": sorted(diff.keys()),
            "revision_id": revision_id,
            "impacted_draft_run_ids": impacted_draft_run_ids,
            "screening": screening_item,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
