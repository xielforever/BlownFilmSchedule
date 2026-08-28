"""Static/data-contract tests for Wave 2-D master-data population.

No PostgreSQL connection is required. These tests protect source identity and prevent
future edits from converting manufacturer evidence or historical aliases into unsafe
plant qualifications.
"""

from __future__ import annotations

import ast
import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(ROOT, "data", "wave2", "official_material_catalog.json")
SEED_SCRIPT_PATH = os.path.join(ROOT, "scripts", "seed_wave2_master_data.py")
OVERRIDE_SCRIPT_PATH = os.path.join(ROOT, "scripts", "apply_wave2_plant_overrides.py")
OVERRIDE_EXAMPLE_PATH = os.path.join(ROOT, "config", "wave2_plant_master_overrides.example.json")


class TestWave2MasterDataPopulationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CATALOG_PATH, "r", encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        with open(SEED_SCRIPT_PATH, "r", encoding="utf-8") as handle:
            cls.seed_script = handle.read()
        with open(OVERRIDE_SCRIPT_PATH, "r", encoding="utf-8") as handle:
            cls.override_script = handle.read()
        with open(OVERRIDE_EXAMPLE_PATH, "r", encoding="utf-8") as handle:
            cls.override_example = json.load(handle)

    def test_python_population_scripts_parse(self):
        ast.parse(self.seed_script)
        ast.parse(self.override_script)

    def test_catalog_requires_exact_alias_matching(self):
        self.assertEqual(self.catalog["policy"]["identity_match"], "EXACT_ALIAS_ONLY")
        self.assertFalse(self.catalog["policy"]["manufacturer_evidence_is_plant_approval"])

    def test_catalog_aliases_are_unique(self):
        seen = {}
        for material in self.catalog["materials"]:
            self.assertIn(material["canonical_grade"], material["exact_aliases"])
            for alias in material["exact_aliases"]:
                key = " ".join(alias.strip().split()).casefold()
                self.assertNotIn(key, seen, f"duplicate alias {alias}: {seen.get(key)}")
                seen[key] = material["canonical_grade"]

    def test_healthcare_evidence_never_auto_approves(self):
        for material in self.catalog["materials"]:
            if material["evidence_status"] in {"HEALTHCARE_INTENDED", "HEALTHCARE_EVALUATION", "TECHNICAL_FILM_ONLY"}:
                self.assertEqual(material["medical_qualification_action"], "NO_AUTO_APPROVAL")

    def test_only_explicit_negative_control_can_auto_exclude(self):
        auto_actions = [
            material
            for material in self.catalog["materials"]
            if material["medical_qualification_action"] != "NO_AUTO_APPROVAL"
        ]
        self.assertEqual(len(auto_actions), 1)
        self.assertEqual(auto_actions[0]["canonical_grade"], "Exact 5101")
        self.assertEqual(auto_actions[0]["evidence_status"], "EXPLICITLY_EXCLUDED_MEDICAL")
        self.assertEqual(auto_actions[0]["medical_qualification_action"], "AUTO_EXCLUDE_MEDICAL")

    def test_le6601_is_not_aliased_to_le6600(self):
        le6600 = next(item for item in self.catalog["materials"] if item["canonical_grade"] == "Bormed LE6600-PH")
        aliases = {alias.casefold() for alias in le6600["exact_aliases"]}
        self.assertNotIn("borealis_le6601-ph", aliases)
        self.assertNotIn("bormed le6601-ph", aliases)

        watch = self.catalog["legacy_identity_watchlist"][0]
        self.assertIn("LE6601", " ".join(watch["exact_aliases"]))
        self.assertEqual(watch["action"], "KEEP_UNVERIFIED_NOT_ALIASED_TO_LE6600")
        self.assertIsNone(watch["replacement"])

    def test_le6600_has_current_borealis_source(self):
        source = next(item for item in self.catalog["sources"] if item["source_id"] == "SRC-MAT-BORMED-LE6600PH")
        self.assertEqual(source["organization"], "Borealis")
        self.assertEqual(source["document_date"], "2025-11-18")
        self.assertIn("DMF 027587", source["metadata"]["references"])
        self.assertFalse(source["metadata"]["plant_approval"])

    def test_pa_density_range_is_not_fabricated_as_scalar(self):
        b36l = next(item for item in self.catalog["materials"] if item["canonical_grade"] == "Ultramid B36 L")
        self.assertIsNone(b36l["density"])
        self.assertEqual(b36l["evidence_status"], "TECHNICAL_FILM_ONLY")

    def test_seed_default_does_not_insert_missing_official_materials(self):
        self.assertIn("--insert-missing-official-materials", self.seed_script)
        self.assertIn("action=\"store_true\"", self.seed_script)
        self.assertNotIn("LIKE '%BOREALIS%'", self.seed_script.upper())
        self.assertNotIn("LIKE '%PURELL%'", self.seed_script.upper())

    def test_seed_keeps_wave2_enforcement_legacy(self):
        self.assertIn("domain_v2_enforcement_mode='LEGACY'", self.seed_script)
        self.assertIn("manufacturer healthcare statement NEVER creates plant APPROVED", self.seed_script)

    def test_legacy_rate_bootstrap_is_shadow_only(self):
        self.assertIn("--bootstrap-legacy-rate-shadow", self.seed_script)
        self.assertIn("'UNKNOWN', m.hourly_output_kg", self.seed_script)
        self.assertIn("0.10, 'SRC-SIM-LEGACY'", self.seed_script)

    def test_override_source_rejects_generic_oem_authority(self):
        ast_tree = ast.parse(self.override_script)
        allowed_values = None
        for node in ast_tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "ALLOWED_SOURCE_TYPES":
                        allowed_values = ast.literal_eval(node.value)
        self.assertIsNotNone(allowed_values)
        self.assertNotIn("OEM_OFFICIAL", allowed_values)
        self.assertNotIn("MATERIAL_OEM_OFFICIAL", allowed_values)
        self.assertIn("PLANT_MASTER", allowed_values)
        self.assertIn("SIMULATED", allowed_values)

    def test_machine_material_upsert_targets_expression_index(self):
        self.assertIn(
            "ON CONFLICT (machine_id, (COALESCE(extruder_position, 0)), polymer_family)",
            self.override_script,
        )

    def test_qualified_rate_requires_positive_value(self):
        self.assertIn("QUALIFIED machine-recipe capability requires positive standard_rate_kg_h", self.override_script)

    def test_released_recipe_requires_approval_and_ratio_validation(self):
        self.assertIn("A RELEASED recipe requires approved_by and approved_at", self.override_script)
        self.assertIn("v_recipe_version_validation", self.override_script)
        self.assertIn("Cannot RELEASE recipe", self.override_script)

    def test_override_example_is_noop_by_default(self):
        collections = [
            "machines",
            "machine_material_capabilities",
            "machine_feature_capabilities",
            "cleaning_validation_groups",
            "cleaning_transition_rules",
            "recipe_versions",
            "material_qualifications",
            "machine_recipe_capabilities",
            "inventory_release",
        ]
        for name in collections:
            for row in self.override_example.get(name, []):
                self.assertFalse(row.get("apply"), f"example row in {name} must default apply=false")
        self.assertTrue(self.override_example["source"]["metadata"]["example_only"])
        self.assertFalse(self.override_example["source"]["metadata"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
