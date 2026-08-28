"""Populate Wave 2 medical blown-film master data without changing solver behavior.

Safety principles:
- manufacturer evidence is not plant approval;
- material matching uses exact aliases only (case-insensitive + trimmed), never fuzzy supplier logic;
- legacy recipe/machine values remain unverified unless an explicit override says otherwise;
- Exact 5101 style explicit manufacturer exclusion may create a fail-safe EXCLUDED_MEDICAL qualification;
- domain_v2_enforcement_mode is forced to LEGACY by this Wave 2 population step.

Run after db/migrations/20260828_wave2_domain_schema.sql has been applied.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import DATABASE_CONFIG


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "wave2" / "official_material_catalog.json"

REQUIRED_TABLES = {
    "provenance_sources",
    "material_application_evidence",
    "material_qualifications",
    "recipe_versions",
    "recipe_layers",
    "machine_capability_profiles",
    "machine_recipe_capabilities",
}


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _identity(value: str | None) -> str:
    """Normalize only representation, not semantic identity."""
    return " ".join(str(value or "").strip().split()).casefold()


def _validate_catalog(catalog: dict[str, Any]) -> None:
    if catalog.get("policy", {}).get("identity_match") != "EXACT_ALIAS_ONLY":
        raise ValueError("Wave 2 catalog must use EXACT_ALIAS_ONLY identity matching.")

    seen: dict[str, str] = {}
    for material in catalog.get("materials", []):
        canonical = material["canonical_grade"]
        aliases = material.get("exact_aliases") or []
        if canonical not in aliases:
            raise ValueError(f"{canonical}: canonical grade must be one of exact_aliases")
        for alias in aliases:
            key = _identity(alias)
            if key in seen and seen[key] != canonical:
                raise ValueError(
                    f"Exact alias {alias!r} maps to both {seen[key]!r} and {canonical!r}"
                )
            seen[key] = canonical

    for watch in catalog.get("legacy_identity_watchlist", []):
        if watch.get("replacement") is not None:
            raise ValueError("Legacy watchlist must not silently define replacement aliases.")


def _assert_schema(cur) -> None:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema='public'
        """
    )
    present = {row[0] for row in cur.fetchall()}
    missing = sorted(REQUIRED_TABLES - present)
    if missing:
        raise RuntimeError(
            "Wave 2 schema is not installed. Missing tables: " + ", ".join(missing)
        )


def _seed_catalog_sources(cur, catalog: dict[str, Any], summary: dict[str, Any]) -> None:
    for source in catalog.get("sources", []):
        cur.execute(
            """
            INSERT INTO provenance_sources
                (source_id, source_type, organization, title, url_or_reference,
                 revision, document_date, confidence, regulatory_claim, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (source_id) DO NOTHING
            """,
            (
                source["source_id"],
                source["source_type"],
                source.get("organization"),
                source["title"],
                source.get("url_or_reference"),
                source.get("revision"),
                source.get("document_date"),
                source.get("confidence"),
                bool(source.get("regulatory_claim", False)),
                psycopg2.extras.Json(source.get("metadata") or {}),
            ),
        )
        summary["catalog_sources_inserted"] += cur.rowcount


def _build_alias_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for material in catalog.get("materials", []):
        for alias in material.get("exact_aliases", []):
            result[_identity(alias)] = material
    return result


