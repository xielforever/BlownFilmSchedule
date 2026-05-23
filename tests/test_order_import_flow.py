import unittest

from fastapi import HTTPException

from api.routers import orders as orders_router


class TestOrderImportPreview(unittest.TestCase):
    def test_preview_classifies_new_conflict_duplicate_and_rejected_rows(self):
        rows = [
            {
                "order_id": "ORD-IMP-001",
                "product_type": "Film-A",
                "target_width": "520",
                "target_thickness": "35",
                "total_quantity_kg": "1200",
                "cleanroom_req": "Class_10K",
                "order_class": "NORMAL",
                "due_date": "2026-05-28T08:30:00+08:00",
            },
            {
                "order_id": "ORD-EXIST-001",
                "product_type": "Film-A",
                "target_width": "520",
                "target_thickness": "35",
                "total_quantity_kg": "1200",
                "cleanroom_req": "Class_10K",
                "order_class": "NORMAL",
                "due_date": "2026-05-28T08:30:00+08:00",
            },
            {
                "order_id": "ORD-IMP-001",
                "product_type": "Film-A",
                "target_width": "520",
                "target_thickness": "35",
                "total_quantity_kg": "1200",
                "cleanroom_req": "Class_10K",
                "order_class": "NORMAL",
                "due_date": "2026-05-28T08:30:00+08:00",
            },
            {
                "order_id": "ORD-BAD-001",
                "product_type": "Missing-Film",
                "target_width": "520",
                "target_thickness": "",
                "total_quantity_kg": "1200",
                "cleanroom_req": "Class_10K",
                "order_class": "NORMAL",
                "due_date": "bad-date",
            },
        ]

        preview = orders_router._preview_import_rows(
            rows,
            existing_order_ids={"ORD-EXIST-001"},
            product_types={"Film-A"},
        )

        self.assertEqual(preview["summary"]["new_count"], 1)
        self.assertEqual(preview["summary"]["conflict_count"], 1)
        self.assertEqual(preview["summary"]["duplicate_input_count"], 1)
        self.assertEqual(preview["summary"]["rejected_count"], 1)
        statuses = [row["row_status"] for row in preview["rows"]]
        self.assertEqual(statuses, ["new", "conflict", "duplicate_input", "rejected"])
        self.assertEqual(preview["rows"][0]["normalized_order"]["status"], "PENDING")
        self.assertTrue(preview["rows"][1]["errors"])
        self.assertTrue(preview["rows"][3]["errors"])

    def test_commit_payload_uses_only_preview_accepted_rows(self):
        preview = orders_router._preview_import_rows(
            [
                {
                    "order_id": "ORD-IMP-001",
                    "product_type": "Film-A",
                    "target_width": "520",
                    "target_thickness": "35",
                    "total_quantity_kg": "1200",
                    "cleanroom_req": "Class_10K",
                    "order_class": "NORMAL",
                    "due_date": "2026-05-28T08:30:00+08:00",
                },
                {
                    "order_id": "ORD-IMP-002",
                    "product_type": "Missing-Film",
                    "target_width": "520",
                    "target_thickness": "35",
                    "total_quantity_kg": "1200",
                    "cleanroom_req": "Class_10K",
                    "order_class": "NORMAL",
                    "due_date": "2026-05-28T08:30:00+08:00",
                },
            ],
            existing_order_ids=set(),
            product_types={"Film-A"},
        )

        accepted = orders_router._accepted_import_orders(preview["rows"])

        self.assertEqual([row["order_id"] for row in accepted], ["ORD-IMP-001"])

    def test_commit_requires_at_least_one_accepted_row(self):
        preview = orders_router._preview_import_rows(
            [
                {
                    "order_id": "ORD-EXIST-001",
                    "product_type": "Film-A",
                    "target_width": "520",
                    "target_thickness": "35",
                    "total_quantity_kg": "1200",
                    "cleanroom_req": "Class_10K",
                    "order_class": "NORMAL",
                    "due_date": "2026-05-28T08:30:00+08:00",
                },
            ],
            existing_order_ids={"ORD-EXIST-001"},
            product_types={"Film-A"},
        )

        with self.assertRaises(HTTPException) as ctx:
            orders_router._ensure_import_has_accepted_rows(preview["rows"])

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("没有可提交", str(ctx.exception.detail))

    def test_preview_keeps_numeric_strings_and_normalizes_cleanroom_no(self):
        preview = orders_router._preview_import_rows(
            [
                {
                    "order_id": "ORD-NO-001",
                    "product_type": "Film-A",
                    "target_width": "100",
                    "target_thickness": "20",
                    "total_quantity_kg": "1000",
                    "cleanroom_req": "NO",
                    "order_class": "NORMAL",
                    "corona_req": "YES",
                    "due_date": "2026-05-28T08:30:00+08:00",
                },
            ],
            existing_order_ids=set(),
            product_types={"Film-A"},
        )

        order = preview["rows"][0]["normalized_order"]
        self.assertEqual(preview["rows"][0]["row_status"], "new")
        self.assertEqual(order["target_width"], 100)
        self.assertEqual(order["cleanroom_req"], "Class_100K")
        self.assertIs(order["corona_req"], True)


if __name__ == "__main__":
    unittest.main()
