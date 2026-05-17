"""Orders API"""
from fastapi import APIRouter, Depends, Query
from api.deps import get_db
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/api/orders", tags=["Orders"])


@router.get("")
def list_orders(status: str = None, page: int = 1, size: int = 50,
                db=Depends(get_db), _=Depends(get_current_user)):
    cur = db.cursor()
    where = "WHERE 1=1"
    params = []
    if status:
        where += " AND o.status=%s"
        params.append(status)

    cur.execute(f"""
        SELECT o.*, c.customer_name, c.customer_class,
            t.machine_id AS assigned_machine, t.start_time AS sched_start,
            t.end_time AS sched_end, t.scrap_kg, t.setup_time_mins,
            t.actual_material_required_kg
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        {where}
        ORDER BY o.due_date
        LIMIT %s OFFSET %s
    """, params + [size, (page - 1) * size])
    items = []
    for r in cur.fetchall():
        items.append({
            "order_id": r["order_id"],
            "product_type": r["product_type"],
            "target_width": r["target_width"],
            "target_thickness": r["target_thickness"],
            "total_quantity_kg": r["total_quantity_kg"],
            "cleanroom_req": r["cleanroom_req"],
            "order_class": r["order_class"],
            "customer_class": r["customer_class"],
            "due_date": r["due_date"].isoformat() if r["due_date"] else None,
            "status": r["status"],
            "corona_req": r["corona_req"],
            "assigned_machine": r["assigned_machine"],
            "sched_start": r["sched_start"].isoformat() if r["sched_start"] else None,
            "sched_end": r["sched_end"].isoformat() if r["sched_end"] else None,
            "scrap_kg": float(r["scrap_kg"]) if r["scrap_kg"] else 0,
            "setup_mins": r["setup_time_mins"] if r["setup_time_mins"] else 0,
            "actual_material_kg": float(r["actual_material_required_kg"]) if r["actual_material_required_kg"] else 0,
        })

    cur.execute(f"SELECT count(*) AS cnt FROM production_orders o {where}", params)
    total = cur.fetchone()["cnt"]
    return {"items": items, "total": total, "page": page}