def _fetch_materials(cur) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT material_grade, material_name, supplier, material_category,
               melt_index, density, manufacturer, commercial_grade,
               polymer_family, melt_index_test_condition
        FROM raw_materials
        ORDER BY material_grade
        """
    )
    columns = [desc[0] for desc in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def _insert_missing_official_materials(
    cur,
    catalog: dict[str, Any],
    existing_identity: set[str],
    summary: dict[str, Any],
) -> None:
    for material in catalog.get("materials", []):
        if any(_identity(alias) in existing_identity for alias in material.get("exact_aliases", [])):
            continue
        cur.execute(
            """
            INSERT INTO raw_materials
                (material_grade, material_name, supplier, material_category,
                 melt_index, density, is_special, manufacturer, commercial_grade,
                 polymer_family, melt_index_test_condition)
            VALUES (%s,%s,NULL,NULL,%s,%s,FALSE,%s,%s,%s,%s)
            ON CONFLICT (material_grade) DO NOTHING
            """,
            (
                material["canonical_grade"],
                material["canonical_grade"],
                material.get("melt_index"),
                material.get("density"),
                material.get("manufacturer"),
                material.get("commercial_grade"),
                material.get("polymer_family"),
                material.get("melt_index_test_condition"),
            ),
        )
        summary["official_material_rows_inserted"] += cur.rowcount


def _populate_official_material_evidence(
    cur,
    catalog: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    alias_map = _build_alias_map(catalog)
    matched_canonicals: dict[str, list[str]] = defaultdict(list)

    for row in _fetch_materials(cur):
        material = alias_map.get(_identity(row["material_grade"]))
        if material is None:
            continue

        grade = row["material_grade"]
        matched_canonicals[material["canonical_grade"]].append(grade)
        summary["official_material_matches"] += 1

        # Preserve plant-owned values. Official catalog fills only null/blank identity/property fields.
        cur.execute(
            """
            UPDATE raw_materials
            SET manufacturer = COALESCE(NULLIF(manufacturer, ''), %s),
                commercial_grade = COALESCE(NULLIF(commercial_grade, ''), %s),
                polymer_family = COALESCE(NULLIF(polymer_family, ''), %s),
                melt_index_test_condition = COALESCE(NULLIF(melt_index_test_condition, ''), %s),
                melt_index = COALESCE(melt_index, %s),
                density = COALESCE(density, %s),
                updated_at = NOW()
            WHERE material_grade = %s
            """,
            (
                material.get("manufacturer"),
                material.get("commercial_grade"),
                material.get("polymer_family"),
                material.get("melt_index_test_condition"),
                material.get("melt_index"),
                material.get("density"),
                grade,
            ),
        )

        cur.execute(
            """
            INSERT INTO material_application_evidence
                (material_grade, evidence_type, application_scope, evidence_status,
                 source_id, notes)
            VALUES (%s,'MANUFACTURER_APPLICATION',%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
            """,
            (
                grade,
                material.get("application_scope"),
                material["evidence_status"],
                material["source_id"],
                material.get("manufacturer_limitation"),
            ),
        )
        summary["manufacturer_evidence_inserted"] += cur.rowcount

        # A manufacturer healthcare statement NEVER creates plant APPROVED.
        # An explicit manufacturer exclusion is allowed to create a global hard-negative qualification.
        if material.get("medical_qualification_action") == "AUTO_EXCLUDE_MEDICAL":
            cur.execute(
                """
                INSERT INTO material_qualifications
                    (material_grade, qualification_scope_type, qualification_status,
                     source_id, reason)
                SELECT %s, 'GLOBAL', 'EXCLUDED_MEDICAL', %s,
                       'Manufacturer source explicitly excludes medical applications.'
                WHERE NOT EXISTS (
                    SELECT 1 FROM material_qualifications
                    WHERE material_grade=%s
                      AND qualification_scope_type='GLOBAL'
                      AND qualification_status='EXCLUDED_MEDICAL'
                      AND source_id=%s
                      AND valid_to IS NULL
                )
                """,
                (grade, material["source_id"], grade, material["source_id"]),
            )
            summary["explicit_medical_exclusions_inserted"] += cur.rowcount

    summary["matched_catalog_grades"] = {
        key: sorted(values) for key, values in sorted(matched_canonicals.items())
    }


def _watch_legacy_identities(cur, catalog: dict[str, Any], summary: dict[str, Any]) -> None:
    watch_map: dict[str, dict[str, Any]] = {}
    for watch in catalog.get("legacy_identity_watchlist", []):
        for alias in watch.get("exact_aliases", []):
            watch_map[_identity(alias)] = watch

    hits = []
    for row in _fetch_materials(cur):
        watch = watch_map.get(_identity(row["material_grade"]))
        if not watch:
            continue
        hits.append({
            "material_grade": row["material_grade"],
            "action": watch["action"],
            "reason": watch.get("reason"),
        })
    summary["legacy_identity_watchlist_hits"] = hits


def _bind_unambiguous_recipe_versions(cur, summary: dict[str, Any]) -> None:
    # Binding is traceability only. The migration-created version remains MIGRATED_UNVERIFIED
    # and does not become solver-authoritative in LEGACY mode.
    cur.execute(
        """
        WITH one_version AS (
            SELECT product_type, MIN(recipe_version_id) AS recipe_version_id
            FROM recipe_versions
            WHERE status <> 'RETIRED'
            GROUP BY product_type
            HAVING COUNT(*) = 1
        )
        UPDATE production_orders o
        SET recipe_version_id = v.recipe_version_id,
            updated_at = NOW()
        FROM one_version v
        WHERE o.recipe_version_id IS NULL
          AND o.product_type = v.product_type
        """
    )
    summary["orders_bound_to_unambiguous_recipe_version"] += cur.rowcount


def _seed_unknown_machine_recipe_shadow(cur, summary: dict[str, Any]) -> None:
    """Optional structural bootstrap only; never marks a pair QUALIFIED.

    This makes legacy-rate comparison possible in Wave 3 SHADOW analysis while keeping
    eligibility UNKNOWN and provenance SIMULATED. It intentionally does not distinguish
    recipe rates and must never be accepted as an industrial rate master.
    """
    cur.execute(
        """
        INSERT INTO machine_recipe_capabilities
            (machine_id, recipe_version_id, eligibility_status, standard_rate_kg_h,
             quality_status, confidence, source_id)
        SELECT m.machine_id, rv.recipe_version_id, 'UNKNOWN', m.hourly_output_kg,
               'UNKNOWN', 0.10, 'SRC-SIM-LEGACY'
        FROM machines m
        CROSS JOIN recipe_versions rv
        WHERE m.status='ACTIVE'
          AND rv.status <> 'RETIRED'
          AND NOT EXISTS (
              SELECT 1
              FROM machine_recipe_capabilities x
              WHERE x.machine_id=m.machine_id
                AND x.recipe_version_id=rv.recipe_version_id
          )
        """
    )
    summary["legacy_shadow_machine_recipe_rows_inserted"] += cur.rowcount


def _apply_overrides(cur, overrides: dict[str, Any], summary: dict[str, Any]) -> None:
    """Apply explicit plant/engineering/simulated overrides supplied by the operator.

    The override file is intentionally separate from official manufacturer catalog data.
    It is the only supported Wave 2 path for promoting plant-specific route/rate/release facts.
    """
    source = overrides.get("source")
    if source:
        if source.get("source_type") not in {"PLANT_MASTER", "PLANT_SOP", "ENGINEERING", "LEARNED", "SIMULATED"}:
            raise ValueError("Override source_type must be plant/engineering/learned/simulated, not generic OEM evidence.")
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
        summary["override_sources_inserted"] += cur.rowcount

    default_source_id = source.get("source_id") if source else None

    for item in overrides.get("machines", []):
        if not item.get("apply", False):
            continue
        cur.execute(
            """
            INSERT INTO machine_capability_profiles
                (machine_id, process_route, medical_release_status,
                 cleanroom_standard, cleanroom_iso_class, qualification_status,
                 qualification_valid_until, source_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (machine_id) DO UPDATE SET
                process_route=EXCLUDED.process_route,
                medical_release_status=EXCLUDED.medical_release_status,
                cleanroom_standard=EXCLUDED.cleanroom_standard,
                cleanroom_iso_class=EXCLUDED.cleanroom_iso_class,
                qualification_status=EXCLUDED.qualification_status,
                qualification_valid_until=EXCLUDED.qualification_valid_until,
                source_id=EXCLUDED.source_id,
                updated_at=NOW()
            """,
            (
                item["machine_id"], item["process_route"], item.get("medical_release_status", "UNKNOWN"),
                item.get("cleanroom_standard"), item.get("cleanroom_iso_class"),
                item.get("qualification_status", "UNKNOWN"), item.get("qualification_valid_until"),
                item.get("source_id") or default_source_id,
            ),
        )
        summary["machine_profile_overrides_applied"] += 1

    for item in overrides.get("recipe_versions", []):
        if not item.get("apply", False):
            continue
        cur.execute(
            """
            UPDATE recipe_versions
            SET process_route=%s,
                status=%s,
                cleaning_validation_group_id=%s,
                source_id=%s,
                approved_by=%s,
                approved_at=%s,
                change_reason=%s,
                updated_at=NOW()
            WHERE recipe_version_id=%s
            """,
            (
                item["process_route"], item["status"], item.get("cleaning_validation_group_id"),
                item.get("source_id") or default_source_id, item.get("approved_by"),
                item.get("approved_at"), item.get("change_reason"), item["recipe_version_id"],
            ),
        )
        summary["recipe_version_overrides_applied"] += cur.rowcount

    for item in overrides.get("material_qualifications", []):
        if not item.get("apply", False):
            continue
        cur.execute(
            """
            INSERT INTO material_qualifications
                (material_grade, qualification_scope_type, product_type,
                 recipe_version_id, process_route, qualification_status,
                 condition_expression, source_id, approved_by, approved_at,
                 valid_from, valid_to, reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                item["material_grade"], item.get("qualification_scope_type", "GLOBAL"),
                item.get("product_type"), item.get("recipe_version_id"), item.get("process_route"),
                item["qualification_status"], psycopg2.extras.Json(item.get("condition_expression")) if item.get("condition_expression") is not None else None,
                item.get("source_id") or default_source_id, item.get("approved_by"), item.get("approved_at"),
                item.get("valid_from"), item.get("valid_to"), item.get("reason"),
            ),
        )
        summary["material_qualification_overrides_inserted"] += cur.rowcount

    for item in overrides.get("machine_recipe_capabilities", []):
        if not item.get("apply", False):
            continue
        cur.execute(
            """
            INSERT INTO machine_recipe_capabilities
                (machine_id, recipe_version_id, eligibility_status,
                 standard_rate_kg_h, min_rate_kg_h, max_rate_kg_h,
                 startup_rate_factor, quality_status, validation_protocol_id,
                 confidence, source_id, valid_from, valid_to)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (machine_id, recipe_version_id) DO UPDATE SET
                eligibility_status=EXCLUDED.eligibility_status,
                standard_rate_kg_h=EXCLUDED.standard_rate_kg_h,
                min_rate_kg_h=EXCLUDED.min_rate_kg_h,
                max_rate_kg_h=EXCLUDED.max_rate_kg_h,
                startup_rate_factor=EXCLUDED.startup_rate_factor,
                quality_status=EXCLUDED.quality_status,
                validation_protocol_id=EXCLUDED.validation_protocol_id,
                confidence=EXCLUDED.confidence,
                source_id=EXCLUDED.source_id,
                valid_from=EXCLUDED.valid_from,
                valid_to=EXCLUDED.valid_to,
                updated_at=NOW()
            """,
            (
                item["machine_id"], item["recipe_version_id"], item["eligibility_status"],
                item.get("standard_rate_kg_h"), item.get("min_rate_kg_h"), item.get("max_rate_kg_h"),
                item.get("startup_rate_factor"), item.get("quality_status", "UNKNOWN"),
                item.get("validation_protocol_id"), item.get("confidence"),
                item.get("source_id") or default_source_id, item.get("valid_from"), item.get("valid_to"),
            ),
        )
        summary["machine_recipe_overrides_applied"] += 1

    for item in overrides.get("inventory_release", []):
        if not item.get("apply", False):
            continue
        cur.execute(
            """
            UPDATE material_inventory
            SET release_status=%s,
                use_before_date=COALESCE(%s, use_before_date),
                source_id=COALESCE(%s, source_id),
                updated_at=NOW()
            WHERE id=%s
            """,
            (
                item["release_status"], item.get("use_before_date"),
                item.get("source_id") or default_source_id, item["inventory_id"],
            ),
        )
        summary["inventory_release_overrides_applied"] += cur.rowcount


def _collect_coverage(cur, summary: dict[str, Any]) -> None:
    queries = {
        "active_machine_count": "SELECT COUNT(*) FROM machines WHERE status='ACTIVE'",
        "known_machine_route_count": "SELECT COUNT(*) FROM machine_capability_profiles WHERE process_route <> 'UNKNOWN'",
        "released_recipe_count": "SELECT COUNT(*) FROM recipe_versions WHERE status='RELEASED' AND valid_to IS NULL",
        "migrated_unverified_recipe_count": "SELECT COUNT(*) FROM recipe_versions WHERE status='MIGRATED_UNVERIFIED'",
        "qualified_machine_recipe_rate_count": "SELECT COUNT(*) FROM machine_recipe_capabilities WHERE eligibility_status='QUALIFIED' AND standard_rate_kg_h > 0",
        "plant_approved_material_qualification_count": "SELECT COUNT(*) FROM material_qualifications WHERE qualification_status='APPROVED' AND valid_to IS NULL",
        "unknown_inventory_release_count": "SELECT COUNT(*) FROM material_inventory WHERE release_status='UNKNOWN'",
    }
    for key, query in queries.items():
        cur.execute(query)
        summary[key] = int(cur.fetchone()[0])

    cur.execute("SELECT domain_v2_enforcement_mode FROM schedule_settings WHERE id=TRUE")
    row = cur.fetchone()
    summary["domain_v2_enforcement_mode"] = row[0] if row else None


def _new_summary() -> dict[str, Any]:
    return {
        "catalog_sources_inserted": 0,
        "official_material_rows_inserted": 0,
        "official_material_matches": 0,
        "manufacturer_evidence_inserted": 0,
        "explicit_medical_exclusions_inserted": 0,
        "orders_bound_to_unambiguous_recipe_version": 0,
        "legacy_shadow_machine_recipe_rows_inserted": 0,
        "override_sources_inserted": 0,
        "machine_profile_overrides_applied": 0,
        "recipe_version_overrides_applied": 0,
        "material_qualification_overrides_inserted": 0,
        "machine_recipe_overrides_applied": 0,
        "inventory_release_overrides_applied": 0,
        "legacy_identity_watchlist_hits": [],
        "matched_catalog_grades": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--overrides", help="Explicit plant/engineering/simulated override JSON.")
    parser.add_argument(
        "--insert-missing-official-materials",
        action="store_true",
        help="Insert catalog grades absent from legacy raw_materials. Default is match-only.",
    )
    parser.add_argument(
        "--bootstrap-legacy-rate-shadow",
        action="store_true",
        help="Create UNKNOWN machine-recipe rows using legacy machine hourly_output_kg for SHADOW comparison only.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute all SQL and print summary, then rollback.",
    )
    args = parser.parse_args()

    catalog = _load_json(args.catalog)
    _validate_catalog(catalog)
    overrides = _load_json(args.overrides) if args.overrides else None
    summary = _new_summary()

    conn = _connect()
    try:
        with conn.cursor() as cur:
            _assert_schema(cur)
            _seed_catalog_sources(cur, catalog, summary)

            existing = _fetch_materials(cur)
            existing_identity = {_identity(row["material_grade"]) for row in existing}
            if args.insert_missing_official_materials:
                _insert_missing_official_materials(cur, catalog, existing_identity, summary)

            _populate_official_material_evidence(cur, catalog, summary)
            _watch_legacy_identities(cur, catalog, summary)
            _bind_unambiguous_recipe_versions(cur, summary)

            if args.bootstrap_legacy_rate_shadow:
                _seed_unknown_machine_recipe_shadow(cur, summary)

            if overrides:
                _apply_overrides(cur, overrides, summary)

            # Wave 2 population is never allowed to flip enforcement implicitly.
            cur.execute(
                "UPDATE schedule_settings SET domain_v2_enforcement_mode='LEGACY' WHERE id=TRUE"
            )
            _collect_coverage(cur, summary)

        if args.dry_run:
            conn.rollback()
            summary["transaction"] = "ROLLED_BACK_DRY_RUN"
        else:
            conn.commit()
            summary["transaction"] = "COMMITTED"

        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        if summary.get("domain_v2_enforcement_mode") != "LEGACY":
            return 3
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
