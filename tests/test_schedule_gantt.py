import unittest
from datetime import datetime, timezone

from api.routers.schedule import _build_idle_windows, _decode_child_output, _task_busy_end, _task_busy_start


def dt(hour):
    return datetime(2026, 5, 19, hour, 0, tzinfo=timezone.utc)


class TestScheduleGanttHelpers(unittest.TestCase):
    def test_idle_windows_cover_unused_machine_and_known_gaps(self):
        tasks = [{
            "machine_id": "LINE-01",
            "order_id": "ORD-001",
            "setup_start_time": None,
            "start_time": dt(9),
            "end_time": dt(10),
        }]
        maintenance = [{
            "machine_id": "LINE-01",
            "start": dt(12),
            "end": dt(13),
            "reason": "GMP cleaning",
        }]

        idle = _build_idle_windows(
            ["LINE-01", "LINE-02"],
            dt(8),
            dt(14),
            tasks,
            maintenance,
            [],
        )

        line_01 = [item for item in idle if item["machine_id"] == "LINE-01"]
        line_02 = [item for item in idle if item["machine_id"] == "LINE-02"]

        self.assertEqual([item["duration_mins"] for item in line_01], [60, 120, 60])
        self.assertEqual(line_01[1]["reason"], "Idle before maintenance window")
        self.assertEqual(line_01[1]["code"], "idle.before_maintenance")
        self.assertEqual(line_01[1]["confidence"], "proven")
        self.assertIn("diagnostic", line_01[1])
        self.assertEqual(
            line_01[1]["diagnostic"]["recommendations"][0]["href"],
            "/config?tab=rules&section=maintenance",
        )
        self.assertEqual(len(line_02), 1)
        self.assertEqual(line_02[0]["duration_mins"], 360)
        self.assertEqual(line_02[0]["reason"], "No scheduled work in active run")
        self.assertEqual(line_02[0]["code"], "idle.no_ready_eligible_order")

    def test_idle_windows_explain_no_hard_fit_orders(self):
        idle = _build_idle_windows(
            ["LINE-03"],
            dt(8),
            dt(14),
            [],
            [],
            [],
            order_context={
                "machines": {
                    "LINE-03": {
                        "machine_id": "LINE-03",
                        "status": "ACTIVE",
                        "cleanroom_level": "Class_10K",
                        "layer_structure": 5,
                        "min_width": 200,
                        "max_width": 400,
                        "min_thickness": 20,
                        "max_thickness": 80,
                        "hourly_output_kg": 120,
                    },
                },
                "orders": [{
                    "order_id": "ORD-WIDE",
                    "target_width": 900,
                    "target_thickness": 40,
                    "total_quantity_kg": 60,
                    "cleanroom_req": "Class_10K",
                    "material_available_time": dt(8),
                    "layer_count": 5,
                    "assigned_machine": None,
                }],
            },
        )

        self.assertEqual(idle[0]["code"], "idle.no_hard_fit_order")
        self.assertEqual(idle[0]["confidence"], "proven")
        self.assertIn("幅宽", idle[0]["diagnostic"]["root_cause"])

    def test_idle_windows_explain_orders_assigned_elsewhere(self):
        tasks = [{
            "machine_id": "LINE-01",
            "order_id": "ORD-001",
            "setup_start_time": None,
            "start_time": dt(9),
            "end_time": dt(10),
        }]
        idle = _build_idle_windows(
            ["LINE-01"],
            dt(8),
            dt(14),
            tasks,
            [],
            [],
            order_context={
                "machines": {
                    "LINE-01": {
                        "machine_id": "LINE-01",
                        "status": "ACTIVE",
                        "cleanroom_level": "Class_10K",
                        "layer_structure": 5,
                        "min_width": 200,
                        "max_width": 900,
                        "min_thickness": 20,
                        "max_thickness": 80,
                        "hourly_output_kg": 120,
                    },
                },
                "orders": [{
                    "order_id": "ORD-READY",
                    "target_width": 500,
                    "target_thickness": 40,
                    "total_quantity_kg": 60,
                    "cleanroom_req": "Class_10K",
                    "material_available_time": dt(8),
                    "layer_count": 5,
                    "assigned_machine": "LINE-02",
                    "assigned_start": dt(11),
                    "duration_mins": 30,
                }],
            },
        )

        last_gap = idle[-1]
        self.assertEqual(last_gap["code"], "idle.assigned_elsewhere")
        self.assertIn("ORD-READY", last_gap["diagnostic"]["root_cause"])
        self.assertIn("LINE-02", last_gap["diagnostic"]["root_cause"])

    def test_child_output_decoder_preserves_chinese_error_text(self):
        message = "订单 ORD-062 无可用机台"

        self.assertEqual(_decode_child_output(message.encode("utf-8")), message)
        self.assertEqual(_decode_child_output(message.encode("gbk")), message)

    def test_task_busy_window_uses_setup_start_when_available(self):
        task = {
            "setup_start_time": dt(8),
            "start_time": dt(9),
            "end_time": dt(10),
        }

        self.assertEqual(_task_busy_start(task), dt(8))
        self.assertEqual(_task_busy_end(task), dt(10))

    def test_task_busy_window_falls_back_to_production_start(self):
        task = {
            "setup_start_time": None,
            "start_time": dt(9),
            "end_time": dt(10),
        }

        self.assertEqual(_task_busy_start(task), dt(9))


if __name__ == "__main__":
    unittest.main()
