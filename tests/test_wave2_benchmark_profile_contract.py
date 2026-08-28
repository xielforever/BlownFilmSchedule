"""Static contract tests for the Wave 2 industrial benchmark plant profile.

No database is required. These tests ensure the benchmark remains explicitly simulated,
does not fabricate missing recipe ratios, and cannot silently become production authority.
"""

from __future__ import annotations

import ast
import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = os.path.join(ROOT, "data", "wave2", "industrial_benchmark_policy.json")
GENERATOR = os.path.join(ROOT, "scripts", "build_wave2_industrial_benchmark_profile.py")
REQUIREMENTS = os.path.join(ROOT, "scripts", "rebuild_wave2_order_material_requirements.py")
AUDIT = os.path.join(ROOT, "scripts", "audit_wave2_benchmark_readiness.py")


class TestWave2BenchmarkProfileContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(POLICY, "r", encoding="utf-8") as handle:
            cls.policy = json.load(handle)
        cls.sources = {}
        for path in (GENERATOR, REQUIREMENTS, AUDIT):
            with open(path, "r", encoding="utf-8") as handle:
                cls.sources[path] = handle.read()

    def test_python_assets_parse(self):
        for path, source in self.sources.items():
            ast.parse(source, filename=path)

    def test_benchmark_source_is_simulated_only(self):
        self.assertEqual(self.policy["source"]["source_type"], "SIMULATED")
        self.assertFalse(self.policy["source"]["metadata"]["production_authority"])
        self.assertIn("SIMULATED_WITH_OFFICIAL_ENVELOPE", self.policy["source"]["metadata"]["simulation_class"])

    def test_missing_recipe_ratio_is_never_fabricated(self):
        self.assertEqual(
            self.policy["recipe_release_policy"]["missing_ratio_action"],
            "BLOCK_PROFILE_GENERATION_FOR_RECIPE",
        )
        source = self.sources[GENERATOR]
        self.assertIn("refuses to fabricate missing recipe ratios", source)
        self.assertNotIn("100 / len(", source)
        self.assertNotIn("100/len(", source)

    def test_exact_medical_exclusion_wins(self):
        source = self.sources[GENERATOR]
        self.assertIn("EXPLICITLY_EXCLUDED_MEDICAL", source)
        self.assertIn("EXCLUDED_MEDICAL", source)
        self.assertIn("if excluded", source)

    def test_machine_recipe_rate_is_recipe_differentiated(self):
        factors = {rule["family"]: rule["rate_factor"] for rule in self.policy["recipe_family_rules"]}
        self.assertGreater(len(set(factors.values())), 1)
        self.assertLess(factors["BARRIER_EVOH"], factors["PE_MONO"])
        self.assertLess(factors["BARRIER_PA"], factors["PE_MONO"])

    def test_corona_is_explicit_and_scarce(self):
        ratio = float(self.policy["feature_policy"]["CORONA"]["enabled_ratio_target"])
        self.assertGreater(ratio, 0)
        self.assertLess(ratio, 1)
        self.assertIn('"CORONA"', self.sources[GENERATOR])
        self.assertIn("machines_with_explicit_corona_capability", self.sources[AUDIT])

    def test_material_requirement_uses_recipe_ratio(self):
        source = self.sources[REQUIREMENTS]
        self.assertIn("SUM(ratio_pct)", source)
        self.assertIn("quantity * ratio / Decimal(\"100\")", source)
        self.assertNotIn("material_available_time", source)

    def test_benchmark_does_not_modify_solver(self):
        for source in self.sources.values():
            self.assertNotIn("from src.scheduler", source)
            self.assertNotIn("import src.scheduler", source)
            self.assertNotIn("domain_v2_enforcement_mode = 'HARD'", source)

    def test_cleaning_matrix_is_complete_square(self):
        groups = [row["group_id"] for row in self.policy["cleaning_groups"]]
        matrix = self.policy["cleaning_transition_minutes"]
        self.assertEqual(set(matrix), set(groups))
        for group in groups:
            self.assertEqual(set(matrix[group]), set(groups))
            for minutes in matrix[group].values():
                self.assertGreaterEqual(int(minutes), 0)


if __name__ == "__main__":
    unittest.main()
