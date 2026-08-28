"""Generate a no-op Wave 2 override candidate file from the current legacy database.

The generator reduces manual transcription but deliberately does NOT authorize any V2
master data. Every generated row has `apply=false`.

What may be proposed:
- exact LINE-xx identities and current legacy physical metadata;
- recipe-version IDs and structural validation state;
- machine-recipe pairs observed as physically feasible under the legacy screening dimensions;
- legacy hourly_output_kg copied only as a low-confidence SIMULATED candidate rate;
- inventory rows needing explicit release classification.

What is never inferred:
- process route;
- medical release / plant qualification;
- CORONA/IBC/etc feature capability;
- material APPROVED status;
- cleaning taxonomy;
- recipe RELEASED status.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import DATABASE_CONFIG


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "output" / "wave2_override_candidates.json"


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


def _legacy_cleanroom_fit(order_req: str | None, machine_level: str | None) -> bool:
    # Mirrors only the existing binary legacy semantics. It is not an ISO-14644 qualification mapping.
    return not (order_req == "Class_10K" and machine_level == "Class_100K")


def _physical_fit(order: dict, machine: dict, recipe_layer_count: int) -> bool:
    return (
        _legacy_cleanroom_fit(order.get("cleanroom_req"), machine.get("cleanroom_level"))
        and machine["min_width"] <= order["target_width"] <= machine["max_width"]
        and machine["min_thickness"] <= order["target_thickness"] <= machine["max_thickness"]
        and recipe_layer_count <= machine["layer_structure"]
    )


def collect_candidates(conn) -> dict:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        machines = _rows(
            cur,
            """
            SELECT machine_id, name, cleanroom_level, layer_structure,
                   min_width, max_width, min_thickness, max_thickness,
                   hourly_output_kg, max_slitting_lanes, status
            FROM machines
            WHERE status='ACTIVE'
            ORDER BY machine_id
            """,
        )
        recipes = _rows(
            cur,
            """
            SELECT rv.recipe_version_id, rv.product_type, rv.revision,
                   rv.layer_count, rv.process_route, rv.status,
                   v.actual_layer_count, v.missing_ratio_count,
                   v.ratio_total, v.structurally_releasable
            FROM recipe_versions rv
            LEFT JOIN v_recipe_version_validation v
              ON v.recipe_version_id=rv.recipe_version_id
            WHERE rv.status <> 'RETIRED'
            ORDER BY rv.product_type, rv.revision
            """,
        )
        active_orders = _rows(
            cur,
            """
            SELECT order_id, product_type, target_width, target_thickness,
                   cleanroom_req, corona_req, core_size_inch, status
            FROM production_orders
            WHERE status IN ('PENDING','SCHEDULED','IN_PRODUCTION')
            ORDER BY product_type, order_id
            """,
        )
        materials = _rows(
            cur,
            """
            SELECT r.material_grade, r.manufacturer, r.commercial_grade,
                   r.polymer_family, r.material_category,
                   COUNT(DISTINCT e.evidence_id) AS evidence_count,
                   STRING_AGG(DISTINCT e.evidence_status, ',' ORDER BY e.evidence_status) AS evidence_statuses
            FROM raw_materials r
            LEFT JOIN material_application_evidence e ON e.material_grade=r.material_grade
            GROUP BY r.material_grade, r.manufacturer, r.commercial_grade,
                     r.polymer_family, r.material_category
            ORDER BY r.material_grade
            """,
        )
        lots = _rows(
            cur,
            """
            SELECT id, material_grade, lot_number, quantity_kg, status,
                   release_status, expected_arrival, use_before_date
            FROM material_inventory
            ORDER BY material_grade, id
            """,
        )

    orders_by_product: dict[str, list[dict]] = {}
    for order in active_orders:
        orders_by_product.setdefault(order["product_type"], []).append(order)

    machine_rows = []
    for machine in machines:
        machine_rows.append({
            "apply": False,
            "machine_id": machine["machine_id"],
            "process_route": "UNKNOWN",
            "medical_release_status": "UNKNOWN",
            "cleanroom_standard": None,
            "cleanroom_iso_class": None,
            "qualification_status": "UNKNOWN",
            "qualification_valid_until": None,
            "legacy_context": {
                "name": machine["name"],
                "legacy_cleanroom_level": machine["cleanroom_level"],
                "layer_structure": machine["layer_structure"],
                "width_range_mm": [machine["min_width"], machine["max_width"]],
                "thickness_range_um": [machine["min_thickness"], machine["max_thickness"]],
                "hourly_output_kg": machine["hourly_output_kg"],
                "max_slitting_lanes": machine["max_slitting_lanes"],
            },
            "review_required": [
                "process_route",
                "medical_release_status",
                "canonical_cleanroom_qualification",
                "feature_capabilities",
            ],
        })

    recipe_rows = []
    machine_recipe_rows = []
    for recipe in recipes:
        recipe_rows.append({
            "apply": False,
            "recipe_version_id": recipe["recipe_version_id"],
            "process_route": recipe.get("process_route") or "UNKNOWN",
            "status": recipe["status"],
            "cleaning_validation_group_id": None,
            "approved_by": None,
            "approved_at": None,
            "change_reason": "Generated candidate only; review process route, ratios and plant approval before apply=true.",
            "legacy_context": {
                "product_type": recipe["product_type"],
                "layer_count": recipe["layer_count"],
                "actual_layer_count": recipe.get("actual_layer_count"),
                "missing_ratio_count": recipe.get("missing_ratio_count"),
                "ratio_total": str(recipe["ratio_total"]) if recipe.get("ratio_total") is not None else None,
                "structurally_releasable": recipe.get("structurally_releasable"),
            },
        })

        product_orders = orders_by_product.get(recipe["product_type"], [])
        for machine in machines:
            fitting_orders = [
                order for order in product_orders
                if _physical_fit(order, machine, int(recipe["layer_count"]))
            ]
            if not fitting_orders:
                continue
            machine_recipe_rows.append({
                "apply": False,
                "machine_id": machine["machine_id"],
                "recipe_version_id": recipe["recipe_version_id"],
                "eligibility_status": "UNKNOWN",
                "standard_rate_kg_h": float(machine["hourly_output_kg"]),
                "min_rate_kg_h": None,
                "max_rate_kg_h": None,
                "startup_rate_factor": None,
                "quality_status": "UNKNOWN",
                "validation_protocol_id": None,
                "confidence": 0.10,
                "valid_from": None,
                "valid_to": None,
                "candidate_basis": "LEGACY_PHYSICAL_SCREENING_PLUS_MACHINE_CONSTANT_RATE",
                "observed_active_order_count": len(fitting_orders),
                "observed_order_ids": [order["order_id"] for order in fitting_orders[:20]],
                "warning": "Candidate only. Legacy hourly_output_kg is not a recipe-specific qualified rate.",
            })

    material_review = []
    for material in materials:
        material_review.append({
            "material_grade": material["material_grade"],
            "manufacturer": material.get("manufacturer"),
            "commercial_grade": material.get("commercial_grade"),
            "polymer_family": material.get("polymer_family"),
            "legacy_material_category": material.get("material_category"),
            "manufacturer_evidence_count": material.get("evidence_count", 0),
            "manufacturer_evidence_statuses": material.get("evidence_statuses"),
            "proposed_plant_qualification": "UNKNOWN",
            "apply": False,
        })

    inventory_rows = []
    for lot in lots:
        inventory_rows.append({
            "apply": False,
            "inventory_id": lot["id"],
            "release_status": lot.get("release_status") or "UNKNOWN",
            "use_before_date": lot.get("use_before_date").isoformat() if lot.get("use_before_date") else None,
            "legacy_context": {
                "material_grade": lot["material_grade"],
                "lot_number": lot.get("lot_number"),
                "quantity_kg": str(lot["quantity_kg"]),
                "logistics_status": lot["status"],
                "expected_arrival": lot.get("expected_arrival").isoformat() if lot.get("expected_arrival") else None,
            },
        })

    return {
        "contract_version": "2026-08-28-candidate-1",
        "generated_from": "LEGACY_DB_RUNTIME_INTROSPECTION",
        "safety": {
            "all_apply_false": True,
            "process_route_inference": False,
            "medical_qualification_inference": False,
            "legacy_rate_is_qualified": False,
            "purpose": "reduce transcription and expose review gaps",
        },
        "source": {
            "source_id": "SRC-SIM-WAVE2-LEGACY-CANDIDATES",
            "source_type": "SIMULATED",
            "organization": "BlownFilmSchedule",
            "title": "Wave 2 legacy-derived candidate override set",
            "url_or_reference": None,
            "revision": "generated",
            "confidence": "LOW",
            "metadata": {
                "candidate_only": True,
                "production_authority": False,
            },
        },
        "machines": machine_rows,
        "recipe_versions": recipe_rows,
        "machine_recipe_capabilities": machine_recipe_rows,
        "material_review": material_review,
        "inventory_release": inventory_rows,
        "machine_material_capabilities": [],
        "machine_feature_capabilities": [],
        "cleaning_validation_groups": [],
        "cleaning_transition_rules": [],
        "material_qualifications": [],
        "summary": {
            "active_machines": len(machines),
            "recipe_versions": len(recipes),
            "active_orders": len(active_orders),
            "machine_recipe_candidate_pairs": len(machine_recipe_rows),
            "materials_for_review": len(material_review),
            "lots_for_release_review": len(inventory_rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    conn = _connect()
    try:
        payload = collect_candidates(conn)
    finally:
        conn.close()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")

    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote no-op candidate file: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
