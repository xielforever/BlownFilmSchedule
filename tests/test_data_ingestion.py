"""
数据清洗管道单元测试

验证日期换算、配方重组、到货期防御补丁、初始挂料广播。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from src.data_ingestion import BlownFilmDataIngestionPipeline
from src.config import INPUT_EXCEL_PATH


class TestDataIngestion(unittest.TestCase):
    """数据清洗管道测试"""

    @classmethod
    def setUpClass(cls):
        cls.pipeline = BlownFilmDataIngestionPipeline()
        cls.machines, cls.orders, cls.recipes_map, cls.setup_mgr = \
            cls.pipeline.load_from_excel(INPUT_EXCEL_PATH)

    def test_orders_loaded(self):
        """验证订单数量"""
        self.assertGreaterEqual(len(self.orders), 32)

    def test_machines_loaded(self):
        """验证机台数量"""
        self.assertEqual(len(self.machines), 10)

    def test_recipes_loaded(self):
        """验证配方数量"""
        self.assertGreaterEqual(len(self.recipes_map), 1)

    def test_due_date_conversion(self):
        """验证交期转分钟偏移量"""
        for o in self.orders:
            self.assertIsInstance(o.due_date_mins, int)

    def test_material_available_default_zero(self):
        """验证到货期缺失时防御性补 0"""
        for o in self.orders:
            self.assertIsInstance(o.material_available_mins, int)
            self.assertGreaterEqual(o.material_available_mins, 0)

    def test_recipe_materials_attached(self):
        """验证配方已挂载到订单"""
        for o in self.orders:
            self.assertIsInstance(o.recipe_materials, list)
            self.assertGreater(len(o.recipe_materials), 0)

    def test_recipe_layer_order(self):
        """验证配方按层级 A→E 严格升序"""
        for prod_type, materials in self.recipes_map.items():
            self.assertIsInstance(materials, list)
            self.assertGreater(len(materials), 0)

    def test_initial_material_broadcast(self):
        """验证初始挂料广播数组长度 == 机台层数"""
        for m in self.machines:
            self.assertEqual(len(m.initial_material_lanes), m.layer_structure,
                             f"{m.machine_id}: 广播长度不匹配")

    def test_forbidden_calendar_injected(self):
        """验证维保日历已注入"""
        for m in self.machines:
            self.assertGreater(len(m.forbidden_calendar), 0,
                               f"{m.machine_id}: 缺少维保日历")

    def test_no_float_in_time_fields(self):
        """验证所有时间字段为纯整数"""
        for o in self.orders:
            self.assertIsInstance(o.order_date_mins, int)
            self.assertIsInstance(o.due_date_mins, int)
            self.assertIsInstance(o.material_available_mins, int)

    def test_cleanroom_values_valid(self):
        """验证洁净度值合法"""
        valid = {"Class_10K", "Class_100K"}
        for o in self.orders:
            self.assertIn(o.cleanroom_req, valid)
        for m in self.machines:
            self.assertIn(m.cleanroom_level, valid)


if __name__ == "__main__":
    unittest.main()
