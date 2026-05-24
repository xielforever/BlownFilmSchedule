from datetime import datetime

from src.snapshotting import (
    build_input_snapshot,
    build_machine_capability_snapshot,
    build_order_snapshot,
)


def test_machine_capability_snapshot_hash_changes_for_capacity_fields():
    base_rows = [
        {
            "machine_id": "BF-01",
            "status": "ACTIVE",
            "cleanroom_level": "Class_10K",
            "layer_structure": 5,
            "min_width": 100,
            "max_width": 1500,
            "min_thickness": 20,
            "max_thickness": 120,
            "hourly_output_kg": 100,
            "max_slitting_lanes": 4,
            "updated_at": datetime(2026, 5, 24, 8, 0),
        }
    ]
    same_rows = [{**base_rows[0], "updated_at": datetime(2026, 5, 24, 9, 0)}]
    changed_rows = [{**base_rows[0], "max_width": 1800}]

    base = build_machine_capability_snapshot(base_rows)
    same = build_machine_capability_snapshot(same_rows)
    changed = build_machine_capability_snapshot(changed_rows)

    assert base["hash"] == same["hash"]
    assert base["hash"] != changed["hash"]
    assert base["count"] == 1


def test_input_snapshot_combines_order_machine_rule_process_and_screening_hashes():
    order_snapshot = build_order_snapshot(
        {
            "order_id": "ORD-001",
            "product_type": "Film-A",
            "target_width": 600,
            "target_thickness": 45,
            "total_quantity_kg": 1200,
            "cleanroom_req": "Class_10K",
            "order_class": "URGENT",
            "due_date": datetime(2026, 5, 28, 8, 0),
            "material_available_time": None,
            "status": "PENDING",
            "priority_override": None,
            "updated_at": datetime(2026, 5, 24, 8, 0),
        }
    )
    machine_snapshot = build_machine_capability_snapshot(
        [
            {
                "machine_id": "BF-01",
                "status": "ACTIVE",
                "cleanroom_level": "Class_10K",
                "layer_structure": 5,
                "min_width": 100,
                "max_width": 1500,
                "min_thickness": 20,
                "max_thickness": 120,
                "hourly_output_kg": 100,
                "max_slitting_lanes": 4,
            }
        ]
    )

    snapshot = build_input_snapshot(
        order_snapshots=[order_snapshot],
        machine_capability_snapshot=machine_snapshot,
        maintenance_calendar_snapshot={"hash": "calendar-v1", "count": 0},
        rule_matrix_snapshot={"hash": "rules-v1", "counts": {"material_switch": 2}},
        process_snapshot={"hash": "process-v1", "count": 1},
        screening_snapshot={"hash": "screening-v1", "summary": {"ready": 1}},
    )

    assert snapshot["orders"]["count"] == 1
    assert snapshot["machine_capability"]["hash"] == machine_snapshot["hash"]
    assert snapshot["maintenance_calendar"]["hash"] == "calendar-v1"
    assert snapshot["rule_matrix"]["hash"] == "rules-v1"
    assert snapshot["process"]["hash"] == "process-v1"
    assert snapshot["screening"]["hash"] == "screening-v1"
    assert snapshot["hash"]
