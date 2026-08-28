"""Audit Wave 2 material-lot reservation consistency without mutating data.

Reservations are an execution/data-integrity concern separate from the optimizer. This
auditor detects double consumption, reservations against unusable lots, material-grade
mismatches, and order/material reservation coverage against the current requirement
calculation version.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATABASE_CONFIG
from scripts.rebuild_wave2_order_material_requirements import CALCULATION_VERSION


ACTIVE_RESERVATION_STATUSES = ("PLANNED", "CONFIRMED")


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )


def _rows(cur, sql: str, params=None):
    cur.execute(sql, params or ())
    return [dict(row) for row in cur.fetchall()]


def collect_reservation_audit(conn) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        active = _rows(
            cur,
            """
            SELECT r.reservation_id, r.inventory_id, r.order_id, r.recipe_version_id,
                   r.material_grade, r.reserved_quantity_kg, r.reservation_status,
                   i.material_grade AS lot_material_grade, i.lot_number,
                   i.quantity_kg AS lot_quantity_kg, i.status AS lot_status,
                   i.release_status, i.use_before_date
            FROM material_lot_reservations r
            JOIN material_inventory i ON i.id=r.inventory_id
            WHERE r.reservation_status = ANY(%s)
            ORDER BY r.inventory_id, r.reservation_id
            """,
            (list(ACTIVE_RESERVATION_STATUSES),),
        )
        over_reserved_lots = _rows(
            cur,
            """
            SELECT i.id AS inventory_id, i.material_grade, i.lot_number,
                   i.quantity_kg,
                   SUM(r.reserved_quantity_kg) AS reserved_quantity_kg
            FROM material_inventory i
            JOIN material_lot_reservations r ON r.inventory_id=i.id
            WHERE r.reservation_status = ANY(%s)
            GROUP BY i.id, i.material_grade, i.lot_number, i.quantity_kg
            HAVING SUM(r.reserved_quantity_kg) > i.quantity_kg
            ORDER BY i.id
            """,
            (list(ACTIVE_RESERVATION_STATUSES),),
        )
        reservation_coverage = _rows(
            cur,
            """
            WITH req AS (
                SELECT order_id, material_grade, SUM(gross_quantity_kg) AS required_kg
                FROM order_material_requirements
                WHERE calculation_version=%s
                GROUP BY order_id, material_grade
            ), res AS (
                SELECT order_id, material_grade, SUM(reserved_quantity_kg) AS reserved_kg
                FROM material_lot_reservations
                WHERE reservation_status = ANY(%s)
                GROUP BY order_id, material_grade
            )
            SELECT req.order_id, req.material_grade, req.required_kg,
                   COALESCE(res.reserved_kg,0) AS reserved_kg,
                   COALESCE(res.reserved_kg,0) - req.required_kg AS delta_kg
            FROM req
            LEFT JOIN res
              ON res.order_id=req.order_id AND res.material_grade=req.material_grade
            ORDER BY req.order_id, req.material_grade
            """,
            (CALCULATION_VERSION, list(ACTIVE_RESERVATION_STATUSES)),
        )

    material_mismatches = [
        row for row in active
        if row["material_grade"] != row["lot_material_grade"]
    ]
    unusable_lot_reservations = [
        row for row in active
        if row["lot_status"] != "IN_STOCK"
        or row["release_status"] != "RELEASED"
        or (row.get("use_before_date") is not None and row["use_before_date"].isoformat() <= __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat())
    ]
    over_reserved_requirements = [row for row in reservation_coverage if row["delta_kg"] > 0]
    under_reserved_requirements = [row for row in reservation_coverage if row["delta_kg"] < 0]

    blockers = []
    if material_mismatches:
        blockers.append("reservation_material_grade_mismatch")
    if unusable_lot_reservations:
        blockers.append("active_reservation_uses_unusable_lot")
    if over_reserved_lots:
        blockers.append("lot_over_reserved")
    if over_reserved_requirements:
        blockers.append("order_material_over_reserved")

    return {
        "calculation_version": CALCULATION_VERSION,
        "active_reservation_count": len(active),
        "material_grade_mismatch_count": len(material_mismatches),
        "unusable_lot_reservation_count": len(unusable_lot_reservations),
        "over_reserved_lot_count": len(over_reserved_lots),
        "over_reserved_requirement_count": len(over_reserved_requirements),
        "under_reserved_requirement_count": len(under_reserved_requirements),
        "safe": len(blockers) == 0,
        "blockers": blockers,
        "details": {
            "material_grade_mismatches": material_mismatches,
            "unusable_lot_reservations": unusable_lot_reservations,
            "over_reserved_lots": over_reserved_lots,
            "over_reserved_requirements": over_reserved_requirements,
            "under_reserved_requirements": under_reserved_requirements,
        },
        "note": (
            "Under-reservation is reported but is not automatically a data-integrity blocker because reservations may be created only after scheduling/confirmation. "
            "Over-reservation and unusable-lot reservations are always invalid."
        ),
    }


def main() -> int:
    conn = _connect()
    try:
        report = collect_reservation_audit(conn)
    finally:
        conn.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["safe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
