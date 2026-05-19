"""Orders API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_db
from api.auth import get_current_user, require_role

router = APIRouter(prefix="/api/orders", tags=["Orders"])


class OrderUpdate(BaseModel):
    product_type: Optional[str] = None
    target_width: Optional[int] = Field(default=None, gt=0)
    target_thickness: Optional[int] = Field(default=None, gt=0)
    total_quantity_kg: Optional[int] = Field(default=None, gt=0)
    cleanroom_req: Optional[str] = None
    order_class: Optional[str] = None
    corona_req: Optional[bool] = None
    core_size_inch: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[str] = None
    material_available_time: Optional[str] = None
    status: Optional[str] = None
    priority_override: Optional[int] = None


@router.get("")
def list_orders(
    status: str = None,
    q: Optional[str] = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=500),
    db=Depends(get_db),
    _=Depends(get_current_user),
):
    cur = db.cursor()
    where_clauses = ["1=1"]
    params = []
    if status:
        where_clauses.append("o.status=%s")
        params.append(status)
    if q:
        like = f"%{q.strip()}%"
        where_clauses.append(
            """(
                o.order_id ILIKE %s
                OR o.product_type ILIKE %s
                OR o.customer_id ILIKE %s
                OR c.customer_name ILIKE %s
                OR o.status ILIKE %s
                OR t.machine_id ILIKE %s
            )"""
        )
        params.extend([like, like, like, like, like, like])

    where = "WHERE " + " AND ".join(where_clauses)
    offset = (page - 1) * size

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
    """, params + [size, offset])
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
            "material_available_time": r["material_available_time"].isoformat() if r["material_available_time"] else None,
            "status": r["status"],
            "corona_req": r["corona_req"],
            "core_size_inch": r["core_size_inch"],
            "priority_override": r["priority_override"],
            "assigned_machine": r["assigned_machine"],
            "sched_start": r["sched_start"].isoformat() if r["sched_start"] else None,
            "sched_end": r["sched_end"].isoformat() if r["sched_end"] else None,
            "scrap_kg": float(r["scrap_kg"]) if r["scrap_kg"] else 0,
            "setup_mins": r["setup_time_mins"] if r["setup_time_mins"] else 0,
            "actual_material_kg": float(r["actual_material_required_kg"]) if r["actual_material_required_kg"] else 0,
        })

    cur.execute(f"""
        SELECT count(DISTINCT o.order_id) AS cnt
        FROM production_orders o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN scheduled_tasks t ON o.order_id = t.order_id
            AND t.run_id = (SELECT run_id FROM schedule_runs WHERE is_active=TRUE ORDER BY run_id DESC LIMIT 1)
        {where}
    """, params)
    total = cur.fetchone()["cnt"]
    return {"items": items, "total": total, "page": page, "size": size}


@router.patch("/{order_id}")
def update_order(
    order_id: str,
    payload: OrderUpdate,
    db=Depends(get_db),
    _=Depends(require_role("admin", "planner")),
):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No order fields to update.")

    allowed_status = {"PENDING", "SCHEDULED", "IN_PRODUCTION", "COMPLETED", "CANCELLED"}
    if "status" in fields and fields["status"] not in allowed_status:
        raise HTTPException(status_code=400, detail="Invalid order status.")

    allowed_class = {"URGENT", "NORMAL", "SAMPLE"}
    if "order_class" in fields and fields["order_class"] not in allowed_class:
        raise HTTPException(status_code=400, detail="Invalid order class.")

    allowed_cleanroom = {"Class_10K", "Class_100K"}
    if "cleanroom_req" in fields and fields["cleanroom_req"] not in allowed_cleanroom:
        raise HTTPException(status_code=400, detail="Invalid cleanroom requirement.")

    assignments = []
    params = []
    for key, value in fields.items():
        assignments.append(f"{key}=%s")
        params.append(value)
    assignments.append("updated_at=NOW()")
    params.append(order_id)

    cur = db.cursor()
    cur.execute(
        f"UPDATE production_orders SET {', '.join(assignments)} WHERE order_id=%s",
        params,
    )
    if cur.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=404, detail="Order not found.")
    db.commit()
    return {"order_id": order_id, "updated": sorted(fields.keys())}
