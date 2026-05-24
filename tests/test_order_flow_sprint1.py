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
        if normalized.startswith("create table if not exists order_screening_cache"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists order_screening_override_audit"):
            self._rows = []
            return
        if normalized.startswith("create table if not exists order_screening_action_audit"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_revision_audit_order"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_ingestion_rows_batch"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_screening_cache_status"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_screening_cache_bucket"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_screening_override_order"):
            self._rows = []
            return
        if normalized.startswith("create index if not exists idx_order_screening_action_order"):
            self._rows = []
            return
        if normalized.startswith("alter table order_screening_cache"):
            self._rows = []
            return
        if normalized.startswith("update order_screening_cache set business_bucket"):
            updated = 0
            for row in self.db.order_screening_cache.values():
                if row.get("business_bucket"):
                    continue
                business_bucket = (row.get("result") or {}).get("business_bucket")
                if not business_bucket:
                    continue
                row["business_bucket"] = business_bucket
                updated += 1
            self._rows = []
            self.rowcount = updated
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
        if normalized.startswith("update schedule_settings set"):
            set_clause = sql.split("SET", 1)[1].split("WHERE", 1)[0]
            field_names = [
                part.split("=", 1)[0].strip()
                for part in set_clause.split(",")
                if "%s" in part
            ]
            for field, value in zip(field_names, params):
                self.db.schedule_settings[field] = value
            self.db.schedule_settings["policy_version"] = int(self.db.schedule_settings["policy_version"]) + 1
            self.db.schedule_settings["updated_at"] = datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc)
            self._rows = []
            self.rowcount = 1
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
        if normalized.startswith("select distinct trim(assignee) as assignee"):
            assignees = sorted({
                item.get("assignee").strip()
                for item in self.db.order_screening_action_audit
                if item.get("assignee") and item.get("assignee").strip()
            })
            self._rows = [{"assignee": assignee} for assignee in assignees]
            return
        if "from production_orders o" in normalized and "limit %s offset %s" in normalized:
            param_index = 0
            status_filter = None
            screening_status_filter = None
            screening_bucket_filter = None
            screening_stale_filter = None
            screening_action_status_filter = None
            screening_action_type_filter = None
            screening_action_assignee_filter = None
            if "o.status=%s" in normalized:
                status_filter = params[param_index]
                param_index += 1
            if "lower(osc.screening_status)=%s" in normalized:
                screening_status_filter = params[param_index]
                param_index += 1
            if "business_bucket" in normalized and "coalesce" in normalized and "=%s" in normalized:
                screening_bucket_filter = params[param_index]
                param_index += 1
            if "coalesce(osc.is_stale, false)=%s" in normalized:
                screening_stale_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.handling_status)=%s" in normalized:
                screening_action_status_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.action_type)=%s" in normalized:
                screening_action_type_filter = params[param_index]
                param_index += 1
            if "lower(trim(latest_action.assignee))=%s" in normalized:
                screening_action_assignee_filter = params[param_index]
                param_index += 1
            screening_action_unhandled_filter = "latest_action.handling_status is null" in normalized
            screening_action_unassigned_filter = "latest_action.assignee is null" in normalized
            rows = []
            for row in self.db.production_orders.values():
                cache = self.db.order_screening_cache.get(row["order_id"], {})
                overrides = [
                    dict(item)
                    for item in self.db.order_screening_override_audit
                    if item["order_id"] == row["order_id"]
                ]
                overrides.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
                latest_override = overrides[0] if overrides else {}
                actions = [
                    dict(item)
                    for item in self.db.order_screening_action_audit
                    if item["order_id"] == row["order_id"]
                ]
                actions.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
                latest_action = actions[0] if actions else {}
                if status_filter and row["status"] != status_filter:
                    continue
                if screening_status_filter and (cache.get("screening_status") or "").lower() != screening_status_filter:
                    continue
                business_bucket = (cache.get("result") or {}).get("business_bucket")
                if screening_bucket_filter and (business_bucket or "").lower() != screening_bucket_filter:
                    continue
                if screening_stale_filter is not None and bool(cache.get("is_stale")) is not bool(screening_stale_filter):
                    continue
                if (
                    screening_action_status_filter
                    and (latest_action.get("handling_status") or "").lower() != screening_action_status_filter
                ):
                    continue
                if screening_action_unhandled_filter and latest_action.get("handling_status"):
                    continue
                if (
                    screening_action_type_filter
                    and (latest_action.get("action_type") or "").lower() != screening_action_type_filter
                ):
                    continue
                if (
                    screening_action_assignee_filter
                    and (latest_action.get("assignee") or "").strip().lower() != screening_action_assignee_filter
                ):
                    continue
                if screening_action_unassigned_filter and latest_action.get("assignee"):
                    continue
                rows.append({
                    **row,
                    "customer_name": self.db.customers.get(row["customer_id"], {}).get("customer_name"),
                    "customer_class": self.db.customers.get(row["customer_id"], {}).get("customer_class", "STANDARD"),
                    "assigned_machine": None,
                    "sched_start": None,
                    "sched_end": None,
                    "scrap_kg": 0,
                    "setup_time_mins": 0,
                    "actual_material_required_kg": 0,
                    "screening_status": cache.get("screening_status"),
                    "screening_code": cache.get("code"),
                    "screening_root_cause": cache.get("root_cause"),
                    "screening_is_stale": cache.get("is_stale"),
                    "screening_stale_reason": cache.get("stale_reason"),
                    "screening_business_bucket": cache.get("business_bucket"),
                    "screening_result": cache.get("result"),
                    "screening_override_id": latest_override.get("id"),
                    "screening_override_status": latest_override.get("screening_status"),
                    "screening_override_code": latest_override.get("screening_code"),
                    "screening_override_policy": latest_override.get("override_policy"),
                    "screening_override_reason_code": latest_override.get("reason_code"),
                    "screening_override_reason_text": latest_override.get("reason_text"),
                    "screening_override_mode": latest_override.get("mode"),
                    "screening_override_policy_version": latest_override.get("policy_version"),
                    "screening_override_actor": latest_override.get("actor"),
                    "screening_override_details": latest_override.get("details"),
                    "screening_override_created_at": latest_override.get("created_at"),
                    "screening_action_id": latest_action.get("id"),
                    "screening_action_status": latest_action.get("screening_status"),
                    "screening_action_bucket": latest_action.get("business_bucket"),
                    "screening_action_code": latest_action.get("screening_code"),
                    "screening_action_type": latest_action.get("action_type"),
                    "screening_action_handling_status": latest_action.get("handling_status"),
                    "screening_action_reason_text": latest_action.get("reason_text"),
                    "screening_action_assignee": latest_action.get("assignee"),
                    "screening_action_actor": latest_action.get("actor"),
                    "screening_action_details": latest_action.get("details"),
                    "screening_action_created_at": latest_action.get("created_at"),
                })
            self._rows = sorted(rows, key=lambda item: item["due_date"])
            return
        if normalized.startswith("select count(distinct o.order_id) as cnt"):
            param_index = 0
            status_filter = None
            screening_status_filter = None
            screening_bucket_filter = None
            screening_stale_filter = None
            screening_action_status_filter = None
            screening_action_type_filter = None
            screening_action_assignee_filter = None
            if "o.status=%s" in normalized:
                status_filter = params[param_index]
                param_index += 1
            if "lower(osc.screening_status)=%s" in normalized:
                screening_status_filter = params[param_index]
                param_index += 1
            if "business_bucket" in normalized and "coalesce" in normalized and "=%s" in normalized:
                screening_bucket_filter = params[param_index]
                param_index += 1
            if "coalesce(osc.is_stale, false)=%s" in normalized:
                screening_stale_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.handling_status)=%s" in normalized:
                screening_action_status_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.action_type)=%s" in normalized:
                screening_action_type_filter = params[param_index]
                param_index += 1
            if "lower(trim(latest_action.assignee))=%s" in normalized:
                screening_action_assignee_filter = params[param_index]
                param_index += 1
            screening_action_unhandled_filter = "latest_action.handling_status is null" in normalized
            screening_action_unassigned_filter = "latest_action.assignee is null" in normalized
            count = 0
            for row in self.db.production_orders.values():
                cache = self.db.order_screening_cache.get(row["order_id"], {})
                actions = [
                    dict(item)
                    for item in self.db.order_screening_action_audit
                    if item["order_id"] == row["order_id"]
                ]
                actions.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
                latest_action = actions[0] if actions else {}
                if status_filter and row["status"] != status_filter:
                    continue
                if screening_status_filter and (cache.get("screening_status") or "").lower() != screening_status_filter:
                    continue
                business_bucket = (cache.get("result") or {}).get("business_bucket")
                if screening_bucket_filter and (business_bucket or "").lower() != screening_bucket_filter:
                    continue
                if screening_stale_filter is not None and bool(cache.get("is_stale")) is not bool(screening_stale_filter):
                    continue
                if (
                    screening_action_status_filter
                    and (latest_action.get("handling_status") or "").lower() != screening_action_status_filter
                ):
                    continue
                if screening_action_unhandled_filter and latest_action.get("handling_status"):
                    continue
                if (
                    screening_action_type_filter
                    and (latest_action.get("action_type") or "").lower() != screening_action_type_filter
                ):
                    continue
                if (
                    screening_action_assignee_filter
                    and (latest_action.get("assignee") or "").strip().lower() != screening_action_assignee_filter
                ):
                    continue
                if screening_action_unassigned_filter and latest_action.get("assignee"):
                    continue
                count += 1
            self._rows = [{"cnt": count}]
            return
        if normalized.startswith("select coalesce(latest_action.handling_status, 'unhandled')"):
            param_index = 0
            status_filter = None
            screening_status_filter = None
            screening_bucket_filter = None
            screening_stale_filter = None
            screening_action_status_filter = None
            screening_action_type_filter = None
            screening_action_assignee_filter = None
            if "o.status=%s" in normalized:
                status_filter = params[param_index]
                param_index += 1
            if "lower(osc.screening_status)=%s" in normalized:
                screening_status_filter = params[param_index]
                param_index += 1
            if "business_bucket" in normalized and "coalesce" in normalized and "=%s" in normalized:
                screening_bucket_filter = params[param_index]
                param_index += 1
            if "coalesce(osc.is_stale, false)=%s" in normalized:
                screening_stale_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.handling_status)=%s" in normalized:
                screening_action_status_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.action_type)=%s" in normalized:
                screening_action_type_filter = params[param_index]
                param_index += 1
            if "lower(trim(latest_action.assignee))=%s" in normalized:
                screening_action_assignee_filter = params[param_index]
                param_index += 1
            screening_action_unhandled_filter = "latest_action.handling_status is null" in normalized
            screening_action_unassigned_filter = "latest_action.assignee is null" in normalized
            counts = {}
            for row in self.db.production_orders.values():
                cache = self.db.order_screening_cache.get(row["order_id"], {})
                actions = [
                    dict(item)
                    for item in self.db.order_screening_action_audit
                    if item["order_id"] == row["order_id"]
                ]
                actions.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
                latest_action = actions[0] if actions else {}
                if status_filter and row["status"] != status_filter:
                    continue
                if screening_status_filter and (cache.get("screening_status") or "").lower() != screening_status_filter:
                    continue
                business_bucket = (cache.get("result") or {}).get("business_bucket")
                if screening_bucket_filter and (business_bucket or "").lower() != screening_bucket_filter:
                    continue
                if screening_stale_filter is not None and bool(cache.get("is_stale")) is not bool(screening_stale_filter):
                    continue
                if (
                    screening_action_status_filter
                    and (latest_action.get("handling_status") or "").lower() != screening_action_status_filter
                ):
                    continue
                if screening_action_unhandled_filter and latest_action.get("handling_status"):
                    continue
                if (
                    screening_action_type_filter
                    and (latest_action.get("action_type") or "").lower() != screening_action_type_filter
                ):
                    continue
                if (
                    screening_action_assignee_filter
                    and (latest_action.get("assignee") or "").strip().lower() != screening_action_assignee_filter
                ):
                    continue
                if screening_action_unassigned_filter and latest_action.get("assignee"):
                    continue
                key = latest_action.get("handling_status") or "unhandled"
                counts[key] = counts.get(key, 0) + 1
            self._rows = [
                {"handling_status": key, "cnt": value}
                for key, value in counts.items()
            ]
            return
        if normalized.startswith("select coalesce(latest_action.action_type, 'unhandled')"):
            param_index = 0
            status_filter = None
            screening_status_filter = None
            screening_bucket_filter = None
            screening_stale_filter = None
            screening_action_status_filter = None
            screening_action_type_filter = None
            screening_action_assignee_filter = None
            if "o.status=%s" in normalized:
                status_filter = params[param_index]
                param_index += 1
            if "lower(osc.screening_status)=%s" in normalized:
                screening_status_filter = params[param_index]
                param_index += 1
            if "business_bucket" in normalized and "coalesce" in normalized and "=%s" in normalized:
                screening_bucket_filter = params[param_index]
                param_index += 1
            if "coalesce(osc.is_stale, false)=%s" in normalized:
                screening_stale_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.handling_status)=%s" in normalized:
                screening_action_status_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.action_type)=%s" in normalized:
                screening_action_type_filter = params[param_index]
                param_index += 1
            if "lower(trim(latest_action.assignee))=%s" in normalized:
                screening_action_assignee_filter = params[param_index]
                param_index += 1
            screening_action_unhandled_filter = "latest_action.handling_status is null" in normalized
            screening_action_unassigned_filter = "latest_action.assignee is null" in normalized
            counts = {}
            for row in self.db.production_orders.values():
                cache = self.db.order_screening_cache.get(row["order_id"], {})
                actions = [
                    dict(item)
                    for item in self.db.order_screening_action_audit
                    if item["order_id"] == row["order_id"]
                ]
                actions.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
                latest_action = actions[0] if actions else {}
                if status_filter and row["status"] != status_filter:
                    continue
                if screening_status_filter and (cache.get("screening_status") or "").lower() != screening_status_filter:
                    continue
                business_bucket = (cache.get("result") or {}).get("business_bucket")
                if screening_bucket_filter and (business_bucket or "").lower() != screening_bucket_filter:
                    continue
                if screening_stale_filter is not None and bool(cache.get("is_stale")) is not bool(screening_stale_filter):
                    continue
                if (
                    screening_action_status_filter
                    and (latest_action.get("handling_status") or "").lower() != screening_action_status_filter
                ):
                    continue
                if screening_action_unhandled_filter and latest_action.get("handling_status"):
                    continue
                if (
                    screening_action_type_filter
                    and (latest_action.get("action_type") or "").lower() != screening_action_type_filter
                ):
                    continue
                if (
                    screening_action_assignee_filter
                    and (latest_action.get("assignee") or "").strip().lower() != screening_action_assignee_filter
                ):
                    continue
                if screening_action_unassigned_filter and latest_action.get("assignee"):
                    continue
                key = latest_action.get("action_type") or "unhandled"
                counts[key] = counts.get(key, 0) + 1
            self._rows = [
                {"action_type": key, "cnt": value}
                for key, value in counts.items()
            ]
            return
        if normalized.startswith("select coalesce(latest_action.assignee, 'unassigned')"):
            param_index = 0
            status_filter = None
            screening_status_filter = None
            screening_bucket_filter = None
            screening_stale_filter = None
            screening_action_status_filter = None
            screening_action_type_filter = None
            screening_action_assignee_filter = None
            if "o.status=%s" in normalized:
                status_filter = params[param_index]
                param_index += 1
            if "lower(osc.screening_status)=%s" in normalized:
                screening_status_filter = params[param_index]
                param_index += 1
            if "business_bucket" in normalized and "coalesce" in normalized and "=%s" in normalized:
                screening_bucket_filter = params[param_index]
                param_index += 1
            if "coalesce(osc.is_stale, false)=%s" in normalized:
                screening_stale_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.handling_status)=%s" in normalized:
                screening_action_status_filter = params[param_index]
                param_index += 1
            if "lower(latest_action.action_type)=%s" in normalized:
                screening_action_type_filter = params[param_index]
                param_index += 1
            if "lower(trim(latest_action.assignee))=%s" in normalized:
                screening_action_assignee_filter = params[param_index]
                param_index += 1
            screening_action_unhandled_filter = "latest_action.handling_status is null" in normalized
            screening_action_unassigned_filter = "latest_action.assignee is null" in normalized
            counts = {}
            for row in self.db.production_orders.values():
                cache = self.db.order_screening_cache.get(row["order_id"], {})
                actions = [
                    dict(item)
                    for item in self.db.order_screening_action_audit
                    if item["order_id"] == row["order_id"]
                ]
                actions.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
                latest_action = actions[0] if actions else {}
                if status_filter and row["status"] != status_filter:
                    continue
                if screening_status_filter and (cache.get("screening_status") or "").lower() != screening_status_filter:
                    continue
                business_bucket = (cache.get("result") or {}).get("business_bucket")
                if screening_bucket_filter and (business_bucket or "").lower() != screening_bucket_filter:
                    continue
                if screening_stale_filter is not None and bool(cache.get("is_stale")) is not bool(screening_stale_filter):
                    continue
                if (
                    screening_action_status_filter
                    and (latest_action.get("handling_status") or "").lower() != screening_action_status_filter
                ):
                    continue
                if screening_action_unhandled_filter and latest_action.get("handling_status"):
                    continue
                if (
                    screening_action_type_filter
                    and (latest_action.get("action_type") or "").lower() != screening_action_type_filter
                ):
                    continue
                if (
                    screening_action_assignee_filter
                    and (latest_action.get("assignee") or "").strip().lower() != screening_action_assignee_filter
                ):
                    continue
                if screening_action_unassigned_filter and latest_action.get("assignee"):
                    continue
                key = latest_action.get("assignee") or "unassigned"
                counts[key] = counts.get(key, 0) + 1
            self._rows = [
                {"assignee": key, "cnt": value}
                for key, value in counts.items()
            ]
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
        if normalized.startswith("insert into config_change_audit"):
            (
                config_scope,
                config_key,
                entity_id,
                before_state,
                after_state,
                changed_by,
                reason_text,
            ) = params
            self.db.config_change_audit.append({
                "config_scope": config_scope,
                "config_key": config_key,
                "entity_id": entity_id,
                "before_state": self._unwrap(before_state),
                "after_state": self._unwrap(after_state),
                "changed_by": changed_by,
                "reason_text": reason_text,
            })
            self._rows = []
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
        if normalized.startswith("insert into order_screening_cache"):
            order_id, screening_status, business_bucket, code, root_cause, result, summary, scope = params
            self.db.order_screening_cache[order_id] = {
                "order_id": order_id,
                "screening_status": screening_status,
                "business_bucket": business_bucket,
                "code": code,
                "root_cause": root_cause,
                "result": self._unwrap(result),
                "summary": self._unwrap(summary),
                "scope": scope,
                "is_stale": False,
            }
            self._rows = []
            self.rowcount = 1
            return
        if normalized.startswith("insert into order_screening_override_audit"):
            (
                order_id,
                screening_status,
                screening_code,
                override_policy,
                reason_code,
                reason_text,
                mode,
                policy_version,
                actor,
                details,
            ) = params
            row = {
                "id": self.db.next_screening_override_audit_id,
                "order_id": order_id,
                "screening_status": screening_status,
                "screening_code": screening_code,
                "override_policy": override_policy,
                "reason_code": reason_code,
                "reason_text": reason_text,
                "mode": mode,
                "policy_version": policy_version,
                "actor": actor,
                "details": self._unwrap(details),
            }
            self.db.next_screening_override_audit_id += 1
            self.db.order_screening_override_audit.append(row)
            self._rows = [{"id": row["id"]}]
            self.rowcount = 1
            return
        if normalized.startswith("select o.order_id, osc.screening_status, osc.business_bucket"):
            order_id = params[0]
            order = self.db.production_orders.get(order_id)
            cache = self.db.order_screening_cache.get(order_id)
            self._rows = [
                {
                    "order_id": order_id,
                    "screening_status": cache.get("screening_status") if cache else None,
                    "business_bucket": cache.get("business_bucket") if cache else None,
                    "screening_code": cache.get("code") if cache else None,
                    "root_cause": cache.get("root_cause") if cache else None,
                    "screening_result": cache.get("result") if cache else None,
                }
            ] if order else []
            return
        if normalized.startswith("insert into order_screening_action_audit"):
            (
                order_id,
                screening_status,
                business_bucket,
                screening_code,
                action_type,
                handling_status,
                reason_text,
                assignee,
                actor,
                details,
            ) = params
            row = {
                "id": self.db.next_screening_action_audit_id,
                "order_id": order_id,
                "screening_status": screening_status,
                "business_bucket": business_bucket,
                "screening_code": screening_code,
                "action_type": action_type,
                "handling_status": handling_status,
                "reason_text": reason_text,
                "assignee": assignee,
                "actor": actor,
                "details": self._unwrap(details),
                "created_at": datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc),
            }
            self.db.next_screening_action_audit_id += 1
            self.db.order_screening_action_audit.append(row)
            self._rows = [dict(row)]
            self.rowcount = 1
            return
        if normalized.startswith("select id, order_id, screening_status, screening_code, override_policy"):
            order_id = params[0]
            rows = [
                dict(row)
                for row in self.db.order_screening_override_audit
                if row["order_id"] == order_id
            ]
            rows.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
            self._rows = rows[:50]
            return
        if normalized.startswith("select id, order_id, screening_status, business_bucket, screening_code"):
            order_id = params[0]
            handling_status_filter = params[1] if "and handling_status=%s" in normalized else None
            rows = [
                dict(row)
                for row in self.db.order_screening_action_audit
                if row["order_id"] == order_id
                and (not handling_status_filter or row.get("handling_status") == handling_status_filter)
            ]
            rows.sort(key=lambda item: (item.get("created_at"), item["id"]), reverse=True)
            self._rows = rows[:50]
            return
        if normalized.startswith("select distinct on (order_id)"):
            order_ids = set(params[0])
            rows = [
                dict(row)
                for row in self.db.order_screening_override_audit
                if row["order_id"] in order_ids and row.get("mode") == "formal"
            ]
            rows.sort(key=lambda item: (item["order_id"], item.get("created_at"), item["id"]), reverse=True)
            latest = {}
            for row in rows:
                latest.setdefault(row["order_id"], row)
            self._rows = list(latest.values())
            return
        if normalized.startswith("update order_screening_cache"):
            reason = params[0]
            order_ids = params[1] if len(params) > 1 else list(self.db.order_screening_cache)
            updated = 0
            for order_id in order_ids:
                row = self.db.order_screening_cache.get(order_id)
                if not row or row.get("is_stale"):
                    continue
                row["is_stale"] = True
                row["stale_reason"] = reason
                updated += 1
            self._rows = []
            self.rowcount = updated
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
        self.order_screening_cache = {}
        self.order_screening_override_audit = []
        self.order_screening_action_audit = []
        self.config_change_audit = []
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
        self.next_screening_override_audit_id = 1
        self.next_screening_action_audit_id = 1
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
        self.assertEqual(db.order_screening_cache["ORD-NEW-001"]["screening_status"], "ready")
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
        self.assertEqual(db.order_screening_cache["ORD-IMP-READY"]["screening_status"], "ready")
        self.assertEqual(db.order_screening_cache["ORD-IMP-READY"]["business_bucket"], "ready")
        self.assertEqual(db.commit_count, 1)

    def test_get_order_screening_refreshes_screening_cache(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-CACHE-REFRESH"] = {
            "order_id": "ORD-CACHE-REFRESH",
            "customer_id": "STANDARD",
            "product_type": "Film-A",
            "target_width": 9999,
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

        result = orders_router.get_order_screening("ORD-CACHE-REFRESH", db=db)

        self.assertEqual(result["item"]["screening_status"], "blocked")
        self.assertEqual(db.order_screening_cache["ORD-CACHE-REFRESH"]["screening_status"], "blocked")

    def test_screening_endpoint_refreshes_cache_for_selected_orders(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-BULK-READY"] = {
            "order_id": "ORD-BULK-READY",
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
        payload = orders_router.OrderScreeningPayload(order_ids=["ORD-BULK-READY"], scope="selected")

        result = orders_router.screen_orders_endpoint(payload, db=db)

        self.assertEqual(result["items"][0]["screening_status"], "ready")
        self.assertEqual(db.order_screening_cache["ORD-BULK-READY"]["screening_status"], "ready")

    def test_screening_override_requires_reason_and_writes_audit(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-RISK-OVERRIDE"] = {
            "order_id": "ORD-RISK-OVERRIDE",
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
            "due_date": datetime(2026, 5, 17, 10, 30, tzinfo=timezone.utc),
            "material_available_time": None,
            "status": "PENDING",
            "priority_override": None,
            "created_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 5, 22, 8, 0, tzinfo=timezone.utc),
        }

        with self.assertRaises(HTTPException) as missing_reason:
            orders_router.create_order_screening_override(
                "ORD-RISK-OVERRIDE",
                orders_router.OrderScreeningOverridePayload(reason_text=" "),
                db=db,
                user=SimpleNamespace(username="planner"),
            )

        self.assertEqual(missing_reason.exception.status_code, 400)
        self.assertEqual(len(db.order_screening_override_audit), 0)

        result = orders_router.create_order_screening_override(
            "ORD-RISK-OVERRIDE",
            orders_router.OrderScreeningOverridePayload(reason_text="客户确认急单插入，接受延期风险"),
            db=db,
            user=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["order_id"], "ORD-RISK-OVERRIDE")
        self.assertEqual(result["override"]["policy"], "restricted")
        self.assertEqual(result["override_audit_id"], 1)
        self.assertEqual(len(db.order_screening_override_audit), 1)
        audit = db.order_screening_override_audit[0]
        self.assertEqual(audit["order_id"], "ORD-RISK-OVERRIDE")
        self.assertEqual(audit["screening_status"], "risk")
        self.assertEqual(audit["override_policy"], "restricted")
        self.assertEqual(audit["reason_text"], "客户确认急单插入，接受延期风险")
        self.assertEqual(audit["policy_version"], 1)
        self.assertEqual(audit["actor"], "planner")

    def test_screening_override_rejects_prohibited_machine_capability_order(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-WIDE-NO-OVERRIDE"] = {
            "order_id": "ORD-WIDE-NO-OVERRIDE",
            "customer_id": "STANDARD",
            "product_type": "Film-A",
            "target_width": 9999,
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

        with self.assertRaises(HTTPException) as ctx:
            orders_router.create_order_screening_override(
                "ORD-WIDE-NO-OVERRIDE",
                orders_router.OrderScreeningOverridePayload(reason_text="业务要求强制排入"),
                db=db,
                user=SimpleNamespace(username="planner"),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["code"], "screening_override_prohibited")
        self.assertEqual(len(db.order_screening_override_audit), 0)

    def test_screening_override_audit_can_be_listed_for_an_order(self):
        db = _FakeDb()
        db.order_screening_override_audit.append({
            "id": 12,
            "order_id": "ORD-AUDIT-LIST",
            "screening_status": "risk",
            "screening_code": "due_risk",
            "override_policy": "restricted",
            "reason_code": "SCREENING_OVERRIDE",
            "reason_text": "排程主管确认插单",
            "mode": "formal",
            "policy_version": 3,
            "actor": "planner",
            "details": {"override_decision": {"policy": "restricted"}},
            "created_at": datetime(2026, 5, 24, 8, 30, tzinfo=timezone.utc),
        })

        result = orders_router.get_order_screening_overrides(
            "ORD-AUDIT-LIST",
            db=db,
            _=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["order_id"], "ORD-AUDIT-LIST")
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["id"], 12)
        self.assertEqual(item["override_policy"], "restricted")
        self.assertEqual(item["reason_text"], "排程主管确认插单")
        self.assertEqual(item["policy_version"], 3)
        self.assertEqual(item["created_at"], "2026-05-24T08:30:00+00:00")

    def test_latest_formal_screening_overrides_are_loaded_for_preplan(self):
        db = _FakeDb()
        db.order_screening_override_audit.extend([
            {
                "id": 10,
                "order_id": "ORD-PREPLAN-OVERRIDE",
                "screening_status": "blocked",
                "screening_code": "material_not_ready",
                "override_policy": "restricted",
                "reason_code": "SCREENING_OVERRIDE",
                "reason_text": "旧原因",
                "mode": "formal",
                "policy_version": 1,
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 11,
                "order_id": "ORD-PREPLAN-OVERRIDE",
                "screening_status": "blocked",
                "screening_code": "material_not_ready",
                "override_policy": "restricted",
                "reason_code": "SCREENING_OVERRIDE",
                "reason_text": "最新正式原因",
                "mode": "formal",
                "policy_version": 2,
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
            {
                "id": 12,
                "order_id": "ORD-PREPLAN-OVERRIDE",
                "screening_status": "blocked",
                "screening_code": "material_not_ready",
                "override_policy": "restricted",
                "reason_code": "SCREENING_OVERRIDE",
                "reason_text": "实验原因",
                "mode": "experimental",
                "policy_version": 3,
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc),
            },
        ])

        result = schedule_router._load_latest_formal_screening_overrides(
            db.cursor(),
            ["ORD-PREPLAN-OVERRIDE"],
        )

        self.assertEqual(set(result), {"ORD-PREPLAN-OVERRIDE"})
        self.assertEqual(result["ORD-PREPLAN-OVERRIDE"]["id"], 11)
        self.assertEqual(result["ORD-PREPLAN-OVERRIDE"]["reason_text"], "最新正式原因")

    def test_list_orders_exposes_cached_screening_status(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-LIST-BLOCKED"] = {
            "order_id": "ORD-LIST-BLOCKED",
            "customer_id": "STANDARD",
            "product_type": "Film-A",
            "target_width": 9999,
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
        db.order_screening_cache["ORD-LIST-BLOCKED"] = {
            "screening_status": "blocked",
            "code": "no_eligible_machine",
            "root_cause": "幅宽超出机台能力",
            "result": {
                "business_bucket": "blocked_machine_capability",
                "recommendations": [
                    {
                        "action": "expand_machine_capability",
                        "label": "调整机台规格能力",
                        "href": "/config?tab=machines",
                        "category": "machine",
                        "guidance": "订单规格超出当前可用机台范围。",
                    },
                ],
                "evidence": [{"metric": "target_width", "actual": 9999}],
            },
            "is_stale": True,
            "stale_reason": "machine_capability_changed",
        }

        result = orders_router.list_orders(status="PENDING", q=None, page=1, size=50, db=db)

        self.assertEqual(result["items"][0]["screening"]["screening_status"], "blocked")
        self.assertEqual(result["items"][0]["screening"]["code"], "no_eligible_machine")
        self.assertEqual(result["items"][0]["screening"]["business_bucket"], "blocked_machine_capability")
        self.assertIs(result["items"][0]["screening"]["is_stale"], True)
        self.assertEqual(
            result["items"][0]["screening"]["stale_reason"],
            "machine_capability_changed",
        )
        self.assertEqual(
            result["items"][0]["screening"]["recommendations"][0]["action"],
            "expand_machine_capability",
        )
        self.assertEqual(
            result["items"][0]["screening"]["evidence"][0]["metric"],
            "target_width",
        )

    def test_list_orders_includes_latest_screening_override_summary(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-LIST-OVERRIDE"] = {
            "order_id": "ORD-LIST-OVERRIDE",
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
        db.order_screening_cache["ORD-LIST-OVERRIDE"] = {
            "screening_status": "risk",
            "code": "due_risk",
            "root_cause": "交期风险较高",
            "business_bucket": "risk",
            "result": {"business_bucket": "risk"},
            "is_stale": False,
        }
        db.order_screening_override_audit.extend([
            {
                "id": 20,
                "order_id": "ORD-LIST-OVERRIDE",
                "screening_status": "risk",
                "screening_code": "due_risk",
                "override_policy": "restricted",
                "reason_code": "SCREENING_OVERRIDE",
                "reason_text": "旧豁免原因",
                "mode": "formal",
                "policy_version": 1,
                "actor": "planner-a",
                "details": {"override_decision": {"policy": "restricted"}},
                "created_at": datetime(2026, 5, 24, 8, 30, tzinfo=timezone.utc),
            },
            {
                "id": 21,
                "order_id": "ORD-LIST-OVERRIDE",
                "screening_status": "risk",
                "screening_code": "due_risk",
                "override_policy": "restricted",
                "reason_code": "SCREENING_OVERRIDE",
                "reason_text": "主管确认插入本轮",
                "mode": "formal",
                "policy_version": 2,
                "actor": "planner-b",
                "details": {"override_decision": {"policy": "restricted"}},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.list_orders(status="PENDING", q=None, page=1, size=50, db=db)

        override = result["items"][0]["screening"]["latest_override"]
        self.assertEqual(override["id"], 21)
        self.assertEqual(override["reason_text"], "主管确认插入本轮")
        self.assertEqual(override["mode"], "formal")
        self.assertEqual(override["policy_version"], 2)
        self.assertEqual(override["actor"], "planner-b")
        self.assertEqual(override["created_at"], "2026-05-24T09:00:00+00:00")

    def test_screening_exception_action_writes_audit_and_updates_order_list(self):
        db = _FakeDb()
        db.products.add("Film-A")
        db.production_orders["ORD-ACTION"] = {
            "order_id": "ORD-ACTION",
            "customer_id": "STANDARD",
            "product_type": "Film-A",
            "target_width": 9999,
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
        db.order_screening_cache["ORD-ACTION"] = {
            "screening_status": "blocked",
            "code": "no_eligible_machine",
            "root_cause": "幅宽超出机台能力",
            "business_bucket": "blocked_machine_capability",
            "result": {"business_bucket": "blocked_machine_capability"},
            "is_stale": False,
        }

        result = orders_router.create_order_screening_action(
            "ORD-ACTION",
            orders_router.OrderScreeningActionPayload(
                action_type="request_data_fix",
                handling_status="in_progress",
                reason_text="目标幅宽疑似录入错误，已退回订单维护",
                assignee="order-admin",
            ),
            db=db,
            user=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["action_audit_id"], 1)
        self.assertEqual(result["latest_action"]["action_type"], "request_data_fix")
        self.assertEqual(result["latest_action"]["handling_status"], "in_progress")
        self.assertEqual(result["latest_action"]["assignee"], "order-admin")
        self.assertEqual(len(db.order_screening_action_audit), 1)
        audit = db.order_screening_action_audit[0]
        self.assertEqual(audit["order_id"], "ORD-ACTION")
        self.assertEqual(audit["business_bucket"], "blocked_machine_capability")
        self.assertEqual(audit["actor"], "planner")

        list_result = orders_router.list_orders(status="PENDING", q=None, page=1, size=50, db=db)

        latest_action = list_result["items"][0]["screening"]["latest_action"]
        self.assertEqual(latest_action["id"], 1)
        self.assertEqual(latest_action["action_type"], "request_data_fix")
        self.assertEqual(latest_action["handling_status"], "in_progress")
        self.assertEqual(latest_action["reason_text"], "目标幅宽疑似录入错误，已退回订单维护")

    def test_screening_exception_actions_can_be_listed_for_an_order(self):
        db = _FakeDb()
        db.order_screening_action_audit.extend([
            {
                "id": 30,
                "order_id": "ORD-ACTION-HISTORY",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "先退回订单维护",
                "assignee": "order-admin",
                "actor": "planner-a",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 31,
                "order_id": "ORD-ACTION-HISTORY",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "mark_resolved",
                "handling_status": "resolved",
                "reason_text": "订单宽度已修正",
                "assignee": "order-admin",
                "actor": "planner-b",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.get_order_screening_actions(
            "ORD-ACTION-HISTORY",
            db=db,
            _=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["order_id"], "ORD-ACTION-HISTORY")
        self.assertEqual([item["id"] for item in result["items"]], [31, 30])
        self.assertEqual(result["items"][0]["handling_status"], "resolved")
        self.assertEqual(result["items"][0]["reason_text"], "订单宽度已修正")
        self.assertEqual(result["items"][1]["actor"], "planner-a")

    def test_screening_exception_actions_can_be_filtered_by_status(self):
        db = _FakeDb()
        db.order_screening_action_audit.extend([
            {
                "id": 40,
                "order_id": "ORD-ACTION-FILTER",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "处理中",
                "assignee": "order-admin",
                "actor": "planner-a",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 41,
                "order_id": "ORD-ACTION-FILTER",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "mark_resolved",
                "handling_status": "resolved",
                "reason_text": "已处理",
                "assignee": "order-admin",
                "actor": "planner-b",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.get_order_screening_actions(
            "ORD-ACTION-FILTER",
            handling_status="resolved",
            db=db,
            _=SimpleNamespace(username="planner"),
        )

        self.assertEqual([item["id"] for item in result["items"]], [41])
        self.assertEqual(result["items"][0]["handling_status"], "resolved")

    def test_screening_action_options_are_exposed_for_ui_configuration(self):
        db = _FakeDb()
        db.order_screening_action_audit.extend([
            {
                "id": 61,
                "order_id": "ORD-A",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "退回订单数据修正",
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 62,
                "order_id": "ORD-B",
                "screening_status": "blocked",
                "business_bucket": "blocked_material",
                "screening_code": "material_not_ready",
                "action_type": "confirm_material",
                "handling_status": "waiting_external",
                "reason_text": "确认替代物料",
                "assignee": "material-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
            {
                "id": 63,
                "order_id": "ORD-C",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "open",
                "reason_text": "重复负责人带空白",
                "assignee": " order-admin ",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.get_order_screening_action_options(
            db=db,
            _=SimpleNamespace(username="planner"),
        )

        action_values = [item["value"] for item in result["action_types"]]
        status_values = [item["value"] for item in result["handling_statuses"]]
        assignee_values = [item["value"] for item in result["assignee_filters"]]
        self.assertIn("request_data_fix", action_values)
        self.assertIn("mark_resolved", action_values)
        self.assertIn("unhandled", status_values)
        self.assertIn("in_progress", status_values)
        self.assertIn("resolved", status_values)
        self.assertEqual(assignee_values, ["unassigned", "material-admin", "order-admin"])
        self.assertEqual(
            next(item for item in result["handling_statuses"] if item["value"] == "unhandled")["label"],
            "未处理",
        )
        self.assertEqual(
            next(item for item in result["assignee_filters"] if item["value"] == "unassigned")["label"],
            "未分配",
        )
        self.assertEqual(
            next(item for item in result["action_types"] if item["value"] == "request_data_fix")["label"],
            "退回订单数据修正",
        )
        self.assertEqual(
            next(item for item in result["handling_statuses"] if item["value"] == "waiting_external")["label"],
            "等待外部确认",
        )

    def test_list_orders_filters_by_latest_screening_action_status(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-ACTION-OPEN", "ORD-ACTION-DONE", "ORD-ACTION-UNHANDLED"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.extend([
            {
                "id": 1,
                "order_id": "ORD-ACTION-OPEN",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "处理中",
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 2,
                "order_id": "ORD-ACTION-DONE",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "mark_resolved",
                "handling_status": "resolved",
                "reason_text": "已处理",
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.list_orders(
            status="PENDING",
            screening_action_status="in_progress",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["order_id"] for item in result["items"]], ["ORD-ACTION-OPEN"])
        self.assertEqual(result["items"][0]["screening"]["latest_action"]["handling_status"], "in_progress")

    def test_list_orders_filters_by_latest_screening_action_type(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-FIX-DATA", "ORD-CONFIRM-MATERIAL"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.extend([
            {
                "id": 11,
                "order_id": "ORD-FIX-DATA",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "退回订单数据修正",
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 12,
                "order_id": "ORD-CONFIRM-MATERIAL",
                "screening_status": "blocked",
                "business_bucket": "blocked_material",
                "screening_code": "material_not_ready",
                "action_type": "confirm_material",
                "handling_status": "in_progress",
                "reason_text": "确认替代物料",
                "assignee": "material-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.list_orders(
            status="PENDING",
            screening_action_type="request_data_fix",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["order_id"] for item in result["items"]], ["ORD-FIX-DATA"])
        self.assertEqual(result["items"][0]["screening"]["latest_action"]["action_type"], "request_data_fix")

    def test_list_orders_filters_by_latest_screening_action_assignee(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-ORDER-ADMIN", "ORD-MATERIAL-ADMIN"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.extend([
            {
                "id": 31,
                "order_id": "ORD-ORDER-ADMIN",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "退回订单数据修正",
                "assignee": " order-admin ",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 32,
                "order_id": "ORD-MATERIAL-ADMIN",
                "screening_status": "blocked",
                "business_bucket": "blocked_material",
                "screening_code": "material_not_ready",
                "action_type": "confirm_material",
                "handling_status": "in_progress",
                "reason_text": "确认替代物料",
                "assignee": "material-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.list_orders(
            status="PENDING",
            screening_action_assignee="order-admin",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["order_id"] for item in result["items"]], ["ORD-ORDER-ADMIN"])
        self.assertEqual(result["items"][0]["screening"]["latest_action"]["assignee"], " order-admin ")

    def test_list_orders_filters_unassigned_screening_action_assignee(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-UNASSIGNED", "ORD-ASSIGNED"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.append({
            "id": 51,
            "order_id": "ORD-ASSIGNED",
            "screening_status": "blocked",
            "business_bucket": "blocked_machine_capability",
            "screening_code": "no_eligible_machine",
            "action_type": "request_data_fix",
            "handling_status": "in_progress",
            "reason_text": "退回订单数据修正",
            "assignee": "order-admin",
            "actor": "planner",
            "details": {},
            "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
        })

        result = orders_router.list_orders(
            status="PENDING",
            screening_status="blocked",
            screening_action_assignee="unassigned",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["order_id"] for item in result["items"]], ["ORD-UNASSIGNED"])
        self.assertIsNone(result["items"][0]["screening"]["latest_action"])

    def test_list_orders_filters_unhandled_screening_exceptions(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-UNHANDLED", "ORD-HANDLED"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.append({
            "id": 3,
            "order_id": "ORD-HANDLED",
            "screening_status": "blocked",
            "business_bucket": "blocked_machine_capability",
            "screening_code": "no_eligible_machine",
            "action_type": "request_data_fix",
            "handling_status": "in_progress",
            "reason_text": "已进入处理",
            "assignee": "order-admin",
            "actor": "planner",
            "details": {},
            "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
        })

        result = orders_router.list_orders(
            status="PENDING",
            screening_status="blocked",
            screening_action_status="unhandled",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["order_id"] for item in result["items"]], ["ORD-UNHANDLED"])
        self.assertIsNone(result["items"][0]["screening"]["latest_action"])

    def test_list_orders_summarizes_latest_screening_action_statuses(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-UNHANDLED", "ORD-INPROGRESS", "ORD-WAITING", "ORD-RESOLVED"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        for index, (order_id, status) in enumerate([
            ("ORD-INPROGRESS", "in_progress"),
            ("ORD-WAITING", "waiting_external"),
            ("ORD-RESOLVED", "resolved"),
        ], start=1):
            db.order_screening_action_audit.append({
                "id": index,
                "order_id": order_id,
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": status,
                "reason_text": status,
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, index, tzinfo=timezone.utc),
            })

        result = orders_router.list_orders(
            status="PENDING",
            screening_status="blocked",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["screening_action_status_counts"], {
            "unhandled": 1,
            "open": 0,
            "in_progress": 1,
            "waiting_external": 1,
            "resolved": 1,
        })

    def test_list_orders_summarizes_latest_screening_action_types(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-NO-ACTION", "ORD-FIX-DATA", "ORD-MATERIAL"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.extend([
            {
                "id": 21,
                "order_id": "ORD-FIX-DATA",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "退回数据修正",
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 22,
                "order_id": "ORD-MATERIAL",
                "screening_status": "blocked",
                "business_bucket": "blocked_material",
                "screening_code": "material_not_ready",
                "action_type": "confirm_material",
                "handling_status": "waiting_external",
                "reason_text": "确认替代物料",
                "assignee": "material-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.list_orders(
            status="PENDING",
            screening_status="blocked",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["screening_action_type_counts"]["unhandled"], 1)
        self.assertEqual(result["screening_action_type_counts"]["request_data_fix"], 1)
        self.assertEqual(result["screening_action_type_counts"]["confirm_material"], 1)
        self.assertEqual(result["screening_action_type_counts"]["mark_resolved"], 0)

    def test_list_orders_summarizes_latest_screening_action_assignees(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id in ["ORD-UNASSIGNED", "ORD-ORDER-ADMIN", "ORD-MATERIAL-ADMIN"]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": 9999,
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
            db.order_screening_cache[order_id] = {
                "screening_status": "blocked",
                "code": "no_eligible_machine",
                "root_cause": "幅宽超出机台能力",
                "business_bucket": "blocked_machine_capability",
                "result": {"business_bucket": "blocked_machine_capability"},
                "is_stale": False,
            }
        db.order_screening_action_audit.extend([
            {
                "id": 41,
                "order_id": "ORD-ORDER-ADMIN",
                "screening_status": "blocked",
                "business_bucket": "blocked_machine_capability",
                "screening_code": "no_eligible_machine",
                "action_type": "request_data_fix",
                "handling_status": "in_progress",
                "reason_text": "退回数据修正",
                "assignee": "order-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 8, 0, tzinfo=timezone.utc),
            },
            {
                "id": 42,
                "order_id": "ORD-MATERIAL-ADMIN",
                "screening_status": "blocked",
                "business_bucket": "blocked_material",
                "screening_code": "material_not_ready",
                "action_type": "confirm_material",
                "handling_status": "waiting_external",
                "reason_text": "确认替代物料",
                "assignee": "material-admin",
                "actor": "planner",
                "details": {},
                "created_at": datetime(2026, 5, 24, 9, 0, tzinfo=timezone.utc),
            },
        ])

        result = orders_router.list_orders(
            status="PENDING",
            screening_status="blocked",
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["screening_action_assignee_counts"], {
            "unassigned": 1,
            "order-admin": 1,
            "material-admin": 1,
        })

    def test_list_orders_filters_by_screening_status_bucket_and_stale_flag(self):
        db = _FakeDb()
        db.products.add("Film-A")
        for order_id, width in [("ORD-LIST-READY", 500), ("ORD-LIST-BLOCKED", 9999)]:
            db.production_orders[order_id] = {
                "order_id": order_id,
                "customer_id": "STANDARD",
                "product_type": "Film-A",
                "target_width": width,
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
        db.order_screening_cache["ORD-LIST-READY"] = {
            "screening_status": "ready",
            "result": {"business_bucket": "ready"},
            "is_stale": False,
        }
        db.order_screening_cache["ORD-LIST-BLOCKED"] = {
            "screening_status": "blocked",
            "code": "no_eligible_machine",
            "root_cause": "幅宽超出机台能力",
            "result": {"business_bucket": "blocked_machine_capability"},
            "is_stale": True,
            "stale_reason": "machine_capability_changed",
        }

        result = orders_router.list_orders(
            status="PENDING",
            screening_status="blocked",
            screening_bucket="blocked_machine_capability",
            screening_stale=True,
            q=None,
            page=1,
            size=50,
            db=db,
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["order_id"] for item in result["items"]], ["ORD-LIST-BLOCKED"])
        self.assertIs(result["items"][0]["screening"]["is_stale"], True)

    def test_ensure_screening_schema_backfills_business_bucket_from_cached_result(self):
        db = _FakeDb()
        db.order_screening_cache["ORD-OLD-CACHE"] = {
            "screening_status": "blocked",
            "result": {"business_bucket": "blocked_machine_capability"},
            "is_stale": False,
        }

        orders_router._ensure_order_screening_schema(db)

        self.assertEqual(
            db.order_screening_cache["ORD-OLD-CACHE"]["business_bucket"],
            "blocked_machine_capability",
        )

    def test_mark_order_screening_cache_stale_marks_requested_orders(self):
        db = _FakeDb()
        db.order_screening_cache["ORD-STALE-1"] = {"screening_status": "ready", "is_stale": False}
        db.order_screening_cache["ORD-FRESH"] = {"screening_status": "ready", "is_stale": False}

        updated = orders_router._mark_order_screening_cache_stale(
            db.cursor(),
            order_ids=["ORD-STALE-1"],
            reason="machine_capability_changed",
        )

        self.assertEqual(updated, 1)
        self.assertIs(db.order_screening_cache["ORD-STALE-1"]["is_stale"], True)
        self.assertEqual(
            db.order_screening_cache["ORD-STALE-1"]["stale_reason"],
            "machine_capability_changed",
        )
        self.assertIs(db.order_screening_cache["ORD-FRESH"]["is_stale"], False)

    def test_policy_update_marks_screening_cache_stale(self):
        db = _FakeDb()
        db.order_screening_cache["ORD-POLICY-STALE"] = {
            "screening_status": "ready",
            "is_stale": False,
        }
        payload = schedule_router.ScheduleSettingsPayload(
            material_constraint_enabled=False,
            change_reason="policy change affects order screening",
        )

        result = schedule_router.update_schedule_settings(
            payload,
            db=db,
            _=SimpleNamespace(username="planner"),
        )

        self.assertEqual(result["policy_version"], 2)
        self.assertIs(db.order_screening_cache["ORD-POLICY-STALE"]["is_stale"], True)
        self.assertEqual(
            db.order_screening_cache["ORD-POLICY-STALE"]["stale_reason"],
            "schedule_policy_changed",
        )
        self.assertEqual(len(db.config_change_audit), 1)

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
        self.assertEqual(result["screening"]["screening_status"], "ready")
        self.assertEqual(db.order_screening_cache["ORD-REV-001"]["screening_status"], "ready")
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
