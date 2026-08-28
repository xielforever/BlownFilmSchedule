"""Contract tests for the legacy-to-V2 override candidate generator."""

from __future__ import annotations

import ast
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(ROOT, "scripts", "generate_wave2_override_candidates.py")


class TestWave2OverrideCandidateGeneratorContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SCRIPT_PATH, "r", encoding="utf-8") as handle:
            cls.script = handle.read()

    def test_script_parses(self):
        ast.parse(self.script)

    def test_generated_candidates_are_noop(self):
        self.assertIn('"all_apply_false": True', self.script)
        self.assertIn('"apply": False', self.script)
        self.assertNotIn('"apply": True', self.script)

    def test_process_and_medical_qualification_are_not_inferred(self):
        self.assertIn('"process_route_inference": False', self.script)
        self.assertIn('"medical_qualification_inference": False', self.script)
        self.assertIn('"process_route": "UNKNOWN"', self.script)
        self.assertIn('"proposed_plant_qualification": "UNKNOWN"', self.script)

    def test_legacy_rate_candidate_never_becomes_qualified(self):
        self.assertIn('"eligibility_status": "UNKNOWN"', self.script)
        self.assertIn('"legacy_rate_is_qualified": False', self.script)
        self.assertIn('"confidence": 0.10', self.script)
        self.assertNotIn('"eligibility_status": "QUALIFIED"', self.script)

    def test_generator_does_not_write_domain_tables(self):
        upper = self.script.upper()
        self.assertNotIn("INSERT INTO MACHINE_RECIPE_CAPABILITIES", upper)
        self.assertNotIn("UPDATE MACHINE_CAPABILITY_PROFILES", upper)
        self.assertNotIn("INSERT INTO MATERIAL_QUALIFICATIONS", upper)


if __name__ == "__main__":
    unittest.main()
