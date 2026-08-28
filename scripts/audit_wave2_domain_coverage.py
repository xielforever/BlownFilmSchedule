"""Report Wave 2 domain-data coverage without changing scheduling behavior.

Use after applying the Wave 2 schema and optional master-data population. This report
separates three concepts:
- SHADOW readiness: enough explicit data exists to compare V2 decisions with legacy behavior;
- BENCHMARK_HARD readiness: fully explicit simulated/plant data can drive deterministic industrial benchmark scenarios;
- PRODUCTION_HARD readiness: hard-driving data is backed by plant/engineering/learned operational provenance.

The tool never changes domain_v2_enforcement_mode.
"""

from __future__ import annotations

import json
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATABASE_CONFIG


OPERATIONAL_SOURCE_TYPES = ("PLANT_MASTER", "PLANT_SOP", "ENGINEERING", "LEARNED")


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


def _pct(numerator: int, denominator: int):
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 2)


def collect_coverage(conn) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT domain_v2_enforcement_mode FROM schedule_settings WHERE id=TRUE")
        mode_row = cur.fetchone() or {}

        orders_total = _scalar(cur, "SELECT COUNT(*) AS n FROM production_orders WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION')")
        orders_with_recipe_version = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM production_orders WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION') AND recipe_version_id IS NOT NULL",
        )
        orders_with_released_recipe = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM production_orders o
            JOIN recipe_versions rv ON rv.recipe_version_id=o.recipe_version_id
            WHERE o.status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
              AND rv.status='RELEASED' AND rv.valid_to IS NULL
            """,
        )

        recipe_total = _scalar(cur, "SELECT COUNT(*) AS n FROM recipe_versions")
        recipe_released = _scalar(cur, "SELECT COUNT(*) AS n FROM recipe_versions WHERE status='RELEASED' AND valid_to IS NULL")
        recipe_structurally_releasable = _scalar(cur, "SELECT COUNT(*) AS n FROM v_recipe_version_validation WHERE structurally_releasable=TRUE")
        recipe_missing_ratios = _scalar(cur, "SELECT COUNT(*) AS n FROM v_recipe_version_validation WHERE missing_ratio_count > 0")
        recipe_unknown_route = _scalar(cur, "SELECT COUNT(*) AS n FROM recipe_versions WHERE process_route='UNKNOWN'")

        active_machines = _scalar(cur, "SELECT COUNT(*) AS n FROM machines WHERE status='ACTIVE'")
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
        machine_recipe_capabilities = _scalar(cur, "SELECT COUNT(*) AS n FROM machine_recipe_capabilities")
        qualified_machine_recipe_rates = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM machine_recipe_capabilities WHERE eligibility_status='QUALIFIED' AND standard_rate_kg_h > 0",
        )
        qualified_machine_recipe_rates_operational = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_recipe_capabilities c
            JOIN provenance_sources s ON s.source_id=c.source_id
            WHERE c.eligibility_status='QUALIFIED'
              AND c.standard_rate_kg_h > 0
              AND s.source_type = ANY(%s)
            """,
            (list(OPERATIONAL_SOURCE_TYPES),),
        )
        qualified_machine_recipe_rates_simulated = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_recipe_capabilities c
            JOIN provenance_sources s ON s.source_id=c.source_id
            WHERE c.eligibility_status='QUALIFIED'
              AND c.standard_rate_kg_h > 0
              AND s.source_type='SIMULATED'
            """,
        )
        unknown_shadow_rate_rows = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM machine_recipe_capabilities c
            WHERE c.eligibility_status='UNKNOWN' AND c.standard_rate_kg_h > 0
            """,
        )

        material_total = _scalar(cur, "SELECT COUNT(*) AS n FROM raw_materials")
        material_evidence = _scalar(cur, "SELECT COUNT(DISTINCT material_grade) AS n FROM material_application_evidence")
        material_approved = _scalar(
            cur,
            "SELECT COUNT(DISTINCT material_grade) AS n FROM material_qualifications WHERE qualification_status='APPROVED' AND valid_to IS NULL",
        )
        material_approved_operational = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT q.material_grade) AS n
            FROM material_qualifications q
            JOIN provenance_sources s ON s.source_id=q.source_id
            WHERE q.qualification_status='APPROVED' AND q.valid_to IS NULL
              AND s.source_type = ANY(%s)
            """,
            (list(OPERATIONAL_SOURCE_TYPES),),
        )
        material_approved_simulated = _scalar(
            cur,
            """
            SELECT COUNT(DISTINCT q.material_grade) AS n
            FROM material_qualifications q
            JOIN provenance_sources s ON s.source_id=q.source_id
            WHERE q.qualification_status='APPROVED' AND q.valid_to IS NULL
              AND s.source_type='SIMULATED'
            """,
        )
        material_explicit_exclusions = _scalar(
            cur,
            "SELECT COUNT(DISTINCT material_grade) AS n FROM material_application_evidence WHERE evidence_status='EXPLICITLY_EXCLUDED_MEDICAL'",
        )

        lots_total = _scalar(cur, "SELECT COUNT(*) AS n FROM material_inventory")
        lots_released = _scalar(cur, "SELECT COUNT(*) AS n FROM material_inventory WHERE release_status='RELEASED'")
        lots_released_operational = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM material_inventory i
            JOIN provenance_sources s ON s.source_id=i.source_id
            WHERE i.release_status='RELEASED' AND s.source_type = ANY(%s)
            """,
            (list(OPERATIONAL_SOURCE_TYPES),),
        )
        lots_released_simulated = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM material_inventory i
            JOIN provenance_sources s ON s.source_id=i.source_id
            WHERE i.release_status='RELEASED' AND s.source_type='SIMULATED'
            """,
        )
        lots_unknown_release = _scalar(cur, "SELECT COUNT(*) AS n FROM material_inventory WHERE release_status='UNKNOWN'")

        cleaning_groups = _scalar(cur, "SELECT COUNT(*) AS n FROM cleaning_validation_groups")
        cleaning_rules = _scalar(cur, "SELECT COUNT(*) AS n FROM cleaning_transition_rules")
        cleaning_rules_operational = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM cleaning_transition_rules r
            JOIN provenance_sources s ON s.source_id=r.source_id
            WHERE s.source_type = ANY(%s)
            """,
            (list(OPERATIONAL_SOURCE_TYPES),),
        )
        cleaning_rules_simulated = _scalar(
            cur,
            """
            SELECT COUNT(*) AS n
            FROM cleaning_transition_rules r
            JOIN provenance_sources s ON s.source_id=r.source_id
            WHERE s.source_type='SIMULATED'
            """,
        )

        provenance_sources = _scalar(cur, "SELECT COUNT(*) AS n FROM provenance_sources")
        legacy_policy_source_links = _scalar(
            cur,
            "SELECT COUNT(*) AS n FROM entity_source_links WHERE entity_type='schedule_settings' AND source_role='LEGACY_ORIGIN'",
        )

    report = {
        "domain_v2_enforcement_mode": mode_row.get("domain_v2_enforcement_mode"),
        "orders": {
            "active_total": orders_total,
            "with_recipe_version": orders_with_recipe_version,
            "with_recipe_version_pct": _pct(orders_with_recipe_version, orders_total),
            "with_released_recipe": orders_with_released_recipe,
            "with_released_recipe_pct": _pct(orders_with_released_recipe, orders_total),
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
            "known_process_route_pct": _pct(machines_known_route, active_machines),
            "medical_released": machines_medical_released,
            "machine_recipe_capabilities": machine_recipe_capabilities,
            "qualified_machine_recipe_rates_any_source": qualified_machine_recipe_rates,
            "qualified_machine_recipe_rates_operational": qualified_machine_recipe_rates_operational,
            "qualified_machine_recipe_rates_simulated": qualified_machine_recipe_rates_simulated,
            "unknown_shadow_rate_rows": unknown_shadow_rate_rows,
        },
        "materials": {
            "total_grades": material_total,
            "grades_with_manufacturer_evidence": material_evidence,
            "approved_grades_any_source": material_approved,
            "approved_grades_operational": material_approved_operational,
            "approved_grades_simulated": material_approved_simulated,
            "explicit_medical_exclusions": material_explicit_exclusions,
        },
        "inventory": {
            "lots_total": lots_total,
            "released_lots_any_source": lots_released,
            "released_lots_operational": lots_released_operational,
            "released_lots_simulated": lots_released_simulated,
            "unknown_release_lots": lots_unknown_release,
        },
        "cleaning": {
            "validation_groups": cleaning_groups,
            "transition_rules_any_source": cleaning_rules,
            "transition_rules_operational": cleaning_rules_operational,
            "transition_rules_simulated": cleaning_rules_simulated,
        },
        "provenance": {
            "sources": provenance_sources,
            "legacy_policy_source_links": legacy_policy_source_links,
        },
    }

    common_blockers = []
    if orders_total and orders_with_released_recipe < orders_total:
        common_blockers.append("active_orders_missing_released_recipe")
    if recipe_missing_ratios > 0 or recipe_unknown_route > 0:
        common_blockers.append("recipe_master_incomplete")
    if active_machines and machines_known_route < active_machines:
        common_blockers.append("active_machines_unknown_process_route")
    if lots_total and lots_unknown_release > 0:
        common_blockers.append("material_lot_release_unknown")

    benchmark_blockers = list(common_blockers)
    if qualified_machine_recipe_rates == 0:
        benchmark_blockers.append("no_explicit_qualified_machine_recipe_rate")
    if material_approved == 0:
        benchmark_blockers.append("no_explicit_approved_material_qualification")
    if lots_total and lots_released == 0:
        benchmark_blockers.append("no_released_material_lots")
    if cleaning_groups == 0 or cleaning_rules == 0:
        benchmark_blockers.append("canonical_cleaning_taxonomy_incomplete")

    production_blockers = list(common_blockers)
    if qualified_machine_recipe_rates_operational == 0:
        production_blockers.append("no_operational_machine_recipe_rate")
    if material_approved_operational == 0:
        production_blockers.append("no_operational_material_qualification")
    if lots_total and lots_released_operational == 0:
        production_blockers.append("no_operational_released_material_lots")
    if cleaning_groups == 0 or cleaning_rules_operational == 0:
        production_blockers.append("no_operational_cleaning_taxonomy")

    report["readiness"] = {
        "safe_for_shadow": (
            orders_with_recipe_version == orders_total
            and machine_profiles >= active_machines
            and report["domain_v2_enforcement_mode"] == "LEGACY"
        ),
        "safe_for_benchmark_hard": len(benchmark_blockers) == 0,
        "safe_for_production_hard": len(production_blockers) == 0,
        "benchmark_hard_blockers": benchmark_blockers,
        "production_hard_blockers": production_blockers,
        "note": (
            "SIMULATED provenance may satisfy deterministic industrial benchmark completeness, "
            "but never counts as production authority. This tool does not change enforcement mode."
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
    return 0 if report["readiness"]["safe_for_benchmark_hard"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
