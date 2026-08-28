"""Extended Wave 2 industrial benchmark readiness audit.

This builds on audit_wave2_domain_coverage and checks the data paths Wave 3 will
actually consume: recipe material requirements, explicit CORONA capability, machine
material capability, known material identity, and at least one qualified Machine x
Recipe rate for each released recipe used by an active order.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATABASE_CONFIG
from scripts.audit_wave2_domain_coverage import collect_coverage
from scripts.rebuild_wave2_order_material_requirements import CALCULATION_VERSION


UNKNOWN_POLYMER_FAMILIES = ("", "UNKNOWN", "OTHER", "UNCLASSIFIED", "N/A", "NA")


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )


def _scalar(cur, sql: str, params=None) -> int:
    cur.execute(sql, params or ())
    row = cur.fetchone()
    return int(next(iter(row.values())))


def collect_extended(conn) -> dict:
    base = collect_coverage(conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        active_orders = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM production_orders WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION')",
        )
        active_orders_with_requirements = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT o.order_id) AS n
            FROM production_orders o
            JOIN order_material_requirements r ON r.order_id=o.order_id
            WHERE o.status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
              AND r.calculation_version=%s
            """,
            (CALCULATION_VERSION,),
        )
        requirement_rows = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM order_material_requirements WHERE calculation_version=%s",
            (CALCULATION_VERSION,),
        )
        shortage_rows = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM order_material_requirements
            WHERE calculation_version=%s AND shortage_quantity_kg > 0
            """,
            (CALCULATION_VERSION,),
        )

        active_machines = _scalar(cur, "SELECT COUNT(*) AS n FROM machines WHERE status='ACTIVE'")
        corona_explicit = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_feature_capabilities f
            JOIN machines m ON m.machine_id=f.machine_id
            WHERE m.status='ACTIVE' AND f.feature_code='CORONA'
            """,
        )
        machine_material_capabilities = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM machine_material_capabilities WHERE capability_status='QUALIFIED'",
        )

        active_released_recipes = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT o.recipe_version_id) AS n
            FROM production_orders o
            JOIN recipe_versions rv ON rv.recipe_version_id=o.recipe_version_id
            WHERE o.status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
              AND rv.status='RELEASED'
            """,
        )
        active_released_recipes_with_rate = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT o.recipe_version_id) AS n
            FROM production_orders o
            JOIN recipe_versions rv ON rv.recipe_version_id=o.recipe_version_id
            JOIN machine_recipe_capabilities c ON c.recipe_version_id=o.recipe_version_id
            WHERE o.status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
              AND rv.status='RELEASED'
              AND c.eligibility_status='QUALIFIED'
              AND c.standard_rate_kg_h > 0
            """,
        )

        released_recipe_materials = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT rl.material_grade) AS n
            FROM recipe_layers rl
            JOIN recipe_versions rv ON rv.recipe_version_id=rl.recipe_version_id
            WHERE rv.status='RELEASED'
            """,
        )
        released_recipe_materials_qualified = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT rl.material_grade) AS n
            FROM recipe_layers rl
            JOIN recipe_versions rv ON rv.recipe_version_id=rl.recipe_version_id
            JOIN material_qualifications q ON q.material_grade=rl.material_grade
            WHERE rv.status='RELEASED'
              AND q.qualification_status='APPROVED'
              AND q.valid_to IS NULL
            """,
        )
        released_recipe_excluded_materials = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT rl.material_grade) AS n
            FROM recipe_layers rl
            JOIN recipe_versions rv ON rv.recipe_version_id=rl.recipe_version_id
            JOIN material_qualifications q ON q.material_grade=rl.material_grade
            WHERE rv.status='RELEASED'
              AND q.qualification_status='EXCLUDED_MEDICAL'
              AND q.valid_to IS NULL
            """,
        )
        released_recipe_unknown_polymer_materials = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT rl.material_grade) AS n
            FROM recipe_layers rl
            JOIN recipe_versions rv ON rv.recipe_version_id=rl.recipe_version_id
            JOIN raw_materials r ON r.material_grade=rl.material_grade
            WHERE rv.status='RELEASED'
              AND UPPER(COALESCE(NULLIF(TRIM(r.polymer_family), ''), 'UNKNOWN')) = ANY(%s)
            """,
            (list(UNKNOWN_POLYMER_FAMILIES),),
        )

    blockers = []
    if not base["readiness"]["safe_for_benchmark_hard"]:
        blockers.extend(base["readiness"]["benchmark_hard_blockers"])
    if active_orders and active_orders_with_requirements < active_orders:
        blockers.append("active_orders_missing_material_requirements")
    if active_machines and corona_explicit < active_machines:
        blockers.append("active_machines_missing_explicit_corona_capability")
    if machine_material_capabilities == 0:
        blockers.append("no_qualified_machine_material_capability")
    if active_released_recipes and active_released_recipes_with_rate < active_released_recipes:
        blockers.append("active_released_recipe_missing_qualified_machine_rate")
    if released_recipe_materials and released_recipe_materials_qualified < released_recipe_materials:
        blockers.append("released_recipe_material_missing_benchmark_qualification")
    if released_recipe_excluded_materials:
        blockers.append("released_recipe_contains_explicitly_excluded_medical_material")
    if released_recipe_unknown_polymer_materials:
        blockers.append("released_recipe_contains_unknown_polymer_family")

    base["benchmark_extended"] = {
        "calculation_version": CALCULATION_VERSION,
        "active_orders": active_orders,
        "active_orders_with_material_requirements": active_orders_with_requirements,
        "material_requirement_rows": requirement_rows,
        "material_shortage_rows": shortage_rows,
        "active_machines": active_machines,
        "machines_with_explicit_corona_capability": corona_explicit,
        "qualified_machine_material_capability_rows": machine_material_capabilities,
        "active_released_recipes": active_released_recipes,
        "active_released_recipes_with_qualified_rate": active_released_recipes_with_rate,
        "released_recipe_material_grades": released_recipe_materials,
        "released_recipe_material_grades_approved": released_recipe_materials_qualified,
        "released_recipe_explicit_excluded_material_grades": released_recipe_excluded_materials,
        "released_recipe_unknown_polymer_material_grades": released_recipe_unknown_polymer_materials,
        "safe_for_wave3_shadow_benchmark": len(blockers) == 0,
        "blockers": sorted(set(blockers)),
        "note": (
            "Material shortage rows are valid scenario state and are reported, but shortage alone is not a data-completeness blocker. "
            "UNKNOWN/OTHER polymer family is a master-data blocker, not a PE default."
        )
    }
    return base


def main() -> int:
    conn = _connect()
    try:
        report = collect_extended(conn)
    finally:
        conn.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["benchmark_extended"]["safe_for_wave3_shadow_benchmark"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
