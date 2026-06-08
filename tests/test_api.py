"""
HTTP API smoke tests.

These tests intentionally run only when APS_RUN_HTTP_TESTS=1 is set because
they require a live FastAPI server and a prepared PostgreSQL database.
"""

import os
import unittest

import requests


@unittest.skipUnless(
    os.getenv("APS_RUN_HTTP_TESTS") == "1",
    "set APS_RUN_HTTP_TESTS=1 and start uvicorn api.main:app to run HTTP tests",
)
class TestHttpApiSmoke(unittest.TestCase):
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

    def test_dashboard_summary(self):
        response = requests.get(
            f"{self.base_url}/api/dashboard/summary",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertIn("total_orders", data)
        self.assertIn("on_time_rate", data)

    def test_gantt_contract(self):
        response = requests.get(
            f"{self.base_url}/api/schedule/gantt",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertIn("tasks", data)
        self.assertIn("maintenance", data)
        self.assertIn("downtime", data)
        self.assertIn("idle", data)
        self.assertIn("machines", data)
        self.assertIn("horizon", data)
        self.assertIsInstance(data["machines"], list)
        self.assertIsInstance(data["idle"], list)
        if data["tasks"]:
            task_machines = {item["machine_id"] for item in data["tasks"]}
            configured_machines = {item["machine_id"] for item in data["machines"]}
            self.assertTrue(task_machines.issubset(configured_machines))
        if data["idle"]:
            self.assertIn("duration_mins", data["idle"][0])
            self.assertIn("reason", data["idle"][0])

    def test_schedule_status_contract(self):
        response = requests.get(
            f"{self.base_url}/api/schedule/status",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertIn("state", data)
        self.assertIn("active_run_id", data)
        if data.get("state") == "failed" and data.get("active_run_id"):
            summary = requests.get(
                f"{self.base_url}/api/dashboard/summary",
                headers=self.headers,
                timeout=10,
            )
            summary.raise_for_status()
            self.assertEqual(summary.json().get("run_id"), data["active_run_id"])

    def test_schedule_diagnostics_contract(self):
        response = requests.get(
            f"{self.base_url}/api/schedule/diagnostics",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertIn("diagnostics", data)
        self.assertIn("counts", data)
        self.assertIsInstance(data["diagnostics"], list)

    def test_runs_contract(self):
        response = requests.get(
            f"{self.base_url}/api/schedule/runs",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertIsInstance(data, list)
        if data:
            self.assertIn("triggered_by", data[0])

    def test_orders_contract(self):
        response = requests.get(
            f"{self.base_url}/api/orders",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertIn("items", data)
        self.assertIn("total", data)

    def test_machines_contract(self):
        response = requests.get(
            f"{self.base_url}/api/machines",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        self.assertIsInstance(response.json(), list)

    def test_order_what_if_contract(self):
        orders = requests.get(
            f"{self.base_url}/api/orders",
            headers=self.headers,
            params={"page": 1, "size": 1},
            timeout=10,
        )
        orders.raise_for_status()
        items = orders.json().get("items", [])
        if not items:
            self.skipTest("no orders available for what-if contract test")

        order_id = items[0]["order_id"]
        response = requests.post(
            f"{self.base_url}/api/schedule/what-if/order",
            headers=self.headers,
            json={
                "order_id": order_id,
                "changes": {"target_width": 99999},
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        self.assertFalse(data["persistent"])
        self.assertEqual(data["mode"], "order_screening")
        self.assertEqual(data["order_id"], order_id)
        self.assertIn("current", data)
        self.assertIn("what_if", data)
        self.assertIn("impact", data)
        self.assertIn("target_width", data["changed_fields"])
        self.assertEqual(data["what_if"]["screening_status"], "blocked")


if __name__ == "__main__":
    unittest.main()
