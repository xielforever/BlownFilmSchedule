"""Seed a small deterministic demo scenario for the scheduling UI.

The script is intentionally explicit:
  python scripts/seed_demo.py apply
  python scripts/seed_demo.py apply --blocked-pending
  python scripts/seed_demo.py restore
  python scripts/seed_demo.py status

`apply` stores a snapshot in output/demo_seed_snapshot.json before it changes
order statuses or the active run. `restore` uses that snapshot to switch back.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import BASELINE_TIME  # noqa: E402
from src.database import DatabaseManager  # noqa: E402
from src.models import BlownFilmMachineModel, ProductionOrderModel  # noqa: E402
from src.scheduler import AdvancedMedicalAPS  # noqa: E402
from src.setup_matrices import SetupMatricesManager  # noqa: E402

DEMO_TRIGGERED_BY = "demo_seed"
DEMO_ORDER_PREFIX = "DEMO-"
DEMO_MACHINE_PREFIX = "DEMO-LINE-"
SNAPSHOT_PATH = PROJECT_ROOT / "output" / "demo_seed_snapshot.json"


def baseline_dt() -> dt.datetime:
    return dt.datetime.strptime(BASELINE_TIME, "%Y-%m-%d %H:%M")


def at_minute(offset_mins: int) -> dt.datetime:
    return baseline_dt() + dt.timedelta(minutes=offset_mins)


def order(order_id: str, **overrides) -> ProductionOrderModel:
    data = {
        "orderId": order_id,
        "productType": "DEMO-MED-5L",
        "targetWidth": 520,
        "targetThickness": 40,
        "totalQuantityKg": 300,
        "cleanroomReq": "Class_10K",
        "customerClass": "STANDARD",
        "orderClass": "NORMAL",
        "coronaReq": "NO",
        "coreSizeInch": 3,
        "orderDateMins": 0,
        "dueDateMins": 2400,
        "materialAvailableMins": 0,
        "recipeMaterialsSequence": ["Standard_Med_LDPE"] * 5,
    }
    data.update(overrides)
    return ProductionOrderModel.from_dict(data)


def machine(machine_id: str, **overrides) -> BlownFilmMachineModel:
    data = {
        "machineId": machine_id,
        "name": machine_id,
        "cleanroomLevel": "Class_10K",
        "layerStructure": 5,
        "dieDiameterMm": 320,
        "minWidth": 220,
        "maxWidth": 900,
        "minThickness": 20,
        "maxThickness": 80,
        "hourlyOutputKg": 120,
        "maxSlittingLanes": 4,
        "initialMaterialLanes": ["Standard_Med_LDPE"] * 5,
        "initialWidth": 500,
        "initialThickness": 40,
        "forbiddenCalendar": [],
    }
    data.update(overrides)
    return BlownFilmMachineModel.from_dict(data)


def build_demo_setup_mgr() -> SetupMatricesManager:
    mgr = SetupMatricesManager()
    mgr.same_material_time = 25
    mgr.material_switch_matrix.update({
        ("Standard_Med_LDPE", "Borealis_LE6601-PH"): 90,
        ("Borealis_LE6601-PH", "Standard_Med_LDPE"): 60,
        ("Standard_Med_LDPE", "Dow_ELITE_5400G"): 80,
        ("Dow_ELITE_5400G", "Standard_Med_LDPE"): 55,
        ("Dow_ELITE_5400G", "Borealis_LE6601-PH"): 95,
        ("Borealis_LE6601-PH", "Dow_ELITE_5400G"): 85,
        ("Borealis_LE6601-PH", "Special_Co-PE"): 120,
        ("Special_Co-PE", "Borealis_LE6601-PH"): 100,
    })
    mgr.width_up_rules = [(50, 15), (200, 35), (999, 80)]
    mgr.width_down_rules = [(50, 20), (200, 45), (999, 90)]
    mgr.thickness_rules = [(10, 10), (999, 25)]
    mgr.die_change_time = 240
    mgr.corona_switch_time = 20
    mgr.core_size_switch_time = 25
    mgr.gmp_clearance_matrix.update({
        ("NORMAL", "URGENT"): 45,
        ("ANY", "SAMPLE"): 60,
        ("SAMPLE", "ANY"): 60,
    })
    mgr.continuous_run_cleaning_time = 90
    return mgr


def build_demo_inputs():
    recipes_map = {
        "DEMO-MED-5L": ["Standard_Med_LDPE"] * 5,
        "DEMO-HIGH-5L": ["Borealis_LE6601-PH"] * 5,
        "DEMO-PACK-3L": ["Dow_ELITE_5400G"] * 3,
        "DEMO-SPECIAL-5L": ["Special_Co-PE"] * 5,
    }

    machines = [
        machine(
            "DEMO-LINE-01",
            name="Demo class 10K high precision line",
            max_width=900,
            hourlyOutputKg=120,
            forbiddenCalendar=[{
                "startMins": 1440,
                "endMins": 1680,
                "reason": "Demo GMP cleaning window",
            }],
        ),
        machine(
            "DEMO-LINE-02",
            name="Demo class 100K wide line",
            cleanroomLevel="Class_100K",
            minWidth=250,
            maxWidth=1200,
            maxThickness=100,
            hourlyOutputKg=150,
            initialMaterialLanes=["Dow_ELITE_5400G"] * 5,
            initialWidth=700,
            initialThickness=35,
        ),
        machine(
            "DEMO-LINE-03",
            name="Demo class 10K compact line",
            layerStructure=3,
            minWidth=180,
            maxWidth=650,
            hourlyOutputKg=85,
            initialMaterialLanes=["Dow_ELITE_5400G"] * 3,
            initialWidth=420,
            initialThickness=30,
        ),
        machine(
            "DEMO-LINE-04",
            name="Demo spare line with no planned work",
            cleanroomLevel="Class_100K",
            layerStructure=3,
            minWidth=180,
            maxWidth=250,
            hourlyOutputKg=75,
            initialMaterialLanes=["Dow_ELITE_5400G"] * 3,
            initialWidth=220,
            initialThickness=35,
        ),
    ]

    feasible_orders = [
        order(
            "DEMO-001",
            productType="DEMO-HIGH-5L",
            recipeMaterialsSequence=recipes_map["DEMO-HIGH-5L"],
            targetWidth=540,
            targetThickness=42,
            totalQuantityKg=360,
            dueDateMins=1320,
        ),
        order(
            "DEMO-002",
            productType="DEMO-HIGH-5L",
            recipeMaterialsSequence=recipes_map["DEMO-HIGH-5L"],
            targetWidth=560,
            targetThickness=48,
            totalQuantityKg=300,
            orderClass="URGENT",
            materialAvailableMins=900,
            dueDateMins=840,
        ),
        order(
            "DEMO-003",
            productType="DEMO-PACK-3L",
            recipeMaterialsSequence=recipes_map["DEMO-PACK-3L"],
            targetWidth=620,
            targetThickness=35,
            totalQuantityKg=650,
            cleanroomReq="Class_100K",
            dueDateMins=2100,
        ),
        order(
            "DEMO-004",
            productType="DEMO-MED-5L",
            recipeMaterialsSequence=recipes_map["DEMO-MED-5L"],
            targetWidth=810,
            targetThickness=58,
            totalQuantityKg=520,
            dueDateMins=3000,
        ),
        order(
            "DEMO-005",
            productType="DEMO-SPECIAL-5L",
            recipeMaterialsSequence=recipes_map["DEMO-SPECIAL-5L"],
            targetWidth=430,
            targetThickness=34,
            totalQuantityKg=220,
            orderClass="SAMPLE",
            dueDateMins=1800,
        ),
        order(
            "DEMO-006",
            productType="DEMO-PACK-3L",
            recipeMaterialsSequence=recipes_map["DEMO-PACK-3L"],
            targetWidth=320,
            targetThickness=30,
            totalQuantityKg=420,
            cleanroomReq="Class_100K",
            materialAvailableMins=1800,
            dueDateMins=3800,
        ),
        order(
            "DEMO-007",
            productType="DEMO-MED-5L",
            recipeMaterialsSequence=recipes_map["DEMO-MED-5L"],
            targetWidth=760,
            targetThickness=52,
            totalQuantityKg=600,
            dueDateMins=4200,
        ),
        order(
            "DEMO-008",
            productType="DEMO-HIGH-5L",
            recipeMaterialsSequence=recipes_map["DEMO-HIGH-5L"],
            targetWidth=530,
            targetThickness=65,
            totalQuantityKg=380,
            dueDateMins=5200,
        ),
    ]

    blocked_order = order(
        "DEMO-BLOCKED",
        productType="DEMO-HIGH-5L",
        recipeMaterialsSequence=recipes_map["DEMO-HIGH-5L"],
        targetWidth=1800,
        targetThickness=70,
        totalQuantityKg=200,
        dueDateMins=2400,
    )

    return machines, feasible_orders, blocked_order, recipes_map, build_demo_setup_mgr()


def run_demo_schedule():
    machines, feasible_orders, blocked_order, recipes_map, setup_mgr = build_demo_inputs()
    result = AdvancedMedicalAPS(setup_mgr).run(feasible_orders, machines)
    return result, machines, feasible_orders, blocked_order, recipes_map, setup_mgr


def save_snapshot(cur, force: bool):
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SNAPSHOT_PATH.exists() and not force:
        return False

    cur.execute("SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1")
    row = cur.fetchone()
    active_run_id = row[0] if row else None

    cur.execute("SELECT order_id, status FROM production_orders ORDER BY order_id")
    order_statuses = {order_id: status for order_id, status in cur.fetchall()}
    cur.execute("SELECT machine_id, status FROM machines ORDER BY machine_id")
    machine_statuses = {machine_id: status for machine_id, status in cur.fetchall()}

    payload = {
        "created_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "active_run_id": active_run_id,
        "order_statuses": order_statuses,
        "machine_statuses": machine_statuses,
    }
    SNAPSHOT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return True


def clear_demo_data(cur):
    cur.execute(
        """
        DELETE FROM scheduled_tasks
        WHERE run_id IN (SELECT run_id FROM schedule_runs WHERE triggered_by=%s)
           OR order_id LIKE %s
        """,
        (DEMO_TRIGGERED_BY, f"{DEMO_ORDER_PREFIX}%"),
    )
    cur.execute("DELETE FROM schedule_runs WHERE triggered_by=%s", (DEMO_TRIGGERED_BY,))
    cur.execute("DELETE FROM production_actuals WHERE order_id LIKE %s", (f"{DEMO_ORDER_PREFIX}%",))
    cur.execute("DELETE FROM production_orders WHERE order_id LIKE %s", (f"{DEMO_ORDER_PREFIX}%",))
    cur.execute("DELETE FROM machine_downtime_events WHERE machine_id LIKE %s", (f"{DEMO_MACHINE_PREFIX}%",))
    cur.execute("DELETE FROM machine_maintenance_calendar WHERE machine_id LIKE %s", (f"{DEMO_MACHINE_PREFIX}%",))
    cur.execute("DELETE FROM machine_current_state WHERE machine_id LIKE %s", (f"{DEMO_MACHINE_PREFIX}%",))
    cur.execute("DELETE FROM machines WHERE machine_id LIKE %s", (f"{DEMO_MACHINE_PREFIX}%",))
    cur.execute("DELETE FROM recipes WHERE product_type LIKE 'DEMO-%'")
    cur.execute("DELETE FROM products WHERE product_type LIKE 'DEMO-%'")
    cur.execute("DELETE FROM customers WHERE customer_id LIKE 'DEMO-%'")


def seed_reference_data(cur, recipes_map, setup_mgr):
    materials = sorted({mat for mats in recipes_map.values() for mat in mats})
    for material in materials:
        category = "SPECIAL" if material == "Special_Co-PE" else (
            "PACKAGING" if material == "Dow_ELITE_5400G" else "MEDICAL_STD"
        )
        cur.execute(
            """
            INSERT INTO raw_materials (material_grade, material_category, is_special)
            VALUES (%s, %s, %s)
            ON CONFLICT (material_grade) DO UPDATE SET
                material_category=EXCLUDED.material_category,
                is_special=EXCLUDED.is_special
            """,
            (material, category, material == "Special_Co-PE"),
        )

    for product_type, materials_for_product in recipes_map.items():
        cur.execute(
            """
            INSERT INTO products (product_type, product_category, layer_type, cleanroom_requirement, description)
            VALUES (%s, 'DEMO', %s, %s, %s)
            ON CONFLICT (product_type) DO UPDATE SET
                product_category=EXCLUDED.product_category,
                layer_type=EXCLUDED.layer_type,
                cleanroom_requirement=EXCLUDED.cleanroom_requirement,
                description=EXCLUDED.description
            """,
            (
                product_type,
                f"{len(materials_for_product)}L",
                "Class_10K" if product_type != "DEMO-PACK-3L" else "Class_100K",
                "Demo product for scheduling walkthrough",
            ),
        )
        for index, material in enumerate(materials_for_product):
            cur.execute(
                """
                INSERT INTO recipes (recipe_id, product_type, layer, layer_name, material_grade, ratio_pct)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (product_type, layer) DO UPDATE SET
                    material_grade=EXCLUDED.material_grade,
                    ratio_pct=EXCLUDED.ratio_pct
                """,
                (
                    f"R{index + 1:02d}-{product_type.replace('DEMO-', '')[:14]}",
                    product_type,
                    chr(ord("A") + index),
                    f"Layer {index + 1}",
                    material,
                    round(100 / len(materials_for_product), 2),
                ),
            )

    for customer_id, customer_class in (("DEMO-VIP", "VIP"), ("DEMO-STD", "STANDARD")):
        cur.execute(
            """
            INSERT INTO customers (customer_id, customer_name, customer_class)
            VALUES (%s, %s, %s)
            ON CONFLICT (customer_id) DO UPDATE SET
                customer_name=EXCLUDED.customer_name,
                customer_class=EXCLUDED.customer_class
            """,
            (customer_id, customer_id.replace("-", " "), customer_class),
        )

    for (from_material, to_material), mins in setup_mgr.material_switch_matrix.items():
        cur.execute(
            """
            INSERT INTO material_switch_matrix
                (from_material, to_material, switch_time_mins, scrap_weight_kg, description)
            VALUES (%s, %s, %s, 25, 'Demo switch rule')
            ON CONFLICT (from_material, to_material) DO UPDATE SET
                switch_time_mins=EXCLUDED.switch_time_mins,
                description=EXCLUDED.description
            """,
            (from_material, to_material, mins),
        )

    for from_class, to_class, mins in [
        ("NORMAL", "URGENT", 45),
        ("ANY", "SAMPLE", 60),
        ("SAMPLE", "ANY", 60),
    ]:
        cur.execute(
            """
            INSERT INTO gmp_clearance_matrix
                (from_order_class, to_order_class, clearance_time_mins, description)
            VALUES (%s, %s, %s, 'Demo GMP clearance')
            ON CONFLICT (from_order_class, to_order_class) DO UPDATE SET
                clearance_time_mins=EXCLUDED.clearance_time_mins,
                description=EXCLUDED.description
            """,
            (from_class, to_class, mins),
        )


def seed_machines(cur, machines: Iterable[BlownFilmMachineModel]):
    for item in machines:
        cur.execute(
            """
            INSERT INTO machines
                (machine_id, name, cleanroom_level, layer_structure, die_diameter_mm,
                 min_width, max_width, min_thickness, max_thickness, hourly_output_kg,
                 max_slitting_lanes, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ACTIVE')
            ON CONFLICT (machine_id) DO UPDATE SET
                name=EXCLUDED.name,
                cleanroom_level=EXCLUDED.cleanroom_level,
                layer_structure=EXCLUDED.layer_structure,
                die_diameter_mm=EXCLUDED.die_diameter_mm,
                min_width=EXCLUDED.min_width,
                max_width=EXCLUDED.max_width,
                min_thickness=EXCLUDED.min_thickness,
                max_thickness=EXCLUDED.max_thickness,
                hourly_output_kg=EXCLUDED.hourly_output_kg,
                max_slitting_lanes=EXCLUDED.max_slitting_lanes,
                status='ACTIVE',
                updated_at=NOW()
            """,
            (
                item.machine_id,
                item.name,
                item.cleanroom_level,
                item.layer_structure,
                item.die_diameter_mm,
                item.min_width,
                item.max_width,
                item.min_thickness,
                item.max_thickness,
                item.hourly_output_kg,
                item.max_slitting_lanes,
            ),
        )
        cur.execute(
            """
            INSERT INTO machine_current_state
                (machine_id, current_material_lanes, current_width, current_thickness)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (machine_id) DO UPDATE SET
                current_material_lanes=EXCLUDED.current_material_lanes,
                current_width=EXCLUDED.current_width,
                current_thickness=EXCLUDED.current_thickness,
                updated_at=NOW()
            """,
            (
                item.machine_id,
                item.initial_material_lanes,
                item.initial_width,
                item.initial_thickness,
            ),
        )
        for window in item.forbidden_calendar:
            cur.execute(
                """
                INSERT INTO machine_maintenance_calendar
                    (machine_id, start_time, end_time, maintenance_type, reason, is_recurring)
                VALUES (%s, %s, %s, 'GMP_CLEANING', %s, FALSE)
                """,
                (
                    item.machine_id,
                    at_minute(window.start_mins),
                    at_minute(window.end_mins),
                    window.reason,
                ),
            )


def seed_downtime(cur):
    cur.execute(
        """
        INSERT INTO machine_downtime_events
            (machine_id, event_type, severity, start_time, end_time, root_cause, reported_by)
        VALUES
            ('DEMO-LINE-02', 'QUALITY_HOLD', 'MINOR', %s, %s, 'Demo quality hold', 'demo_seed')
        """,
        (at_minute(2100), at_minute(2220)),
    )


def seed_orders(cur, feasible_orders, blocked_order, blocked_pending: bool):
    all_orders = list(feasible_orders) + [blocked_order]
    for item in all_orders:
        status = "PENDING"
        if item.order_id == blocked_order.order_id and not blocked_pending:
            status = "CANCELLED"
        cur.execute(
            """
            INSERT INTO production_orders
                (order_id, customer_id, product_type, target_width, target_thickness,
                 total_quantity_kg, cleanroom_req, order_class, corona_req,
                 core_size_inch, order_date, due_date, material_available_time, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (order_id) DO UPDATE SET
                customer_id=EXCLUDED.customer_id,
                product_type=EXCLUDED.product_type,
                target_width=EXCLUDED.target_width,
                target_thickness=EXCLUDED.target_thickness,
                total_quantity_kg=EXCLUDED.total_quantity_kg,
                cleanroom_req=EXCLUDED.cleanroom_req,
                order_class=EXCLUDED.order_class,
                corona_req=EXCLUDED.corona_req,
                core_size_inch=EXCLUDED.core_size_inch,
                order_date=EXCLUDED.order_date,
                due_date=EXCLUDED.due_date,
                material_available_time=EXCLUDED.material_available_time,
                status=EXCLUDED.status,
                updated_at=NOW()
            """,
            (
                item.order_id,
                "DEMO-VIP" if item.order_class in {"URGENT", "SAMPLE"} else "DEMO-STD",
                item.product_type,
                item.target_width,
                item.target_thickness,
                item.total_quantity_kg,
                item.cleanroom_req,
                item.order_class,
                item.corona_req,
                item.core_size_inch,
                at_minute(item.order_date_mins) if item.order_date_mins else None,
                at_minute(item.due_date_mins),
                at_minute(item.material_available_mins) if item.material_available_mins else None,
                status,
            ),
        )


def set_non_demo_orders_cancelled(cur):
    cur.execute(
        """
        UPDATE production_orders
        SET status='CANCELLED', updated_at=NOW()
        WHERE order_id NOT LIKE %s
        """,
        (f"{DEMO_ORDER_PREFIX}%",),
    )


def set_non_demo_machines_offline(cur):
    cur.execute(
        """
        UPDATE machines
        SET status='OFFLINE', updated_at=NOW()
        WHERE machine_id NOT LIKE %s
        """,
        (f"{DEMO_MACHINE_PREFIX}%",),
    )


def apply_demo(args):
    result, machines, feasible_orders, blocked_order, recipes_map, setup_mgr = run_demo_schedule()
    if result.status not in {"OPTIMAL", "FEASIBLE"}:
        raise RuntimeError(f"Demo schedule is not feasible: {result.status}")

    with DatabaseManager() as db:
        with db.conn.cursor() as cur:
            snapshot_created = save_snapshot(cur, force=args.force_snapshot)
            clear_demo_data(cur)
            set_non_demo_orders_cancelled(cur)
            set_non_demo_machines_offline(cur)
            seed_reference_data(cur, recipes_map, setup_mgr)
            seed_machines(cur, machines)
            seed_downtime(cur)
            seed_orders(cur, feasible_orders, blocked_order, blocked_pending=args.blocked_pending)
        db.conn.commit()

        run_id = db.save_schedule_result(result, triggered_by=DEMO_TRIGGERED_BY)

        if args.blocked_pending:
            with db.conn.cursor() as cur:
                cur.execute(
                    "UPDATE production_orders SET status='PENDING', updated_at=NOW() WHERE order_id=%s",
                    (blocked_order.order_id,),
                )
            db.conn.commit()

    print(
        json.dumps(
            {
                "applied": True,
                "run_id": run_id,
                "orders_scheduled": len(result.tasks),
                "blocked_order": blocked_order.order_id,
                "blocked_pending": args.blocked_pending,
                "snapshot_created": snapshot_created,
                "snapshot": str(SNAPSHOT_PATH),
            },
            indent=2,
        )
    )


def restore_demo(_args):
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError(f"Snapshot not found: {SNAPSHOT_PATH}")
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    with DatabaseManager() as db:
        with db.conn.cursor() as cur:
            clear_demo_data(cur)
            cur.execute("UPDATE schedule_runs SET is_active=FALSE")
            if snapshot.get("active_run_id") is not None:
                cur.execute(
                    "UPDATE schedule_runs SET is_active=TRUE WHERE run_id=%s",
                    (snapshot["active_run_id"],),
                )
            for order_id, status in snapshot.get("order_statuses", {}).items():
                cur.execute(
                    "UPDATE production_orders SET status=%s, updated_at=NOW() WHERE order_id=%s",
                    (status, order_id),
                )
            for machine_id, status in snapshot.get("machine_statuses", {}).items():
                cur.execute(
                    "UPDATE machines SET status=%s, updated_at=NOW() WHERE machine_id=%s",
                    (status, machine_id),
                )
        db.conn.commit()

    print(json.dumps({"restored": True, "snapshot": str(SNAPSHOT_PATH)}, indent=2))


def show_status(_args):
    with DatabaseManager() as db:
        with db.conn.cursor() as cur:
            cur.execute("SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1")
            active = cur.fetchone()
            cur.execute("SELECT count(*) FROM production_orders WHERE order_id LIKE %s", (f"{DEMO_ORDER_PREFIX}%",))
            demo_orders = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM machines WHERE machine_id LIKE %s", (f"{DEMO_MACHINE_PREFIX}%",))
            demo_machines = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM schedule_runs WHERE triggered_by=%s", (DEMO_TRIGGERED_BY,))
            demo_runs = cur.fetchone()[0]

    print(
        json.dumps(
            {
                "active_run_id": active[0] if active else None,
                "demo_orders": demo_orders,
                "demo_machines": demo_machines,
                "demo_runs": demo_runs,
                "snapshot_exists": SNAPSHOT_PATH.exists(),
                "snapshot": str(SNAPSHOT_PATH),
            },
            indent=2,
        )
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Seed or restore the APS demo scenario.")
    sub = parser.add_subparsers(dest="command", required=True)

    apply_parser = sub.add_parser("apply", help="Apply demo data and publish a demo active run.")
    apply_parser.add_argument(
        "--blocked-pending",
        action="store_true",
        help="Leave DEMO-BLOCKED as PENDING so the next Run Schedule demonstrates failure fallback.",
    )
    apply_parser.add_argument(
        "--force-snapshot",
        action="store_true",
        help="Overwrite output/demo_seed_snapshot.json before applying demo data.",
    )
    apply_parser.set_defaults(func=apply_demo)

    restore_parser = sub.add_parser("restore", help="Restore the pre-demo active run and order statuses.")
    restore_parser.set_defaults(func=restore_demo)

    status_parser = sub.add_parser("status", help="Show current demo seed state.")
    status_parser.set_defaults(func=show_status)
    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
