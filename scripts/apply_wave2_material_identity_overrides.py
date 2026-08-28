"""Apply exact-grade material identity/classification overrides for Wave 2.

This tool exists because a legacy grade may lack an official catalog match while the
benchmark still needs an explicit polymer family. It never renames material_grade,
never creates an alias, and never creates medical APPROVED qualification.

Allowed authority is PLANT_MASTER, ENGINEERING or deliberately SIMULATED. Manufacturer
official identity for a currently verified exact grade belongs in official_material_catalog.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATABASE_CONFIG


ALLOWED_SOURCE_TYPES = {"PLANT_MASTER", "ENGINEERING", "SIMULATED"}
ALLOWED_POLYMER_FAMILIES = {
    "LDPE", "LLDPE", "HDPE", "PE", "PP", "PA", "PA6", "PA66", "EVOH", "TIE",
    "ETHYLENE_PLASTOMER", "ADDITIVE", "OTHER"
}


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )


def _load(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate(config: dict[str, Any]) -> None:
    source = config.get("source") or {}
    if source.get("source_type") not in ALLOWED_SOURCE_TYPES:
        raise ValueError("Material identity override source_type must be PLANT_MASTER, ENGINEERING or SIMULATED.")
    if not source.get("source_id") or not source.get("title"):
        raise ValueError("source_id and title are required")
    for item in config.get("materials", []):
        if not item.get("apply"):
            continue
        if not item.get("material_grade"):
            raise ValueError("Applied material identity override requires exact material_grade")
        family = str(item.get("polymer_family") or "").upper()
        if family not in ALLOWED_POLYMER_FAMILIES:
            raise ValueError(f"Unsupported polymer_family: {family}")
        if not item.get("reason"):
            raise ValueError("Applied material identity override requires reason")
        if item.get("rename_to") or item.get("alias_to"):
            raise ValueError("Wave 2 material identity override never renames or aliases material grades")


def _seed_source(cur, source: dict[str, Any]) -> None:
    cur.execute(
        """
        INSERT INTO provenance_sources
            (source_id, source_type, organization, title, url_or_reference,
             revision, confidence, regulatory_claim, metadata)
        VALUES (%s,%s,%s,%s,%s,%s,%s,FALSE,%s)
        ON CONFLICT (source_id) DO NOTHING
        """,
        (
            source["source_id"], source["source_type"], source.get("organization"),
            source["title"], source.get("url_or_reference"), source.get("revision"),
            source.get("confidence"), psycopg2.extras.Json(source.get("metadata") or {}),
        ),
    )


def apply_overrides(conn, config: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    _validate(config)
    source = config["source"]
    summary: dict[str, Any] = {
        "source_id": source["source_id"],
        "source_type": source["source_type"],
        "matched": 0,
        "updated": 0,
        "missing_exact_grades": [],
        "applied_grades": [],
        "medical_qualifications_created": 0,
        "renames_created": 0,
    }
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        _seed_source(cur, source)
        for item in config.get("materials", []):
            if not item.get("apply"):
                continue
            grade = item["material_grade"]
            cur.execute("SELECT material_grade FROM raw_materials WHERE material_grade=%s", (grade,))
            if not cur.fetchone():
                summary["missing_exact_grades"].append(grade)
                continue
            summary["matched"] += 1
            cur.execute(
                """
                UPDATE raw_materials
                SET polymer_family=%s,
                    manufacturer=COALESCE(%s, manufacturer),
                    commercial_grade=COALESCE(%s, commercial_grade),
                    melt_index_test_condition=COALESCE(%s, melt_index_test_condition),
                    updated_at=NOW()
                WHERE material_grade=%s
                """,
                (
                    str(item["polymer_family"]).upper(), item.get("manufacturer"),
                    item.get("commercial_grade"), item.get("melt_index_test_condition"), grade,
                ),
            )
            summary["updated"] += cur.rowcount
            summary["applied_grades"].append(grade)

            cur.execute(
                """
                INSERT INTO entity_source_links
                    (entity_type, entity_key, field_name, source_id, source_role, notes)
                VALUES ('raw_materials', %s, 'polymer_family', %s, 'PRIMARY', %s)
                ON CONFLICT DO NOTHING
                """,
                (grade, source["source_id"], item["reason"]),
            )

    if dry_run:
        conn.rollback()
        summary["transaction"] = "ROLLED_BACK_DRY_RUN"
    else:
        conn.commit()
        summary["transaction"] = "COMMITTED"
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = _load(args.config)
    conn = _connect()
    try:
        summary = apply_overrides(conn, config, dry_run=args.dry_run)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if summary["missing_exact_grades"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
