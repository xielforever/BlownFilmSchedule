from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from api.routers import orders as orders_router
from api.routers import schedule as schedule_router


class TestOrderFlowSprint1Contracts(unittest.TestCase):
    def test_create_payload_requires_core_order_fields(self):
        self.assertTrue(hasattr(orders_router, "OrderCreatePayload"))

        with self.assertRaises(ValidationError):
            orders_router.OrderCreatePayload(order_id="ORD-NEW-001")

        payload = orders_router.OrderCreatePayload(
            order_id="ORD-NEW-001",
            product_type="Film-A",
            target_width=520,
            target_thickness=35,
            total_quantity_kg=1200,
            cleanroom_req="Class_10K",
            order_class="NORMAL",
            due_date="2026-05-28T08:30:00+08:00",
        )

        self.assertEqual(payload.status, "PENDING")
        self.assertEqual(payload.cleanroom_req, "Class_10K")
        self.assertIsNone(payload.material_available_time)

    def test_update_payload_separates_revision_reason_from_changed_fields(self):
        self.assertTrue(hasattr(orders_router, "OrderUpdatePayload"))

        payload = orders_router.OrderUpdatePayload(
            target_width=610,
            due_date="2026-05-29T08:30:00+08:00",
            reason_code="CUSTOMER_CHANGE",
            reason_text="客户改幅宽和交期",
        )

        changed = payload.changed_fields()
        self.assertEqual(set(changed), {"target_width", "due_date"})
        self.assertNotIn("reason_code", changed)
        self.assertNotIn("reason_text", changed)

    def test_order_revision_diff_ignores_unchanged_fields(self):
        self.assertTrue(hasattr(orders_router, "_order_revision_diff"))
        before = {
            "order_id": "ORD-REV-001",
            "target_width": 520,
            "target_thickness": 35,
            "due_date": datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc),
        }
        changed = {
            "target_width": 520,
            "target_thickness": 40,
            "due_date": "2026-05-28T08:30:00+00:00",
        }

        diff = orders_router._order_revision_diff(before, changed)

        self.assertEqual(list(diff), ["target_thickness"])
        self.assertEqual(diff["target_thickness"]["before"], 35)
        self.assertEqual(diff["target_thickness"]["after"], 40)

    def test_order_snapshot_hash_changes_for_scheduling_fields_only(self):
        self.assertTrue(hasattr(schedule_router, "_order_snapshot_from_row"))
        self.assertTrue(hasattr(schedule_router, "_order_snapshot_hash"))

        base_row = {
            "order_id": "ORD-SNAP-001",
            "product_type": "Film-A",
            "target_width": 520,
            "target_thickness": 35,
            "total_quantity_kg": 1200,
            "cleanroom_req": "Class_10K",
            "order_class": "NORMAL",
            "due_date": datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc),
            "material_available_time": None,
            "status": "PENDING",
            "priority_override": None,
            "updated_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            "customer_id": "CUST-A",
        }
        same_scheduling = {**base_row, "customer_id": "CUST-B"}
        changed_width = {**base_row, "target_width": 610}

        base = schedule_router._order_snapshot_from_row(base_row)
        same = schedule_router._order_snapshot_from_row(same_scheduling)
        changed = schedule_router._order_snapshot_from_row(changed_width)

        self.assertEqual(
            schedule_router._order_snapshot_hash(base),
            schedule_router._order_snapshot_hash(same),
        )
        self.assertNotEqual(
            schedule_router._order_snapshot_hash(base),
            schedule_router._order_snapshot_hash(changed),
        )

    def test_stale_order_snapshot_items_report_changed_fields(self):
        self.assertTrue(hasattr(schedule_router, "_stale_order_snapshot_items"))
        old_snapshot = {
            "order_id": "ORD-STALE-001",
            "updated_at": "2026-05-22T08:00:00+00:00",
            "fields": {
                "product_type": "Film-A",
                "target_width": 520,
                "target_thickness": 35,
                "total_quantity_kg": 1200,
                "cleanroom_req": "Class_10K",
                "order_class": "NORMAL",
                "due_date": "2026-05-28T08:30:00+00:00",
                "material_available_time": None,
                "status": "PENDING",
                "priority_override": None,
            },
        }
        old_snapshot["hash"] = schedule_router._order_snapshot_hash(old_snapshot)
        current_snapshot = {
            **old_snapshot,
            "updated_at": "2026-05-23T08:00:00+00:00",
            "fields": {**old_snapshot["fields"], "target_width": 610},
        }
        current_snapshot["hash"] = schedule_router._order_snapshot_hash(current_snapshot)

        items = schedule_router._stale_order_snapshot_items(
            {"ORD-STALE-001": old_snapshot},
            {"ORD-STALE-001": current_snapshot},
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["severity"], "error")
        self.assertEqual(items[0]["code"], "order_snapshot_stale")
        self.assertEqual(items[0]["order_id"], "ORD-STALE-001")
        self.assertIn("target_width", items[0]["changed_fields"])


