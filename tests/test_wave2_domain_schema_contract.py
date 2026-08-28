"""Static safety contract for the Wave 2 additive domain migration.

These tests do not require PostgreSQL. They prevent future edits from turning the
migration into a destructive change or silently approving unverified medical data.
"""

from __future__ import annotations

import os
import re
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION_PATH = os.path.join(
    ROOT,
    "db",
    "migrations",
    "20260828_wave2_domain_schema.sql",
)


class TestWave2DomainSchemaContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MIGRATION_PATH, "r", encoding="utf-8") as handle:
            cls.sql = handle.read()
        cls.sql_upper = cls.sql.upper()

    def test_migration_is_additive_only(self):
        destructive_patterns = [
            r"\bDROP\s+TABLE\b",
            r"\bDROP\s+COLUMN\b",
            r"\bALTER\s+COLUMN\b.*\bTYPE\b",
            r"\bRENAME\s+TO\b",
        ]
        for pattern in destructive_patterns:
            self.assertIsNone(
                re.search(pattern, self.sql_upper),
                f"Wave 2 migration must stay additive; found pattern {pattern}",
            )

    def test_default_enforcement_stays_legacy(self):
        self.assertIn("DOMAIN_V2_ENFORCEMENT_MODE", self.sql_upper)
        self.assertRegex(
            self.sql_upper,
            r"DOMAIN_V2_ENFORCEMENT_MODE\s+VARCHAR\(20\)\s+NOT\s+NULL\s+DEFAULT\s+'LEGACY'",
        )

    def test_legacy_recipe_backfill_is_not_released(self):
        self.assertIn("MIGRATED_UNVERIFIED", self.sql_upper)
        legacy_insert = re.search(
            r"INSERT INTO RECIPE_VERSIONS.*?FROM RECIPES R.*?ON CONFLICT",
            self.sql_upper,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(legacy_insert)
        self.assertIn("'MIGRATED_UNVERIFIED'", legacy_insert.group(0))
        self.assertNotIn("'RELEASED'", legacy_insert.group(0))

    def test_migration_never_auto_approves_materials(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS MATERIAL_QUALIFICATIONS", self.sql_upper)
        self.assertNotRegex(
            self.sql_upper,
            r"INSERT\s+INTO\s+MATERIAL_QUALIFICATIONS[\s\S]*?'APPROVED'",
        )

    def test_supplier_name_is_not_used_for_medical_classification(self):
        forbidden_logic = [
            "LIKE '%BOREALIS%'",
            "LIKE '%PURELL%'",
            "LIKE '%SABIC%'",
            "POSITION('BOREALIS'",
        ]
        for fragment in forbidden_logic:
            self.assertNotIn(fragment, self.sql_upper)

    def test_official_negative_control_is_seeded(self):
        self.assertIn("SRC-MAT-EXACT5101-EXCLUDE", self.sql)
        self.assertIn("EXPLICITLY_EXCLUDED_MEDICAL", self.sql)
        self.assertIn("WHERE material_grade = 'Exact 5101'", self.sql)

    def test_recipe_ratio_is_preserved_without_fabrication(self):
        self.assertIn("r.ratio_pct", self.sql)
        self.assertNotRegex(
            self.sql_upper,
            r"RATIO_PCT\s*=\s*100\s*/",
        )

    def test_machine_process_route_backfills_unknown(self):
        self.assertRegex(
            self.sql_upper,
            r"MACHINE_CAPABILITY_PROFILES[\s\S]*?'UNKNOWN'\s*,\s*'UNKNOWN'\s*,\s*'UNKNOWN'",
        )

    def test_legacy_rules_receive_non_regulatory_provenance(self):
        self.assertIn("SRC-SIM-LEGACY", self.sql)
        self.assertIn("Legacy 72h value. Not asserted as a universal ISO/FDA rule.", self.sql)
        self.assertIn("Legacy rule keyed by order urgency/class", self.sql)

    def test_required_v2_tables_exist_in_contract(self):
        required = {
            "PROVENANCE_SOURCES",
            "MATERIAL_APPLICATION_EVIDENCE",
            "MATERIAL_QUALIFICATIONS",
            "RECIPE_VERSIONS",
            "RECIPE_LAYERS",
            "MACHINE_CAPABILITY_PROFILES",
            "MACHINE_EXTRUDERS",
            "MACHINE_MATERIAL_CAPABILITIES",
            "MACHINE_FEATURE_CAPABILITIES",
            "MACHINE_RECIPE_CAPABILITIES",
            "CLEANING_VALIDATION_GROUPS",
            "CLEANING_TRANSITION_RULES",
            "MATERIAL_LOT_RESERVATIONS",
            "ORDER_MATERIAL_REQUIREMENTS",
        }
        for name in required:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {name}", self.sql_upper)


if __name__ == "__main__":
    unittest.main()
