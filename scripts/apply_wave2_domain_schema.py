"""Apply and verify the Wave 2 additive medical blown-film domain schema.

This migration is intentionally isolated from the solver. It creates additive V2
master-data structures and keeps schedule_settings.domain_v2_enforcement_mode at
LEGACY so current scheduling behavior does not change.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATABASE_CONFIG


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION_PATH = os.path.join(
    ROOT,
    "db",
    "migrations",
    "20260828_wave2_domain_schema.sql",
)

REQUIRED_TABLES = {
    "provenance_sources",
    "entity_source_links",
    "material_application_evidence",
    "material_qualifications",
    "cleaning_validation_groups",
    "recipe_versions",
    "recipe_layers",
    "machine_capability_profiles",
    "machine_extruders",
    "machine_material_capabilities",
    "machine_feature_capabilities",
    "machine_recipe_capabilities",
    "cleaning_transition_rules",
    "material_lot_reservations",
    "order_material_requirements",
}

REQUIRED_VIEWS = {
    "v_recipe_version_validation",
    "v_material_lot_available",
}


def _connect():
    conn = psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )
    # The SQL file contains its own BEGIN/COMMIT so it is also safe to run in psql.
    # Autocommit here prevents a nested implicit psycopg transaction around that file.
    conn.autocommit = True
    return conn


def apply_migration(conn) -> None:
    with open(MIGRATION_PATH, "r", encoding="utf-8") as handle:
        sql = handle.read()
    with conn.cursor() as cur:
        cur.execute(sql)


def verify_schema(conn) -> dict:
    result = {
        "missing_tables": [],
        "missing_views": [],
        "domain_v2_enforcement_mode": None,
        "recipe_versions": 0,
        "migrated_unverified_recipes": 0,
        "released_recipes": 0,
        "machine_profiles": 0,
        "machine_recipe_capabilities": 0,
        "material_qualifications": 0,
        "provenance_sources": 0,
    }
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
            """
        )
        present_tables = {row["table_name"] for row in cur.fetchall()}
        result["missing_tables"] = sorted(REQUIRED_TABLES - present_tables)

        cur.execute(
            """
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema='public'
            """
        )
        present_views = {row["table_name"] for row in cur.fetchall()}
        result["missing_views"] = sorted(REQUIRED_VIEWS - present_views)

        cur.execute(
            "SELECT domain_v2_enforcement_mode FROM schedule_settings WHERE id=TRUE"
        )
        row = cur.fetchone()
        result["domain_v2_enforcement_mode"] = (
            row["domain_v2_enforcement_mode"] if row else None
        )

        for key, query in {
            "recipe_versions": "SELECT COUNT(*) AS n FROM recipe_versions",
            "migrated_unverified_recipes": (
                "SELECT COUNT(*) AS n FROM recipe_versions "
                "WHERE status='MIGRATED_UNVERIFIED'"
            ),
            "released_recipes": (
                "SELECT COUNT(*) AS n FROM recipe_versions WHERE status='RELEASED'"
            ),
            "machine_profiles": "SELECT COUNT(*) AS n FROM machine_capability_profiles",
            "machine_recipe_capabilities": (
                "SELECT COUNT(*) AS n FROM machine_recipe_capabilities"
            ),
            "material_qualifications": "SELECT COUNT(*) AS n FROM material_qualifications",
            "provenance_sources": "SELECT COUNT(*) AS n FROM provenance_sources",
        }.items():
            cur.execute(query)
            result[key] = int(cur.fetchone()["n"])

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Do not execute migration SQL; only verify current database state.",
    )
    args = parser.parse_args()

    conn = _connect()
    try:
        if not args.verify_only:
            apply_migration(conn)
            print(f"Applied: {MIGRATION_PATH}")

        result = verify_schema(conn)
        print("Wave 2 schema verification:")
        for key, value in result.items():
            print(f"  {key}: {value}")

        if result["missing_tables"] or result["missing_views"]:
            return 2
        if result["domain_v2_enforcement_mode"] != "LEGACY":
            print(
                "ERROR: migration must leave domain_v2_enforcement_mode=LEGACY "
                "until Wave 3 shadow validation is explicitly enabled."
            )
            return 3
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