class _FakeCursor:
    def __init__(self, db):
        self.db = db
        self._rows = []
        self.rowcount = 0

    @staticmethod
    def _unwrap(value):
        return getattr(value, "adapted", getattr(value, "obj", value))

    def execute(self, sql, params=None):
        params = list(params or [])
        normalized = " ".join(sql.split()).lower()
        self.rowcount = 0

        if normalized.startswith("create table if not exists order_revision_audit"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists order_ingestion_batches"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists order_ingestion_rows"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_revision_audit_order"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_ingestion_rows_batch"):
            self._rows = []
            return
        if normalized.startswith("alter table schedule_runs"):
            self._rows = []
            return
        if normalized.startswith("alter table scheduled_tasks"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists schedule_settings"):
            self._rows = []
            return
        if normalized.startswith("alter table schedule_settings"):
            self._rows = []
            return
        if normalized.startswith("insert into schedule_settings"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists config_change_audit"):
            self._rows = []
            return
        if normalized.startswith("alter table config_change_audit"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists schedule_adjustment_audit"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists manufacturing_queue"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists schedule_publish_audit"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_schedule_publish_audit_run"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_config_change_audit_created"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_schedule_runs_lifecycle"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_queue_status"):
            self._rows = []
            return
        if normalized.startswith("update schedule_runs set lifecycle_status='confirmed' where lifecycle_status is null"):
            self._rows = []
            return
        if normalized.startswith("select 1 from production_orders where order_id=%s"):
            order_id = params[0]
            self._rows = [{"exists": 1}] if order_id in self.db.production_orders else []
            return
        if normalized.startswith("select 1 from products where product_type=%s"):
            product_type = params[0]
            self._rows = [{"exists": 1}] if product_type in self.db.products else []
            return
        if normalized.startswith("select order_id from production_orders where order_id = any"):
            order_ids = params[0]
            self._rows = [
                {"order_id": order_id}
                for order_id in order_ids
                if order_id in self.db.production_orders
            ]
            return
        if normalized.startswith("select product_type from products"):
            self._rows = [{"product_type": product_type} for product_type in sorted(self.db.products)]
            return
        if "from schedule_settings where id=true" in normalized:
            self._rows = [dict(self.db.schedule_settings)]
            return
        if normalized.startswith("select run_id, lifecycle_status") and "from schedule_runs where run_id=%s" in normalized:
            run_id = params[0]
            run = next((item for item in self.db.schedule_runs if item["run_id"] == run_id), None)
            self._rows = [dict(run)] if run else []
            return
        if normalized.startswith("insert into customers"):
            customer_id, customer_name, customer_class = params
            self.db.customers[customer_id] = {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "customer_class": customer_class,
            }
            self._rows = []
            self.rowcount = 1
            return
        if normalized.startswith("insert into production_orders"):
            (
                order_id,
                customer_id,
                product_type,
                target_width,
                target_thickness,
                total_quantity_kg,
                cleanroom_req,
                order_class,
                corona_req,
                core_size_inch,
                order_date,
                due_date,
                material_available_time,
                status,
                priority_override,
            ) = params
            row = {
                "order_id": order_id,
                "customer_id": customer_id,
                "product_type": product_type,
                "target_width": target_width,
                "target_thickness": target_thickness,
                "total_quantity_kg": total_quantity_kg,
                "cleanroom_req": cleanroom_req,
                "order_class": order_class,
                "corona_req": corona_req,
                "core_size_inch": core_size_inch,
                "order_date": order_date,
                "due_date": due_date,
                "material_available_time": material_available_time,
                "status": status,
                "priority_override": priority_override,
                "created_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
                "updated_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            }
            self.db.production_orders[order_id] = row
            self._rows = []
            self.rowcount = 1
            return
        if normalized.startswith("select * from production_orders where order_id=%s"):
            order_id = params[0]
            row = self.db.production_orders.get(order_id)
            self._rows = [dict(row)] if row else []
            return
        if normalized.startswith("select o.*, coalesce(c.customer_class"):
            order_ids = params[0] if params else list(self.db.production_orders)
            rows = []
            for order_id in order_ids:
                row = self.db.production_orders.get(order_id)
                if not row:
                    continue
                product_type = row["product_type"]
                recipe_materials = self.db.recipes.get(product_type, [])
                rows.append({
                    **row,
                    "customer_class": self.db.customers.get(row["customer_id"], {}).get("customer_class", "STANDARD"),
                    "product_exists": product_type in self.db.products,
                    "recipe_layers": len(recipe_materials),
                    "recipe_materials": recipe_materials,
                })
            self._rows = rows
            return
        if normalized.startswith("select machine_id, name, cleanroom_level") and "from machines" in normalized:
            self._rows = [dict(row) for row in self.db.machines]
            return
        if normalized.startswith("update production_orders set"):
            set_clause = sql.split("SET", 1)[1].split("WHERE", 1)[0]
            field_names = [
                part.split("=", 1)[0].strip()
                for part in set_clause.split(",")
                if "%s" in part
            ]
            order_id = params[-1]
            row = self.db.production_orders.get(order_id)
            if row:
                for field, value in zip(field_names, params[:-1]):
                    row[field] = value
                row["updated_at"] = datetime(2026, 5, 23, 8, 0, tzinfo=timezone.utc)
                self.rowcount = 1
            self._rows = []
            return
        if normalized.startswith("select run_id from schedule_runs"):
            order_id = params[0]
            rows = []
            for run in self.db.schedule_runs:
                if run.get("lifecycle_status") not in {"DRAFT", "VALIDATED"}:
                    continue
                selected_ids = (run.get("solver_params") or {}).get("selected_order_ids") or []
                if order_id in selected_ids:
                    rows.append({"run_id": run["run_id"]})
            rows.sort(key=lambda item: item["run_id"], reverse=True)
            self._rows = rows
            return
        if normalized.startswith("insert into order_revision_audit"):
            (
                order_id,
                action_type,
                changed_fields,
                before_state,
                after_state,
                reason_code,
                reason_text,
                impacted_draft_run_ids,
                changed_by,
            ) = params
            row = {
                "id": self.db.next_audit_id,
                "order_id": order_id,
                "action_type": action_type,
                "changed_fields": self._unwrap(changed_fields),
                "before_state": self._unwrap(before_state),
                "after_state": self._unwrap(after_state),
                "reason_code": reason_code,
                "reason_text": reason_text,
                "impacted_draft_run_ids": self._unwrap(impacted_draft_run_ids),
                "changed_by": changed_by,
            }
            self.db.next_audit_id += 1
            self.db.order_revision_audit.append(row)
            self._rows = [{"id": row["id"]}]
            self.rowcount = 1
            return
        if normalized.startswith("insert into order_ingestion_batches"):
            source_name, conflict_policy, total_rows, accepted_rows, rejected_rows, created_by = params
            row = {
                "id": self.db.next_batch_id,
                "source_name": source_name,
                "conflict_policy": conflict_policy,
                "total_rows": total_rows,
                "accepted_rows": accepted_rows,
                "rejected_rows": rejected_rows,
                "created_by": created_by,
            }
            self.db.next_batch_id += 1
            self.db.order_ingestion_batches.append(row)
            self._rows = [{"id": row["id"]}]
            self.rowcount = 1
            return
        if normalized.startswith("insert into order_ingestion_rows"):
            (
                batch_id,
                row_index,
                order_id,
                row_status,
                normalized_order,
                errors,
                warnings,
                created_order,
            ) = params
            self.db.order_ingestion_rows.append({
                "batch_id": batch_id,
                "row_index": row_index,
                "order_id": order_id,
                "row_status": row_status,
                "normalized_order": self._unwrap(normalized_order),
                "errors": self._unwrap(errors),
                "warnings": self._unwrap(warnings),
                "created_order": created_order,
            })
            self._rows = []
            self.rowcount = 1
            return

        raise AssertionError(f"Unhandled SQL: {sql}")

    def fetchone(self):
        if not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self):
        rows = self._rows
        self._rows = []
        return rows


class _FakeDb:
    def __init__(self):
        self.production_orders = {}
        self.products = set()
        self.customers = {}
        self.machines = [
            {
                "machine_id": "LINE-A",
                "name": "LINE-A",
                "cleanroom_level": "Class_10K",
                "layer_structure": 5,
                "die_diameter_mm": 300,
                "min_width": 100,
                "max_width": 1500,
                "min_thickness": 20,
                "max_thickness": 80,
                "hourly_output_kg": 600,
                "max_slitting_lanes": 4,
            }
        ]
        self.recipes = {"Film-A": ["L1", "L2", "L3", "L4", "L5"]}
        self.schedule_runs = []
        self.order_revision_audit = []
        self.order_ingestion_batches = []
        self.order_ingestion_rows = []
        self.schedule_settings = {
            "policy_version": 1,
            "review_required": True,
            "manual_adjust_enabled": True,
            "manual_adjust_reason_required": True,
            "publish_with_warnings_allowed": True,
            "auto_release_enabled": False,
            "material_constraint_enabled": True,
            "maintenance_constraint_enabled": True,
            "setup_rules_enabled": True,
            "cleanroom_constraint_enabled": True,
            "machine_capability_constraint_enabled": True,
            "due_date_optimization_enabled": True,
            "updated_by": None,
            "change_reason": None,
            "updated_at": None,
        }
        self.next_audit_id = 1
        self.next_batch_id = 1
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class TestOrderFlowSprint1Routes(unittest.TestCase):
    def test_create_order_writes_initial_audit_and_defaults_to_pending(self):
        db = _FakeDb()
        db.products.add("Film-A")

        payload = orders_router.OrderCreatePayload(
            order_id="ORD-NEW-001",
            product_type="Film-A",
            target_width=520,
            target_thickness=35,
            total_quantity_kg=1200,
            cleanroom_req="Class_10K",
            order_class="NORMAL",
            due_date="2026-05-28T08:30:00+08:00",
        )

        result = orders_router.create_order(payload, db=db, user=SimpleNamespace(username="planner"))

        self.assertTrue(result["created"])
        self.assertEqual(result["order_id"], "ORD-NEW-001")
        self.assertEqual(result["impacted_draft_run_ids"], [])
        self.assertEqual(result["screening"]["screening_status"], "ready")
        self.assertEqual(db.production_orders["ORD-NEW-001"]["status"], "PENDING")
        self.assertEqual(len(db.order_revision_audit), 1)
        self.assertEqual(db.order_revision_audit[0]["action_type"], "CREATE")
        self.assertEqual(db.commit_count, 1)

    def test_create_order_rejects_duplicate_before_audit(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-EXIST-001"] = {
            "order_id": "ORD-EXIST-001",
            "customer_id": "STANDARD",
            "product_type": "Film-A",
            "target_width": 520,
            "target_thickness": 35,
            "total_quantity_kg": 1200,
            "cleanroom_req": "Class_10K",
            "order_class": "NORMAL",
            "corona_req": False,
            "core_size_inch": 3,
            "order_date": None,
            "due_date": datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc),
            "material_available_time": None,
            "status": "PENDING",
            "priority_override": None,
            "created_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
        }

        payload = orders_router.OrderCreatePayload(
            order_id="ORD-EXIST-001",
            product_type="Film-A",
            target_width=520,
            target_thickness=35,
            total_quantity_kg=1200,
            cleanroom_req="Class_10K",
            order_class="NORMAL",
            due_date="2026-05-28T08:30:00+08:00",
        )

        with self.assertRaises(HTTPException) as ctx:
            orders_router.create_order(payload, db=db, user=SimpleNamespace(username="planner"))

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(db.order_revision_audit), 0)
        self.assertEqual(db.rollback_count, 1)

    def test_import_commit_returns_screening_for_created_orders(self):
        db = _FakeDb()
        db.products.add("Film-A")
        payload = orders_router.OrderImportCommitPayload(
            rows=[
                {
                    "order_id": "ORD-IMP-READY",
                    "product_type": "Film-A",
                    "target_width": "520",
                    "target_thickness": "35",
                    "total_quantity_kg": "1200",
                    "cleanroom_req": "Class_10K",
                    "order_class": "NORMAL",
                    "due_date": "2026-05-28T08:30:00+08:00",
                }
            ],
            source_name="unit-test-import",
        )

        result = orders_router.import_orders_commit(payload, db=db, user=SimpleNamespace(username="planner"))

        self.assertEqual(result["created_order_ids"], ["ORD-IMP-READY"])
        self.assertEqual(result["screening"]["summary"]["ready_count"], 1)
        self.assertEqual(result["screening"]["items"][0]["order_id"], "ORD-IMP-READY")
        self.assertEqual(result["screening"]["items"][0]["screening_status"], "ready")
        self.assertEqual(db.commit_count, 1)

    def test_update_order_writes_diff_and_impacted_drafts(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-REV-001"] = {
            "order_id": "ORD-REV-001",
            "customer_id": "STANDARD",
            "product_type": "Film-A",
            "target_width": 520,
            "target_thickness": 35,
            "total_quantity_kg": 1200,
            "cleanroom_req": "Class_10K",
            "order_class": "NORMAL",
            "corona_req": False,
            "core_size_inch": 3,
            "order_date": None,
            "due_date": datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc),
            "material_available_time": None,
            "status": "PENDING",
            "priority_override": None,
            "created_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
        }
        db.schedule_runs = [
            {
                "run_id": 7,
                "lifecycle_status": "DRAFT",
                "solver_params": {"selected_order_ids": ["ORD-REV-001"]},
            },
            {
                "run_id": 8,
                "lifecycle_status": "CONFIRMED",
                "solver_params": {"selected_order_ids": ["ORD-REV-001"]},
            },
        ]

        payload = orders_router.OrderUpdatePayload(
            target_width=610,
            due_date="2026-05-29T08:30:00+08:00",
            reason_code="CUSTOMER_CHANGE",
            reason_text="客户改幅宽和交期",
        )

        result = orders_router.update_order(
            "ORD-REV-001",
            payload,
            db=db,
            user=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["updated"], ["due_date", "target_width"])
        self.assertEqual(result["impacted_draft_run_ids"], [7])
        self.assertEqual(len(db.order_revision_audit), 1)
        audit = db.order_revision_audit[0]
        self.assertEqual(audit["action_type"], "UPDATE")
        self.assertEqual(audit["reason_code"], "CUSTOMER_CHANGE")
        self.assertEqual(audit["impacted_draft_run_ids"], [7])
        self.assertIn("target_width", audit["changed_fields"])
        self.assertEqual(db.commit_count, 1)

    def test_confirm_preplan_requires_validation_when_review_is_required(self):
        db = _FakeDb()
        db.schedule_runs = [
            {
                "run_id": 11,
                "lifecycle_status": "DRAFT",
            }
        ]

        with self.assertRaises(HTTPException) as ctx:
            schedule_router.confirm_preplan(11, db=db, user=SimpleNamespace(username="planner"))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("需要先校验方案", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
