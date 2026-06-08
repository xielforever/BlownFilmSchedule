"""
HTTP contract tests for preplan order buckets.

These tests require a running API server and prepared database, so they are
gated by APS_RUN_HTTP_TESTS=1.
"""

import os
import unittest

import requests


@unittest.skipUnless(
    os.getenv("APS_RUN_HTTP_TESTS") == "1",
    "set APS_RUN_HTTP_TESTS=1 and start uvicorn api.main:app to run HTTP tests",
)
class TestPreplanDetailContract(unittest.TestCase):
    base_url = os.getenv("APS_API_BASE_URL", "http://localhost:8000")

    @classmethod
    def setUpClass(cls):
        response = requests.post(
            f"{cls.base_url}/api/auth/login",
            data={"username": "admin", "password": "admin123"},
            timeout=10,
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        cls.headers = {"Authorization": f"Bearer {token}"}

    def setUp(self):
        self.created_run_ids = []

    def tearDown(self):
        for run_id in self.created_run_ids:
            requests.post(
                f"{self.base_url}/api/schedule/preplans/{run_id}/cancel",
                headers=self.headers,
                json={"reason": "HTTP contract test cleanup"},
                timeout=10,
            )

    def _pending_order_ids(self, limit=12):
        response = requests.post(
            f"{self.base_url}/api/orders/screening",
            headers=self.headers,
            json={"scope": "pending"},
            timeout=10,
        )
        response.raise_for_status()
        schedulable = [
            item["order_id"]
            for item in response.json().get("items", [])
            if item.get("screening_status") in {"ready", "risk"}
        ]
        return schedulable[:limit]

    def test_preplan_detail_returns_authoritative_order_buckets(self):
        settings = requests.get(
            f"{self.base_url}/api/schedule/settings",
            headers=self.headers,
            timeout=10,
        )
        settings.raise_for_status()
        original_settings = settings.json()
        self.addCleanup(
            lambda: requests.patch(
                f"{self.base_url}/api/schedule/settings",
                headers=self.headers,
                json={
                    "review_required": original_settings["review_required"],
                    "auto_release_enabled": original_settings["auto_release_enabled"],
                    "change_reason": "HTTP contract restore",
                },
                timeout=10,
            )
        )
        settings_response = requests.patch(
            f"{self.base_url}/api/schedule/settings",
            headers=self.headers,
            json={
                "review_required": True,
                "auto_release_enabled": False,
                "change_reason": "HTTP contract setup",
            },
            timeout=10,
        )
        settings_response.raise_for_status()

        order_ids = self._pending_order_ids()
        if not order_ids:
            self.skipTest("no pending orders available for HTTP preplan contract test")

        created = requests.post(
            f"{self.base_url}/api/schedule/preplans",
            headers=self.headers,
            json={"order_ids": order_ids, "mode": "AUTO"},
            timeout=60,
        )
        created.raise_for_status()
        run_id = created.json()["run"]["run_id"]
        self.created_run_ids.append(run_id)

        detail_response = requests.get(
            f"{self.base_url}/api/schedule/preplans/{run_id}",
            headers=self.headers,
            timeout=20,
        )
        detail_response.raise_for_status()
        detail = detail_response.json()

        for key in (
            "input_orders",
            "scheduled_orders",
            "schedulable_orders",
            "unplaced_schedulable_orders",
            "blocked_orders",
            "late_orders",
        ):
            self.assertIn(key, detail)
            self.assertIsInstance(detail[key], list)

        self.assertEqual(
            len(detail["input_orders"]),
            len(detail["scheduled_orders"])
            + len(detail["unplaced_schedulable_orders"])
            + len(detail["blocked_orders"]),
        )

        row_fields = {
            "order_id",
            "product_type",
            "target_width",
            "target_thickness",
            "total_quantity_kg",
            "order_class",
            "cleanroom_req",
            "due_date",
            "status",
            "bucket_reason",
        }
        for row in detail["input_orders"]:
            self.assertTrue(row_fields.issubset(row.keys()))

        for row in detail["schedulable_orders"]:
            self.assertIn("eligible_machine_count", row)

        for row in detail["blocked_orders"]:
            self.assertTrue(row.get("root_cause") or row.get("bucket_reason"))


if __name__ == "__main__":
    unittest.main()
