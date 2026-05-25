"""Stable snapshot helpers for schedule planning inputs."""

from __future__ import annotations

import datetime
import hashlib
import json
from decimal import Decimal
from typing import Any, Iterable


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

MACHINE_CAPABILITY_FIELDS = (
    "machine_id",
    "status",
    "cleanroom_level",
    "layer_structure",
    "die_diameter_mm",
    "min_width",
    "max_width",
    "min_thickness",
    "max_thickness",
    "hourly_output_kg",
    "max_slitting_lanes",
)

MAINTENANCE_CALENDAR_FIELDS = (
    "machine_id",
    "start_time",
    "end_time",
    "maintenance_type",
    "reason",
    "is_enabled",
)

RULE_MATRIX_FIELDS = (
    "table",
    "key",
    "values",
    "is_enabled",
)

PROCESS_FIELDS = (
    "product_type",
    "layer",
    "material_grade",
    "ratio_pct",
)


def snapshot_value(value: Any) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): snapshot_value(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [snapshot_value(item) for item in value]
    if isinstance(value, set):
        return sorted(snapshot_value(item) for item in value)
    return value


def stable_hash(payload: Any) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _row_dict(row: Any) -> dict[str, Any]:
    return dict(row or {})


def _fields(row: Any, field_names: Iterable[str]) -> dict[str, Any]:
    data = _row_dict(row)
    return {key: snapshot_value(data.get(key)) for key in field_names}


def _collection_snapshot(
    rows: Iterable[Any],
    *,
    fields: Iterable[str],
    sort_keys: Iterable[str],
) -> dict[str, Any]:
    normalized = [_fields(row, fields) for row in rows or []]
    normalized.sort(key=lambda item: tuple(item.get(key) or "" for key in sort_keys))
    return {
        "count": len(normalized),
        "hash": stable_hash(normalized),
    }


def build_order_snapshot(row: Any) -> dict[str, Any]:
    data = _row_dict(row)
    fields = _fields(data, ORDER_SNAPSHOT_FIELDS)
    snapshot = {
        "order_id": data.get("order_id"),
        "updated_at": snapshot_value(data.get("updated_at")),
        "fields": fields,
    }
    snapshot["hash"] = stable_hash(fields)
    return snapshot


def build_machine_capability_snapshot(rows: Iterable[Any]) -> dict[str, Any]:
    return _collection_snapshot(
        rows,
        fields=MACHINE_CAPABILITY_FIELDS,
        sort_keys=("machine_id",),
    )


def build_maintenance_calendar_snapshot(rows: Iterable[Any]) -> dict[str, Any]:
    return _collection_snapshot(
        rows,
        fields=MAINTENANCE_CALENDAR_FIELDS,
        sort_keys=("machine_id", "start_time", "end_time", "maintenance_type"),
    )


def build_rule_matrix_snapshot(rows: Iterable[Any]) -> dict[str, Any]:
    return _collection_snapshot(
        rows,
        fields=RULE_MATRIX_FIELDS,
        sort_keys=("table", "key"),
    )


def build_process_snapshot(rows: Iterable[Any]) -> dict[str, Any]:
    return _collection_snapshot(
        rows,
        fields=PROCESS_FIELDS,
        sort_keys=("product_type", "layer", "material_grade"),
    )


def build_input_snapshot(
    *,
    order_snapshots: list[dict[str, Any]],
    machine_capability_snapshot: dict[str, Any],
    maintenance_calendar_snapshot: dict[str, Any],
    rule_matrix_snapshot: dict[str, Any],
    process_snapshot: dict[str, Any],
    screening_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    orders = {
        "count": len(order_snapshots or []),
        "hash": stable_hash(
            sorted(
                (
                    {
                        "order_id": item.get("order_id"),
                        "hash": item.get("hash"),
                    }
                    for item in order_snapshots or []
                ),
                key=lambda item: item.get("order_id") or "",
            )
        ),
    }
    snapshot = {
        "orders": orders,
        "machine_capability": machine_capability_snapshot,
        "maintenance_calendar": maintenance_calendar_snapshot,
        "rule_matrix": rule_matrix_snapshot,
        "process": process_snapshot,
        "screening": screening_snapshot or {"hash": stable_hash([]), "count": 0},
    }
    snapshot["hash"] = stable_hash(snapshot)
    return snapshot
