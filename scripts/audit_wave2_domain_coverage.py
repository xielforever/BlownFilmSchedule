"""Report Wave 2 domain-data coverage without changing scheduling behavior.

Use after applying db/migrations/20260828_wave2_domain_schema.sql. The report is
intended to decide when it is safe to move domain_v2_enforcement_mode from
LEGACY to SHADOW. It never changes the enforcement mode.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATABASE_CONFIG


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


def collect_coverage(conn) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT domain_v2_enforcement_mode FROM schedule_settings WHERE id=TRUE"
        )
        mode_row = cur.fetchone() or {}

        orders_total = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM production_orders "
            "WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION')",
        )
        orders_with_recipe_version = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM production_orders "
            "WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION') "
            "AND recipe_version_id IS NOT NULL",
        )
        orders_with_released_recipe = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM production_orders o
            JOIN recipe_versions rv ON rv.recipe_version_id=o.recipe_version_id
            WHERE o.status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
              AND rv.status='RELEASED'
            """,
        )

        recipe_total = _scalar(cur, "SELECT COUNT(*) AS n FROM recipe_versions")
        recipe_released = _scalar(
            cur, "SELECT COUNT(*) AS n FROM recipe_versions WHERE status='RELEASED'"
        )
        recipe_structurally_releasable = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM v_recipe_version_validation "
            "WHERE structurally_releasable=TRUE",
        )
        recipe_missing_ratios = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM v_recipe_version_validation "
            "WHERE missing_ratio_count > 0",
        )
        recipe_unknown_route = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM recipe_versions WHERE process_route='UNKNOWN'",
        )

        active_machines = _scalar(
            cur, "SELECT COUNT(*) AS n FROM machines WHERE status='ACTIVE'"
        )
        machine_profiles = _scalar(cur, "SELECT COUNT(*) AS n FROM machine_capability_profiles")
        machines_known_route = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_capability_profiles p
            JOIN machines m ON m.machine_id=p.machine_id
            WHERE m.status='ACTIVE' AND p.process_route <> 'UNKNOWN'
            """,
        )
        machines_medical_released = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_capability_profiles p
            JOIN machines m ON m.machine_id=p.machine_id
            WHERE m.status='ACTIVE'
              AND p.medical_release_status NOT IN ('UNKNOWN','NOT_QUALIFIED')
            """,
        )
        machine_recipe_capabilities = _scalar(
            cur, "SELECT COUNT(*) AS n FROM machine_recipe_capabilities"
        )
        qualified_machine_recipe_rates = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_recipe_capabilities
            WHERE eligibility_status='QUALIFIED'
              AND standard_rate_kg_h > 0
            """,
        )

        material_total = _scalar(cur, "SELECT COUNT(*) AS n FROM raw_materials")
        material_evidence = _scalar(cur, "SELECT COUNT(DISTINCT material_grade) AS n FROM material_application_evidence")
        material_approved = _scalar(
            cur,
            "SELECT COUNT(DISTINCT material_grade) AS n FROM material_qualifications "
            "WHERE qualification_status='APPROVED'",
        )
        material_explicit_exclusions = _scalar(
            cur,
            "SELECT COUNT(DISTINCT material_grade) AS n FROM material_application_evidence "
            "WHERE evidence_status='EXPLICITLY_EXCLUDED_MEDICAL'",
        )

        lots_total = _scalar(cur, "SELECT COUNT(*) AS n FROM material_inventory")
        lots_released = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM material_inventory WHERE release_status='RELEASED'",
        )
        lots_unknown_release = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM material_inventory WHERE release_status='UNKNOWN'",
        )

        cleaning_groups = _scalar(cur, "SELECT COUNT(*) AS n FROM cleaning_validation_groups")
        cleaning_rules = _scalar(cur, "SELECT COUNT(*) AS n FROM cleaning_transition_rules")
        provenance_sources = _scalar(cur, "SELECT COUNT(*) AS n FROM provenance_sources")
        legacy_policy_source_links = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM entity_source_links "
            "WHERE entity_type='schedule_settings' AND source_role='LEGACY_ORIGIN'",
        )

    def pct(numerator: int, denominator: int):
        if denominator <= 0:
            return None
        return round(numerator / denominator * 100.0, 2)

    report = {
        "domain_v2_enforcement_mode": mode_row.get("domain_v2_enforcement_mode"),
        "orders": {
            "active_total": orders_total,
            "with_recipe_version": orders_with_recipe_version,
            "with_recipe_version_pct": pct(orders_with_recipe_version, orders_total),
            "with_released_recipe": orders_with_released_recipe,
            "with_released_recipe_pct": pct(orders_with_released_recipe, orders_total),
        },
        "recipes": {
            "total_versions": recipe_total,
            "released": recipe_released,
            "structurally_releasable": recipe_structurally_releasable,
            "missing_ratio": recipe_missing_ratios,
            "unknown_process_route": recipe_unknown_route,
        },
        "machines": {
            "active_total": active_machines,
            "profiles": machine_profiles,
            "known_process_route": machines_known_route,
            "known_process_route_pct": pct(machines_known_route, active_machines),
            "medical_released": machines_medical_released,
            "machine_recipe_capabilities": machine_recipe_capabilities,
            "qualified_machine_recipe_rates": qualified_machine_recipe_rates,
        },
        "materials": {
            "total_grades": material_total,
            "grades_with_manufacturer_evidence": material_evidence,
            "plant_approved_grades": material_approved,
            "explicit_medical_exclusions": material_explicit_exclusions,
        },
        "inventory": {
            "lots_total": lots_total,
            "released_lots": lots_released,
            "unknown_release_lots": lots_unknown_release,
        },
        "cleaning": {
            "validation_groups": cleaning_groups,
            "transition_rules": cleaning_rules,
        },
        "provenance": {
            "sources": provenance_sources,
            "legacy_policy_source_links": legacy_policy_source_links,
        },
    }

    hard_readiness_blockers = []
    if orders_total and orders_with_released_recipe < orders_total:
        hard_readiness_blockers.append("active_orders_missing_released_recipe")
    if active_machines and machines_known_route < active_machines:
        hard_readiness_blockers.append("active_machines_unknown_process_route")
    if qualified_machine_recipe_rates == 0:
        hard_readiness_blockers.append("no_qualified_machine_recipe_rate")
    if material_approved == 0:
        hard_readiness_blockers.append("no_plant_approved_material_qualification")
    if lots_total and lots_released == 0:
        hard_readiness_blockers.append("no_released_material_lots")
    if cleaning_groups == 0 or cleaning_rules == 0:
        hard_readiness_blockers.append("canonical_cleaning_taxonomy_incomplete")

    report["readiness"] = {
        "safe_for_shadow": len(hard_readiness_blockers) <= 4,
        "safe_for_hard": len(hard_readiness_blockers) == 0,
        "hard_readiness_blockers": hard_readiness_blockers,
        "note": (
            "safe_for_shadow is an engineering migration hint, not a regulatory approval. "
            "HARD requires all listed blockers resolved and benchmark validation."
        ),
    }
    return report


def main() -> int:
    conn = _connect()
    try:
        report = collect_coverage(conn)
    finally:
        conn.close()

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["readiness"]["safe_for_hard"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
