"""Build a deterministic SIMULATED Wave 2 industrial benchmark plant profile.

The profile is generated from the runtime database so it preserves the existing plant's
machine IDs, physical envelopes, recipe layers/ratios and inventory IDs. Only missing V2
plant semantics are simulated. Generic OEM/material official sources remain evidence
bounds and are never copied into LINE-xx as plant facts.

Output is compatible with scripts/apply_wave2_plant_overrides.py and intentionally uses
source_type=SIMULATED. It may satisfy benchmark-hard completeness, never production-hard
readiness.
"""

from __future__ import annotations

import argparse
import json
import math
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
DEFAULT_POLICY = ROOT / "data" / "wave2" / "industrial_benchmark_policy.json"
DEFAULT_OUTPUT = ROOT / "output" / "wave2_industrial_benchmark_profile.json"


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


def _rows(cur, sql: str, params=None) -> list[dict[str, Any]]:
    cur.execute(sql, params or ())
    return [dict(row) for row in cur.fetchall()]


def _recipe_family(layer_count: int, polymer_families: list[str], policy: dict[str, Any]) -> dict[str, Any]:
    families = {str(x or "OTHER").upper() for x in polymer_families}
    primary = families - {"TIE", "ADDITIVE", "OTHER"}
    for rule in policy["recipe_family_rules"]:
        if rule.get("contains_any_polymer_family"):
            if families.intersection({x.upper() for x in rule["contains_any_polymer_family"]}):
                return rule
        if rule.get("all_primary_polymer_families_in"):
            allowed = {x.upper() for x in rule["all_primary_polymer_families_in"]}
            if primary and primary.issubset(allowed):
                return rule
        if rule.get("min_layer_count") is not None and layer_count >= int(rule["min_layer_count"]):
            return rule
        if rule.get("max_layer_count") is not None and layer_count <= int(rule["max_layer_count"]):
            return rule
    raise ValueError(f"No benchmark recipe family rule for layers={layer_count}, families={sorted(families)}")


def _cleanroom_mapping(level: str | None, policy: dict[str, Any]) -> tuple[str | None, int | None]:
    item = policy.get("cleanroom_compatibility", {}).get(level or "")
    if not item:
        return None, None
    return item.get("cleanroom_standard"), item.get("cleanroom_iso_class")


def _machine_ordinal(machine_id: str, fallback: int) -> int:
    digits = "".join(ch for ch in machine_id if ch.isdigit())
    return int(digits) if digits else fallback


