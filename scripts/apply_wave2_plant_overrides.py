"""Apply explicit Wave 2 plant/engineering/simulated master-data overrides.

This tool is intentionally separate from official manufacturer evidence seeding.
Generic OEM/material sources may describe possible capability, but they are not accepted
as authority for a specific LINE-xx machine, plant release, cleaning SOP or production rate.

All rows are opt-in with `apply=true`. The script never changes
`schedule_settings.domain_v2_enforcement_mode`.
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


ALLOWED_SOURCE_TYPES = {"PLANT_MASTER", "PLANT_SOP", "ENGINEERING", "LEARNED", "SIMULATED"}
ALLOWED_PROCESS_ROUTES = {"UPWARD_AIR", "DOWNWARD_WATER_QUENCH", "UNKNOWN"}
ALLOWED_RECIPE_STATUS = {"DRAFT", "MIGRATED_UNVERIFIED", "VALIDATED", "RELEASED", "RETIRED"}
ALLOWED_MATERIAL_QUALIFICATION = {"APPROVED", "CONDITIONAL", "TECHNICAL_TRIAL_ONLY", "EXCLUDED_MEDICAL", "UNKNOWN"}
ALLOWED_MACHINE_RECIPE_STATUS = {"QUALIFIED", "CONDITIONAL", "TECHNICAL_TRIAL_ONLY", "NOT_QUALIFIED", "UNKNOWN"}
ALLOWED_MACHINE_MATERIAL_STATUS = {"QUALIFIED", "CONDITIONAL", "TECHNICAL_ONLY", "NOT_SUPPORTED", "UNKNOWN"}
ALLOWED_RELEASE_STATUS = {"RELEASED", "QC_HOLD", "QUARANTINE", "REJECTED", "TECHNICAL_TRIAL_ONLY", "EXPIRED", "UNKNOWN"}
ALLOWED_CLEANING_ENFORCEMENT = {"HARD", "PUBLISH_BLOCKER", "SHADOW"}


def _load(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _connect():
    return psycopg2.connect(
        host=DATABASE_CONFIG["host"],
        port=DATABASE_CONFIG["port"],
        dbname=DATABASE_CONFIG["database"],
        user=DATABASE_CONFIG["username"],
        password=DATABASE_CONFIG["password"],
    )


def _validate(config: dict[str, Any]) -> None:
    source = config.get("source") or {}
    if source.get("source_type") not in ALLOWED_SOURCE_TYPES:
        raise ValueError(
            "Override source_type must be PLANT_MASTER/PLANT_SOP/ENGINEERING/LEARNED/SIMULATED. "
            "Generic OEM or material manufacturer evidence cannot authorize plant-specific values."
        )
    if not source.get("source_id") or not source.get("title"):
        raise ValueError("Override source_id and title are required.")

    for item in config.get("machines", []):
        if item.get("apply") and item.get("process_route") not in ALLOWED_PROCESS_ROUTES:
            raise ValueError(f"Invalid process route: {item.get('process_route')}")

    for item in config.get("recipe_versions", []):
        if not item.get("apply"):
            continue
        if item.get("process_route") not in ALLOWED_PROCESS_ROUTES:
            raise ValueError(f"Invalid recipe process route: {item.get('process_route')}")
        if item.get("status") not in ALLOWED_RECIPE_STATUS:
            raise ValueError(f"Invalid recipe status: {item.get('status')}")
        if item.get("status") == "RELEASED":
            if item.get("process_route") == "UNKNOWN":
                raise ValueError("A RELEASED recipe cannot keep process_route=UNKNOWN.")
            if not item.get("approved_by") or not item.get("approved_at"):
                raise ValueError("A RELEASED recipe requires approved_by and approved_at.")

    for item in config.get("material_qualifications", []):
        if item.get("apply") and item.get("qualification_status") not in ALLOWED_MATERIAL_QUALIFICATION:
            raise ValueError(f"Invalid material qualification: {item.get('qualification_status')}")
        if item.get("apply") and item.get("qualification_status") in {"APPROVED", "CONDITIONAL"}:
            if not item.get("approved_by") or not item.get("approved_at"):
                raise ValueError("APPROVED/CONDITIONAL material qualification requires approver and timestamp.")

    for item in config.get("machine_recipe_capabilities", []):
        if not item.get("apply"):
            continue
        if item.get("eligibility_status") not in ALLOWED_MACHINE_RECIPE_STATUS:
            raise ValueError(f"Invalid machine-recipe status: {item.get('eligibility_status')}")
        if item.get("eligibility_status") == "QUALIFIED":
            rate = item.get("standard_rate_kg_h")
            if rate is None or float(rate) <= 0:
                raise ValueError("QUALIFIED machine-recipe capability requires positive standard_rate_kg_h.")

    for item in config.get("machine_material_capabilities", []):
        if item.get("apply") and item.get("capability_status") not in ALLOWED_MACHINE_MATERIAL_STATUS:
            raise ValueError(f"Invalid machine-material status: {item.get('capability_status')}")

    for item in config.get("inventory_release", []):
        if item.get("apply") and item.get("release_status") not in ALLOWED_RELEASE_STATUS:
            raise ValueError(f"Invalid lot release status: {item.get('release_status')}")

    for item in config.get("cleaning_transition_rules", []):
        if not item.get("apply"):
            continue
        if item.get("enforcement_mode") not in ALLOWED_CLEANING_ENFORCEMENT:
            raise ValueError(f"Invalid cleaning enforcement: {item.get('enforcement_mode')}")
        if item.get("change_time_mins") is None or int(item["change_time_mins"]) < 0:
            raise ValueError("Applied cleaning transition requires non-negative change_time_mins.")


def _seed_source(cur, source: dict[str, Any], summary: dict[str, int]) -> None:
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
    summary["sources"] += cur.rowcount


def _source_id(item: dict[str, Any], default: str) -> str:
    return item.get("source_id") or default


def _apply(cur, config: dict[str, Any]) -> dict[str, int]:
    summary = {
        "sources": 0,
        "machine_profiles": 0,
        "machine_material_capabilities": 0,
        "machine_feature_capabilities": 0,
        "cleaning_groups": 0,
        "cleaning_rules": 0,
        "recipe_versions": 0,
        "material_qualifications": 0,
        "machine_recipe_capabilities": 0,
        "inventory_release": 0,
    }
    source = config["source"]
    default_source = source["source_id"]
    _seed_source(cur, source, summary)

    for item in config.get("cleaning_validation_groups", []):
        if not item.get("apply"):
            continue
        cur.execute(
            """
            INSERT INTO cleaning_validation_groups
                (group_id, group_name, description, status, source_id)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (group_id) DO UPDATE SET
                group_name=EXCLUDED.group_name,
                description=EXCLUDED.description,
                status=EXCLUDED.status,
                source_id=EXCLUDED.source_id,
                updated_at=NOW()
            """,
            (item["group_id"], item["group_name"], item.get("description"), item.get("status", "ACTIVE"), _source_id(item, default_source)),
        )
        summary["cleaning_groups"] += 1

    for item in config.get("machines", []):
        if not item.get("apply"):
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
                item.get("cleanroom_standard"), item.get("cleanroom_iso_class"), item.get("qualification_status", "UNKNOWN"),
                item.get("qualification_valid_until"), _source_id(item, default_source),
            ),
        )
        summary["machine_profiles"] += 1

    for item in config.get("machine_material_capabilities", []):
        if not item.get("apply"):
            continue
        cur.execute(
            """
            INSERT INTO machine_material_capabilities
                (machine_id, extruder_position, polymer_family, capability_status, source_id, valid_from, valid_to)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (machine_id, COALESCE(extruder_position, 0), polymer_family)
            DO UPDATE SET
                capability_status=EXCLUDED.capability_status,
                source_id=EXCLUDED.source_id,
                valid_from=EXCLUDED.valid_from,
                valid_to=EXCLUDED.valid_to
            """,
            (
                item["machine_id"], item.get("extruder_position"), item["polymer_family"],
                item["capability_status"], _source_id(item, default_source), item.get("valid_from"), item.get("valid_to"),
            ),
        )
        summary["machine_material_capabilities"] += 1

    for item in config.get("machine_feature_capabilities", []):
        if not item.get("apply"):
            continue
        cur.execute(
            """
            INSERT INTO machine_feature_capabilities
                (machine_id, feature_code, enabled, value_number, value_text, source_id, valid_from, valid_to)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (machine_id, feature_code) DO UPDATE SET
                enabled=EXCLUDED.enabled,
                value_number=EXCLUDED.value_number,
                value_text=EXCLUDED.value_text,
                source_id=EXCLUDED.source_id,
                valid_from=EXCLUDED.valid_from,
                valid_to=EXCLUDED.valid_to,
                updated_at=NOW()
            """,
            (
                item["machine_id"], item["feature_code"], bool(item["enabled"]), item.get("value_number"),
                item.get("value_text"), _source_id(item, default_source), item.get("valid_from"), item.get("valid_to"),
            ),
        )
        summary["machine_feature_capabilities"] += 1

    for item in config.get("cleaning_transition_rules", []):
        if not item.get("apply"):
            continue
        cur.execute(
            """
            INSERT INTO cleaning_transition_rules
                (from_group_id, to_group_id, change_time_mins, scrap_weight_kg,
                 enforcement_mode, source_id, valid_from, valid_to)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (from_group_id, to_group_id) DO UPDATE SET
                change_time_mins=EXCLUDED.change_time_mins,
                scrap_weight_kg=EXCLUDED.scrap_weight_kg,
                enforcement_mode=EXCLUDED.enforcement_mode,
                source_id=EXCLUDED.source_id,
                valid_from=EXCLUDED.valid_from,
                valid_to=EXCLUDED.valid_to,
                updated_at=NOW()
            """,
            (
                item["from_group_id"], item["to_group_id"], int(item["change_time_mins"]),
                item.get("scrap_weight_kg"), item["enforcement_mode"], _source_id(item, default_source),
                item.get("valid_from"), item.get("valid_to"),
            ),
        )
        summary["cleaning_rules"] += 1

    for item in config.get("recipe_versions", []):
        if not item.get("apply"):
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
                _source_id(item, default_source), item.get("approved_by"), item.get("approved_at"),
                item.get("change_reason"), item["recipe_version_id"],
            ),
        )
        summary["recipe_versions"] += cur.rowcount

        if item["status"] == "RELEASED" and cur.rowcount:
            cur.execute(
                """
                SELECT layer_count, actual_layer_count, missing_ratio_count,
                       ratio_total, layer_count_ok, ratio_complete, ratio_sum_ok
                FROM v_recipe_version_validation
                WHERE recipe_version_id=%s
                """,
                (item["recipe_version_id"],),
            )
            validation = cur.fetchone()
            if not validation or not all(validation[-3:]):
                raise ValueError(
                    f"Cannot RELEASE recipe {item['recipe_version_id']}: layer/ratio validation failed: {validation}"
                )

    for item in config.get("material_qualifications", []):
        if not item.get("apply"):
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
                item["material_grade"], item.get("qualification_scope_type", "GLOBAL"), item.get("product_type"),
                item.get("recipe_version_id"), item.get("process_route"), item["qualification_status"],
                psycopg2.extras.Json(item.get("condition_expression")) if item.get("condition_expression") is not None else None,
                _source_id(item, default_source), item.get("approved_by"), item.get("approved_at"),
                item.get("valid_from"), item.get("valid_to"), item.get("reason"),
            ),
        )
        summary["material_qualifications"] += cur.rowcount

    for item in config.get("machine_recipe_capabilities", []):
        if not item.get("apply"):
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
                item["machine_id"], item["recipe_version_id"], item["eligibility_status"], item.get("standard_rate_kg_h"),
                item.get("min_rate_kg_h"), item.get("max_rate_kg_h"), item.get("startup_rate_factor"),
                item.get("quality_status", "UNKNOWN"), item.get("validation_protocol_id"), item.get("confidence"),
                _source_id(item, default_source), item.get("valid_from"), item.get("valid_to"),
            ),
        )
        summary["machine_recipe_capabilities"] += 1

    for item in config.get("inventory_release", []):
        if not item.get("apply"):
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
            (item["release_status"], item.get("use_before_date"), _source_id(item, default_source), item["inventory_id"]),
        )
        summary["inventory_release"] += cur.rowcount

    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Path to explicit Wave 2 override JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and execute, then rollback.")
    args = parser.parse_args()

    config = _load(args.config)
    _validate(config)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            summary = _apply(cur, config)
            cur.execute("SELECT domain_v2_enforcement_mode FROM schedule_settings WHERE id=TRUE")
            row = cur.fetchone()
            mode = row[0] if row else None

        if args.dry_run:
            conn.rollback()
            transaction = "ROLLED_BACK_DRY_RUN"
        else:
            conn.commit()
            transaction = "COMMITTED"

        print(json.dumps({"transaction": transaction, "enforcement_mode_unchanged": mode, **summary}, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
