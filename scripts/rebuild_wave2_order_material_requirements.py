"""Rebuild explicit order material requirements from versioned recipe ratios.

This is a Wave 2 data-derivation tool, not a solver change. It aggregates layers that use
the same material grade and writes one requirement row per order/material. It never
fabricates missing ratios and never treats expected in-transit stock as released stock.

Run after recipe_version_id bindings and lot release classification exist.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATABASE_CONFIG


CALCULATION_VERSION = "W2-ORDER-MATERIAL-REQ-v1"


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def rebuild(conn, *, setup_buffer_per_material_kg: Decimal, dry_run: bool) -> dict:
    summary = {
        "active_orders": 0,
        "requirements_written": 0,
        "orders_blocked_missing_recipe": [],
        "orders_blocked_invalid_recipe": [],
        "materials_with_shortage": 0,
        "total_shortage_kg": "0.000",
        "calculation_version": CALCULATION_VERSION,
        "setup_buffer_per_material_kg": str(setup_buffer_per_material_kg),
    }

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT o.order_id, o.total_quantity_kg, o.recipe_version_id,
                   rv.status AS recipe_status,
                   v.layer_count_ok, v.ratio_complete, v.ratio_sum_ok
            FROM production_orders o
            LEFT JOIN recipe_versions rv ON rv.recipe_version_id=o.recipe_version_id
            LEFT JOIN v_recipe_version_validation v ON v.recipe_version_id=o.recipe_version_id
            WHERE o.status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
            ORDER BY o.order_id
            """
        )
        orders = [dict(row) for row in cur.fetchall()]
        summary["active_orders"] = len(orders)

        cur.execute(
            """
            SELECT material_grade, COALESCE(SUM(available_quantity_kg),0) AS available_kg
            FROM v_material_lot_available
            GROUP BY material_grade
            """
        )
        available = {row["material_grade"]: Decimal(str(row["available_kg"])) for row in cur.fetchall()}

        if not dry_run:
            cur.execute(
                "DELETE FROM order_material_requirements WHERE calculation_version=%s",
                (CALCULATION_VERSION,),
            )

        total_shortage = Decimal("0")
        for order in orders:
            if not order.get("recipe_version_id"):
                summary["orders_blocked_missing_recipe"].append(order["order_id"])
                continue
            if not all(bool(order.get(key)) for key in ("layer_count_ok", "ratio_complete", "ratio_sum_ok")):
                summary["orders_blocked_invalid_recipe"].append(order["order_id"])
                continue

            cur.execute(
                """
                SELECT material_grade, SUM(ratio_pct) AS ratio_pct
                FROM recipe_layers
                WHERE recipe_version_id=%s
                GROUP BY material_grade
                ORDER BY material_grade
                """,
                (order["recipe_version_id"],),
            )
            material_ratios = [dict(row) for row in cur.fetchall()]
            quantity = Decimal(str(order["total_quantity_kg"]))

            for item in material_ratios:
                ratio = Decimal(str(item["ratio_pct"]))
                net = _q(quantity * ratio / Decimal("100"))
                buffer_kg = _q(setup_buffer_per_material_kg)
                gross = _q(net + buffer_kg)
                released = _q(available.get(item["material_grade"], Decimal("0")))
                shortage = _q(max(Decimal("0"), gross - released))
                if shortage > 0:
                    summary["materials_with_shortage"] += 1
                    total_shortage += shortage

                if not dry_run:
                    cur.execute(
                        """
                        INSERT INTO order_material_requirements
                            (order_id, recipe_version_id, material_grade, layer_index,
                             net_quantity_kg, setup_buffer_kg, gross_quantity_kg,
                             released_available_kg, shortage_quantity_kg,
                             earliest_feasible_time, calculation_version)
                        VALUES (%s,%s,%s,NULL,%s,%s,%s,%s,%s,NULL,%s)
                        ON CONFLICT (
                            order_id,
                            (COALESCE(recipe_version_id, '')),
                            material_grade,
                            (COALESCE(layer_index, 0)),
                            calculation_version
                        ) DO UPDATE SET
                            net_quantity_kg=EXCLUDED.net_quantity_kg,
                            setup_buffer_kg=EXCLUDED.setup_buffer_kg,
                            gross_quantity_kg=EXCLUDED.gross_quantity_kg,
                            released_available_kg=EXCLUDED.released_available_kg,
                            shortage_quantity_kg=EXCLUDED.shortage_quantity_kg,
                            earliest_feasible_time=EXCLUDED.earliest_feasible_time,
                            calculated_at=NOW()
                        """,
                        (
                            order["order_id"], order["recipe_version_id"], item["material_grade"],
                            net, buffer_kg, gross, released, shortage, CALCULATION_VERSION,
                        ),
                    )
                    summary["requirements_written"] += 1

        summary["total_shortage_kg"] = str(_q(total_shortage))

    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-buffer-per-material-kg", type=Decimal, default=Decimal("0"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.setup_buffer_per_material_kg < 0:
        raise ValueError("setup buffer must be >= 0")

    conn = _connect()
    try:
        summary = rebuild(
            conn,
            setup_buffer_per_material_kg=args.setup_buffer_per_material_kg,
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["orders_blocked_missing_recipe"] or summary["orders_blocked_invalid_recipe"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