def collect_profile(conn, policy: dict[str, Any]) -> dict[str, Any]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        machines = _rows(
            cur,
            """
            SELECT machine_id, name, cleanroom_level, layer_structure,
                   min_width, max_width, min_thickness, max_thickness,
                   hourly_output_kg, max_slitting_lanes, status
            FROM machines WHERE status='ACTIVE' ORDER BY machine_id
            """,
        )
        recipes = _rows(
            cur,
            """
            SELECT rv.recipe_version_id, rv.product_type, rv.revision, rv.layer_count,
                   rv.status, v.actual_layer_count, v.missing_ratio_count,
                   v.ratio_total, v.layer_count_ok, v.ratio_complete,
                   v.ratio_sum_ok, v.structurally_releasable
            FROM recipe_versions rv
            JOIN v_recipe_version_validation v ON v.recipe_version_id=rv.recipe_version_id
            WHERE rv.status <> 'RETIRED'
            ORDER BY rv.product_type, rv.revision
            """,
        )
        layers = _rows(
            cur,
            """
            SELECT rl.recipe_version_id, rl.layer_index, rl.material_grade,
                   rl.ratio_pct, COALESCE(r.polymer_family, 'OTHER') AS polymer_family
            FROM recipe_layers rl
            JOIN raw_materials r ON r.material_grade=rl.material_grade
            ORDER BY rl.recipe_version_id, rl.layer_index
            """,
        )
        explicit_exclusions = _rows(
            cur,
            """
            SELECT DISTINCT material_grade
            FROM material_application_evidence
            WHERE evidence_status='EXPLICITLY_EXCLUDED_MEDICAL'
            """,
        )
        lots = _rows(
            cur,
            """
            SELECT id, material_grade, lot_number, quantity_kg, status,
                   release_status, expected_arrival, use_before_date
            FROM material_inventory ORDER BY material_grade, id
            """,
        )
        active_orders = _rows(
            cur,
            """
            SELECT order_id, product_type, recipe_version_id, total_quantity_kg,
                   corona_req, cleanroom_req, status
            FROM production_orders
            WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
            ORDER BY order_id
            """,
        )

    layers_by_recipe: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in layers:
        layers_by_recipe[row["recipe_version_id"]].append(row)

    recipe_meta: dict[str, dict[str, Any]] = {}
    blocked_recipes = []
    for recipe in recipes:
        recipe_layers = layers_by_recipe.get(recipe["recipe_version_id"], [])
        families = [row["polymer_family"] for row in recipe_layers]
        family_rule = _recipe_family(int(recipe["layer_count"]), families, policy)
        releasable = bool(recipe.get("structurally_releasable"))
        recipe_meta[recipe["recipe_version_id"]] = {
            "recipe": recipe,
            "layers": recipe_layers,
            "families": sorted(set(families)),
            "family_rule": family_rule,
            "releasable": releasable,
        }
        if not releasable:
            blocked_recipes.append({
                "recipe_version_id": recipe["recipe_version_id"],
                "product_type": recipe["product_type"],
                "actual_layer_count": recipe.get("actual_layer_count"),
                "layer_count": recipe["layer_count"],
                "missing_ratio_count": recipe.get("missing_ratio_count"),
                "ratio_total": str(recipe.get("ratio_total")) if recipe.get("ratio_total") is not None else None,
                "reason": "Benchmark profile refuses to fabricate missing recipe ratios or layer structure.",
            })

    pp_recipes = [
        meta for meta in recipe_meta.values()
        if meta["releasable"] and meta["family_rule"]["process_route"] == "DOWNWARD_WATER_QUENCH"
    ]
    water_quench_machine_ids: set[str] = set()
    if pp_recipes and policy["route_policy"].get("allocate_water_quench_machines_only_if_pp_recipe_exists", True):
        required_layers = max(int(meta["recipe"]["layer_count"]) for meta in pp_recipes)
        candidates = [m for m in machines if int(m["layer_structure"]) >= required_layers]
        count = min(int(policy["route_policy"].get("max_water_quench_machine_count", 2)), len(candidates))
        water_quench_machine_ids = {m["machine_id"] for m in candidates[-count:]}

    source = policy["source"]
    approved_by = policy["material_qualification_policy"]["approved_by"]
    approved_at = policy["material_qualification_policy"]["approved_at"]
    exclusions = {row["material_grade"] for row in explicit_exclusions}

    machine_rows = []
    for index, machine in enumerate(machines, start=1):
        route = (
            policy["route_policy"]["pp_only_recipe_route"]
            if machine["machine_id"] in water_quench_machine_ids
            else policy["route_policy"]["default_route"]
        )
        clean_std, clean_iso = _cleanroom_mapping(machine.get("cleanroom_level"), policy)
        machine_rows.append({
            "apply": True,
            "machine_id": machine["machine_id"],
            "process_route": route,
            "medical_release_status": "RELEASED",
            "cleanroom_standard": clean_std,
            "cleanroom_iso_class": clean_iso,
            "qualification_status": "QUALIFIED",
            "qualification_valid_until": None,
            "benchmark_context": {
                "legacy_name": machine["name"],
                "legacy_layer_structure": machine["layer_structure"],
                "legacy_hourly_output_kg": machine["hourly_output_kg"],
                "simulation_class": "SIMULATED_WITH_OFFICIAL_ENVELOPE"
            }
        })

    recipe_rows = []
    for meta in recipe_meta.values():
        recipe = meta["recipe"]
        rule = meta["family_rule"]
        recipe_rows.append({
            "apply": bool(meta["releasable"]),
            "recipe_version_id": recipe["recipe_version_id"],
            "process_route": rule["process_route"] if meta["releasable"] else "UNKNOWN",
            "status": "RELEASED" if meta["releasable"] else recipe["status"],
            "cleaning_validation_group_id": rule["cleaning_group"] if meta["releasable"] else None,
            "approved_by": policy["recipe_release_policy"]["approved_by"] if meta["releasable"] else None,
            "approved_at": policy["recipe_release_policy"]["approved_at"] if meta["releasable"] else None,
            "change_reason": (
                f"SIMULATED benchmark release; family={rule['family']}; ratios preserved from runtime recipe master."
                if meta["releasable"] else
                "Not released: runtime recipe structure/ratio validation is incomplete."
            )
        })

    material_rows = []
    benchmark_materials = sorted({
        layer["material_grade"]
        for meta in recipe_meta.values() if meta["releasable"]
        for layer in meta["layers"]
    })
    for grade in benchmark_materials:
        excluded = grade in exclusions
        material_rows.append({
            "apply": True,
            "material_grade": grade,
            "qualification_scope_type": "GLOBAL",
            "product_type": None,
            "recipe_version_id": None,
            "process_route": None,
            "qualification_status": "EXCLUDED_MEDICAL" if excluded else "APPROVED",
            "condition_expression": None,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "valid_from": approved_at,
            "valid_to": None,
            "reason": (
                "Manufacturer evidence explicitly excludes medical use; benchmark fail-safe exclusion retained."
                if excluded else
                "SIMULATED plant qualification for deterministic benchmark only; not production authority."
            )
        })

    machine_routes = {row["machine_id"]: row["process_route"] for row in machine_rows}
    machine_recipe_rows = []
    machine_material_pairs: set[tuple[str, str]] = set()
    rate_policy = policy["rate_policy"]
    for machine in machines:
        for meta in recipe_meta.values():
            if not meta["releasable"]:
                continue
            recipe = meta["recipe"]
            rule = meta["family_rule"]
            if int(machine["layer_structure"]) < int(recipe["layer_count"]):
                continue
            if machine_routes[machine["machine_id"]] != rule["process_route"]:
                continue
            if any(layer["material_grade"] in exclusions for layer in meta["layers"]):
                continue
            standard = round(float(machine["hourly_output_kg"]) * float(rule["rate_factor"]), 3)
            machine_recipe_rows.append({
                "apply": True,
                "machine_id": machine["machine_id"],
                "recipe_version_id": recipe["recipe_version_id"],
                "eligibility_status": "QUALIFIED",
                "standard_rate_kg_h": standard,
                "min_rate_kg_h": round(standard * float(rate_policy["min_rate_factor"]), 3),
                "max_rate_kg_h": round(standard * float(rate_policy["max_rate_factor"]), 3),
                "startup_rate_factor": float(rate_policy["startup_rate_factor"]),
                "quality_status": rate_policy["quality_status"],
                "validation_protocol_id": rate_policy["validation_protocol_id"],
                "confidence": float(rate_policy["confidence"]),
                "valid_from": approved_at,
                "valid_to": None,
                "benchmark_family": rule["family"],
                "rate_derivation": f"legacy_machine_rate * {rule['rate_factor']}"
            })
            for family in meta["families"]:
                machine_material_pairs.add((machine["machine_id"], family))

    machine_material_rows = [
        {
            "apply": True,
            "machine_id": machine_id,
            "extruder_position": None,
            "polymer_family": family,
            "capability_status": "QUALIFIED",
            "valid_from": approved_at,
            "valid_to": None
        }
        for machine_id, family in sorted(machine_material_pairs)
    ]

    feature_rows = []
    total_machines = max(1, len(machines))
    corona_count = max(1, math.ceil(total_machines * float(policy["feature_policy"]["CORONA"]["enabled_ratio_target"])))
    gauge_count = max(1, math.ceil(total_machines * float(policy["feature_policy"]["AUTO_GAUGE"]["enabled_ratio_target"])))
    for index, machine in enumerate(machines, start=1):
        ordinal = _machine_ordinal(machine["machine_id"], index)
        feature_rows.extend([
            {
                "apply": True,
                "machine_id": machine["machine_id"],
                "feature_code": "CORONA",
                "enabled": index <= corona_count,
                "value_number": None,
                "value_text": "SIMULATED_BENCHMARK"
            },
            {
                "apply": True,
                "machine_id": machine["machine_id"],
                "feature_code": "IBC",
                "enabled": int(machine["layer_structure"]) >= int(policy["feature_policy"]["IBC"]["enabled_when_min_layers"]),
                "value_number": None,
                "value_text": "SIMULATED_BENCHMARK"
            },
            {
                "apply": True,
                "machine_id": machine["machine_id"],
                "feature_code": "AUTO_GAUGE",
                "enabled": index <= gauge_count,
                "value_number": None,
                "value_text": "SIMULATED_BENCHMARK"
            },
            {
                "apply": True,
                "machine_id": machine["machine_id"],
                "feature_code": "GRAVIMETRIC_DOSING",
                "enabled": int(machine["layer_structure"]) >= int(policy["feature_policy"]["GRAVIMETRIC_DOSING"]["enabled_when_min_layers"]),
                "value_number": None,
                "value_text": f"SIMULATED_BENCHMARK_MACHINE_{ordinal}"
            }
        ])

    cleaning_groups = [
        {
            "apply": True,
            "group_id": item["group_id"],
            "group_name": item["group_name"],
            "description": "SIMULATED benchmark taxonomy. Not an ISO/FDA-defined cleaning group.",
            "status": "ACTIVE"
        }
        for item in policy["cleaning_groups"]
    ]
    cleaning_rules = []
    for from_group, targets in policy["cleaning_transition_minutes"].items():
        for to_group, minutes in targets.items():
            cleaning_rules.append({
                "apply": True,
                "from_group_id": from_group,
                "to_group_id": to_group,
                "change_time_mins": int(minutes),
                "scrap_weight_kg": round(8.0 + 0.45 * int(minutes), 3),
                "enforcement_mode": "HARD",
                "valid_from": approved_at,
                "valid_to": None
            })

    inventory_rows = []
    release_map = policy["inventory_release_policy"]
    for lot in lots:
        excluded = lot["material_grade"] in exclusions
        release_status = (
            release_map["explicit_medical_exclusion"]
            if excluded else release_map.get(lot["status"], "QC_HOLD")
        )
        inventory_rows.append({
            "apply": True,
            "inventory_id": lot["id"],
            "release_status": release_status,
            "use_before_date": lot.get("use_before_date").isoformat() if lot.get("use_before_date") else None,
            "benchmark_context": {
                "material_grade": lot["material_grade"],
                "lot_number": lot.get("lot_number"),
                "quantity_kg": str(lot["quantity_kg"]),
                "legacy_logistics_status": lot["status"]
            }
        })

    active_order_recipe_missing = [
        row["order_id"] for row in active_orders if not row.get("recipe_version_id")
    ]
    corona_required_orders = sum(1 for row in active_orders if row.get("corona_req"))

    return {
        "contract_version": "2026-08-28-benchmark-profile-1",
        "profile_class": "SIMULATED_WITH_OFFICIAL_ENVELOPE",
        "production_authority": False,
        "source": source,
        "machines": machine_rows,
        "machine_material_capabilities": machine_material_rows,
        "machine_feature_capabilities": feature_rows,
        "cleaning_validation_groups": cleaning_groups,
        "cleaning_transition_rules": cleaning_rules,
        "recipe_versions": recipe_rows,
        "material_qualifications": material_rows,
        "machine_recipe_capabilities": machine_recipe_rows,
        "inventory_release": inventory_rows,
        "benchmark_diagnostics": {
            "blocked_recipes": blocked_recipes,
            "active_orders_missing_recipe_version": active_order_recipe_missing,
            "corona_required_active_order_count": corona_required_orders,
            "water_quench_machine_ids": sorted(water_quench_machine_ids),
            "notes": [
                "No missing recipe ratio is fabricated.",
                "Exact manufacturer medical exclusion always wins over simulated benchmark approval.",
                "Machine x Recipe rate is recipe-differentiated but remains simulated.",
                "Apply with apply_wave2_plant_overrides.py; Wave 2 enforcement mode remains LEGACY."
            ]
        },
        "summary": {
            "active_machines": len(machines),
            "recipe_versions": len(recipes),
            "benchmark_released_recipes": sum(1 for row in recipe_rows if row["apply"] and row["status"] == "RELEASED"),
            "blocked_recipe_count": len(blocked_recipes),
            "material_qualifications": len(material_rows),
            "machine_recipe_qualified_pairs": len(machine_recipe_rows),
            "machine_material_capabilities": len(machine_material_rows),
            "machine_feature_rows": len(feature_rows),
            "cleaning_transition_rules": len(cleaning_rules),
            "inventory_rows": len(inventory_rows),
            "active_orders": len(active_orders),
            "active_orders_missing_recipe_version": len(active_order_recipe_missing)
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    policy = _load(args.policy)
    if policy.get("source", {}).get("source_type") != "SIMULATED":
        raise ValueError("Industrial benchmark policy must remain source_type=SIMULATED.")

    conn = _connect()
    try:
        profile = collect_profile(conn, policy)
    finally:
        conn.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(profile, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")

    print(json.dumps(profile["summary"], ensure_ascii=False, indent=2))
    if profile["benchmark_diagnostics"]["blocked_recipes"]:
        print("WARNING: benchmark profile contains unreleased recipes due to incomplete layer/ratio master.")
    print(f"Wrote benchmark profile: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
