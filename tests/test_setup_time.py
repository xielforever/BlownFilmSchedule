"""
换产耗时精算单元测试

覆盖材质切换（并发 Max）、幅宽方向性阶梯、GMP 清场等核心场景。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from src.models import ProductionOrderModel, BlownFilmMachineModel
from src.setup_matrices import SetupMatricesManager
from src.scheduler import SetupCalculator


def _make_order(**kwargs) -> ProductionOrderModel:
    """快速构造测试订单"""
    defaults = {
        "orderId": "TEST-001", "productType": "TestProd",
        "targetWidth": 300, "targetThickness": 40, "totalQuantityKg": 500,
        "cleanroomReq": "Class_10K", "customerClass": "STANDARD",
        "orderClass": "NORMAL", "coronaReq": "NO", "coreSizeInch": 3,
        "recipeMaterialsSequence": ["Borealis_LE6601-PH"] * 5,
    }
    defaults.update(kwargs)
    return ProductionOrderModel.from_dict(defaults)


def _make_machine(**kwargs) -> BlownFilmMachineModel:
    """快速构造测试机台"""
    defaults = {
        "machineId": "LINE-01", "name": "Test", "cleanroomLevel": "Class_10K",
        "layerStructure": 5, "dieDiameterMm": 300, "minWidth": 200,
        "maxWidth": 600, "minThickness": 20, "maxThickness": 80,
        "hourlyOutputKg": 50, "maxSlittingLanes": 4,
        "initialMaterialLanes": ["Standard_Med_LDPE"] * 5,
        "initialWidth": 300, "initialThickness": 40,
        "initialCorona": "NO", "initialCoreSize": 3,
        "forbiddenCalendar": [],
    }
    defaults.update(kwargs)
    return BlownFilmMachineModel.from_dict(defaults)


def _make_setup_mgr() -> SetupMatricesManager:
    """构造测试用换产矩阵管理器（手动填充关键数据）"""
    mgr = SetupMatricesManager()
    # 填充原料切换矩阵
    mgr.material_switch_matrix[("Sinopec_YM-210", "Borealis_LE6601-PH")] = 180
    mgr.material_switch_matrix[("Borealis_LE6601-PH", "Sinopec_YM-210")] = 90
    mgr.material_switch_matrix[("Dow_ELITE_5400G", "Borealis_LE6601-PH")] = 150
    mgr.same_material_time = 30
    # 填充幅宽规则
    mgr.width_up_rules = [(50, 15), (200, 40), (999, 90)]
    mgr.width_down_rules = [(50, 30), (200, 60), (999, 120)]
    mgr.die_change_time = 360
    # 填充厚度规则
    mgr.thickness_rules = [(10, 10), (999, 30)]
    # 固定值
    mgr.corona_switch_time = 20
    mgr.core_size_switch_time = 30
    # GMP 清场
    mgr.gmp_clearance_matrix[("NORMAL", "URGENT")] = 45
    mgr.gmp_clearance_matrix[("ANY", "SAMPLE")] = 60
    mgr.gmp_clearance_matrix[("SAMPLE", "ANY")] = 60
    return mgr


class TestSetupTimeCalculation(unittest.TestCase):
    """换产耗时精算测试"""

    def setUp(self):
        self.mgr = _make_setup_mgr()
        self.calc = SetupCalculator(self.mgr)
        self.machine = _make_machine()

    def test_same_material_same_spec(self):
        """同材质同规格：仅同料换批次清场"""
        a = _make_order(orderId="A")
        b = _make_order(orderId="B")
        t = self.calc.calculate_setup_time(a, b, self.machine)
        self.assertEqual(t, 30)  # 同料换批次 Max(30,30,30,30,30) = 30

    def test_material_change_concurrent_max(self):
        """异质换料并发 Max：取最慢层"""
        a = _make_order(
            orderId="A",
            recipeMaterialsSequence=["Sinopec_YM-210", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH"])
        b = _make_order(
            orderId="B",
            recipeMaterialsSequence=["Borealis_LE6601-PH", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH"])
        t = self.calc.calculate_setup_time(a, b, self.machine)
        # 第一层 Sinopec→Borealis=180, 其余同料=30, Max=180
        self.assertEqual(t, 180)

    def test_width_up_small(self):
        """幅宽升序 ≤50mm"""
        a = _make_order(orderId="A", targetWidth=300)
        b = _make_order(orderId="B", targetWidth=340)
        t = self.calc.calculate_setup_time(a, b, self.machine)
        # 同料=30, 幅宽+15, 同厚/电晕/管径=0
        self.assertEqual(t, 30 + 15)

    def test_width_down_large(self):
        """幅宽降序 >200mm"""
        a = _make_order(orderId="A", targetWidth=550)
        b = _make_order(orderId="B", targetWidth=300)
        t = self.calc.calculate_setup_time(a, b, self.machine)
        # 同料=30, 幅宽降 250mm → 120
        self.assertEqual(t, 30 + 120)

    def test_gmp_normal_to_urgent(self):
        """GMP 清场: NORMAL → URGENT"""
        a = _make_order(orderId="A", orderClass="NORMAL")
        b = _make_order(orderId="B", orderClass="URGENT")
        t = self.calc.calculate_setup_time(a, b, self.machine)
        self.assertEqual(t, 30 + 45)  # 同料30 + GMP45

    def test_start_to_first_order(self):
        """机台初始状态 → 首单"""
        b = _make_order(orderId="B")
        t = self.calc.calculate_setup_time(None, b, self.machine)
        # 初始挂料 Standard_Med_LDPE → Borealis_LE6601-PH (未命中=120 fallback)
        # Max(120,120,120,120,120) = 120
        self.assertGreaterEqual(t, 120)

    def test_missing_material_switches_are_summarized(self):
        """未配置材料切换只记录汇总，供排程诊断展示。"""
        self.mgr.reset_runtime_observations()

        first = self.mgr.get_material_switch_time("A-RAW", "B-RAW")
        second = self.mgr.get_material_switch_time("A-RAW", "B-RAW")
        missing = self.mgr.get_missing_material_switches()

        self.assertEqual(first, second)
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["from_material"], "A-RAW")
        self.assertEqual(missing[0]["to_material"], "B-RAW")
        self.assertEqual(missing[0]["lookup_count"], 2)

    def test_corona_switch(self):
        """电晕切换"""
        a = _make_order(orderId="A", coronaReq="YES")
        b = _make_order(orderId="B", coronaReq="NO")
        t = self.calc.calculate_setup_time(a, b, self.machine)
        self.assertEqual(t, 30 + 20)  # 同料30 + 电晕20

    def test_first_order_uses_machine_current_corona_and_core(self):
        """首单换产应使用机台当前电晕和纸芯状态。"""
        machine = _make_machine(
            initialMaterialLanes=["Borealis_LE6601-PH"] * 5,
            initialCorona="NO",
            initialCoreSize=6,
        )
        b = _make_order(orderId="B", coronaReq="YES", coreSizeInch=3)
        t = self.calc.calculate_setup_time(None, b, machine)
        self.assertEqual(t, 30 + 20 + 30)


class TestScrapWeightCalculation(unittest.TestCase):
    """废料守恒精算测试"""

    def setUp(self):
        self.mgr = _make_setup_mgr()
        self.calc = SetupCalculator(self.mgr)
        self.machine = _make_machine()

    def test_scrap_is_sum_not_max(self):
        """废料为逐层 Sum 而非 Max"""
        a = _make_order(
            orderId="A",
            recipeMaterialsSequence=["Sinopec_YM-210", "Sinopec_YM-210",
                                      "Borealis_LE6601-PH", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH"])
        b = _make_order(
            orderId="B",
            recipeMaterialsSequence=["Borealis_LE6601-PH", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH", "Borealis_LE6601-PH",
                                      "Borealis_LE6601-PH"])
        scrap = self.calc.calculate_scrap_weight(a, b, self.machine)
        # 2 layers changed (25kg each) + 3 layers same (5kg each) = 50+15 = 65
        self.assertEqual(scrap, 25 * 2 + 5 * 3)

    def test_actual_material_formula(self):
        """actual_material = net_weight + scrap"""
        a = _make_order(orderId="A")
        b = _make_order(orderId="B", totalQuantityKg=1000)
        scrap = self.calc.calculate_scrap_weight(a, b, self.machine)
        actual = b.total_quantity_kg + scrap
        self.assertEqual(actual, 1000 + scrap)

    def test_width_change_adds_scrap(self):
        """幅宽变动产生额外废料"""
        a = _make_order(orderId="A", targetWidth=300)
        b = _make_order(orderId="B", targetWidth=400)
        scrap = self.calc.calculate_scrap_weight(a, b, self.machine)
        # 5 layers same (5*5=25) + width change (15) = 40
        self.assertEqual(scrap, 5 * 5 + 15)

    def test_material_scrap_rule_overrides_constant(self):
        """Rules 中配置的材料废料应覆盖默认每层废料常量。"""
        self.mgr.material_switch_scrap_matrix[
            ("Sinopec_YM-210", "Borealis_LE6601-PH")
        ] = 7.5
        a = _make_order(
            orderId="A",
            recipeMaterialsSequence=[
                "Sinopec_YM-210",
                "Borealis_LE6601-PH",
                "Borealis_LE6601-PH",
                "Borealis_LE6601-PH",
                "Borealis_LE6601-PH",
            ],
        )
        b = _make_order(orderId="B")
        scrap = self.calc.calculate_scrap_weight(a, b, self.machine)
        self.assertEqual(scrap, 7.5 + 5 * 4)

    def test_spec_scrap_rule_overrides_constant(self):
        """Rules 中配置的规格废料应覆盖默认幅宽废料常量。"""
        self.mgr.width_up_scrap_rules = [(50, 2.5), (200, None), (999, None)]
        a = _make_order(orderId="A", targetWidth=300)
        b = _make_order(orderId="B", targetWidth=340)
        scrap = self.calc.calculate_scrap_weight(a, b, self.machine)
        self.assertEqual(scrap, 5 * 5 + 2.5)


if __name__ == "__main__":
    unittest.main()
