import unittest

from scripts.seed_demo import build_demo_inputs, run_demo_schedule


class TestDemoSeedScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (
            cls.result,
            cls.machines,
            cls.feasible_orders,
            cls.blocked_order,
            cls.recipes_map,
            cls.setup_mgr,
        ) = run_demo_schedule()

    def test_demo_schedule_is_feasible_and_small(self):
        self.assertIn(self.result.status, {"OPTIMAL", "FEASIBLE"})
        self.assertEqual(self.result.validation_errors, [])
        self.assertEqual(len(self.result.tasks), len(self.feasible_orders))
        self.assertLessEqual(len(self.feasible_orders), 12)

    def test_demo_contains_explainable_cases(self):
        self.assertTrue(any(task.setup_time > 0 for task in self.result.tasks))
        self.assertTrue(any(task.end_mins > task.order.due_date_mins for task in self.result.tasks))
        self.assertTrue(any(order.material_available_mins > 0 for order in self.feasible_orders))
        self.assertTrue(any(machine.forbidden_calendar for machine in self.machines))

    def test_demo_blocked_order_is_intentionally_infeasible(self):
        eligible = [machine.machine_id for machine in self.machines if machine.can_produce(self.blocked_order)]
        self.assertEqual(eligible, [])

    def test_demo_fourth_machine_is_available_for_idle_row(self):
        machine_ids_with_tasks = {task.machine.machine_id for task in self.result.tasks}
        self.assertIn("DEMO-LINE-04", {machine.machine_id for machine in self.machines})
        self.assertNotIn("DEMO-LINE-04", machine_ids_with_tasks)

    def test_demo_data_build_is_import_safe(self):
        machines, orders, blocked_order, recipes_map, setup_mgr = build_demo_inputs()
        self.assertEqual(len(machines), 4)
        self.assertEqual(len(orders), len(self.feasible_orders))
        self.assertEqual(blocked_order.order_id, "DEMO-BLOCKED")
        self.assertIn("DEMO-MED-5L", recipes_map)
        self.assertGreater(len(setup_mgr.material_switch_matrix), 0)


if __name__ == "__main__":
    unittest.main()
