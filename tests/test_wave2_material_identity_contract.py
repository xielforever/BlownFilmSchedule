"""Static contracts for Wave 2 material identity governance and repeatable overrides."""

from __future__ import annotations

import ast
import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENTITY_EXAMPLE = os.path.join(ROOT, "config", "wave2_material_identity_overrides.example.json")
IDENTITY_SCRIPT = os.path.join(ROOT, "scripts", "apply_wave2_material_identity_overrides.py")
BENCHMARK_GENERATOR = os.path.join(ROOT, "scripts", "build_wave2_industrial_benchmark_profile.py")
PLANT_OVERRIDE_SCRIPT = os.path.join(ROOT, "scripts", "apply_wave2_plant_overrides.py")


class TestWave2MaterialIdentityContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(IDENTITY_EXAMPLE, "r", encoding="utf-8") as handle:
            cls.example = json.load(handle)
        cls.sources = {}
        for path in (IDENTITY_SCRIPT, BENCHMARK_GENERATOR, PLANT_OVERRIDE_SCRIPT):
            with open(path, "r", encoding="utf-8") as handle:
                cls.sources[path] = handle.read()

    def test_python_assets_parse(self):
        for path, source in self.sources.items():
            ast.parse(source, filename=path)

    def test_identity_example_is_noop(self):
        self.assertTrue(self.example["materials"])
        self.assertTrue(all(item.get("apply") is False for item in self.example["materials"]))

    def test_identity_override_never_renames_or_approves(self):
        source = self.sources[IDENTITY_SCRIPT]
        self.assertNotIn("UPDATE material_qualifications", source)
        self.assertNotIn("INSERT INTO material_qualifications", source)
        self.assertNotIn("SET material_grade", source)
        self.assertIn("never renames or aliases", source)
        self.assertIn("WHERE material_grade=%s", source)

    def test_le6601_example_is_not_an_alias(self):
        item = next(row for row in self.example["materials"] if row["material_grade"] == "Borealis_LE6601-PH")
        self.assertNotIn("alias_to", item)
        self.assertNotIn("rename_to", item)
        self.assertEqual(item["commercial_grade"], "LE6601-PH")
        self.assertNotEqual(item["commercial_grade"], "LE6600-PH")

    def test_unknown_polymer_family_blocks_benchmark_release(self):
        source = self.sources[BENCHMARK_GENERATOR]
        self.assertIn("UNKNOWN_POLYMER_FAMILIES", source)
        self.assertIn("identity_ok = not unknown_layers", source)
        self.assertIn("releasable = structure_ok and identity_ok", source)
        self.assertIn("unknown_material_families", source)

    def test_material_qualification_override_is_repeatable(self):
        source = self.sources[PLANT_OVERRIDE_SCRIPT]
        self.assertIn("INSERT INTO material_qualifications", source)
        self.assertIn("WHERE NOT EXISTS", source)
        self.assertIn("q.product_type IS NOT DISTINCT FROM", source)
        self.assertIn("q.recipe_version_id IS NOT DISTINCT FROM", source)
        self.assertIn("q.source_id IS NOT DISTINCT FROM", source)


if __name__ == "__main__":
    unittest.main()
