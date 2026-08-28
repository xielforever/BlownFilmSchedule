"""Static contracts for Wave 2 material reservation auditing."""

from __future__ import annotations

import ast
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, "scripts", "audit_wave2_material_reservations.py")
EXTENDED = os.path.join(ROOT, "scripts", "audit_wave2_benchmark_readiness.py")


class TestWave2ReservationAuditContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(AUDIT, "r", encoding="utf-8") as handle:
            cls.audit = handle.read()
        with open(EXTENDED, "r", encoding="utf-8") as handle:
            cls.extended = handle.read()

    def test_scripts_parse(self):
        ast.parse(self.audit, filename=AUDIT)
        ast.parse(self.extended, filename=EXTENDED)

    def test_active_reservations_are_planned_or_confirmed(self):
        self.assertIn('ACTIVE_RESERVATION_STATUSES = ("PLANNED", "CONFIRMED")', self.audit)

    def test_unusable_lot_is_blocker(self):
        self.assertIn('row["lot_status"] != "IN_STOCK"', self.audit)
        self.assertIn('row["release_status"] != "RELEASED"', self.audit)
        self.assertIn("_is_expired", self.audit)
        self.assertIn("active_reservation_uses_unusable_lot", self.audit)

    def test_overreservation_is_blocker(self):
        self.assertIn("lot_over_reserved", self.audit)
        self.assertIn("order_material_over_reserved", self.audit)
        self.assertIn("HAVING SUM(r.reserved_quantity_kg) > i.quantity_kg", self.audit)

    def test_underreservation_is_report_only(self):
        self.assertIn("under_reserved_requirement_count", self.audit)
        self.assertIn("Under-reservation is reported", self.audit)
        self.assertNotIn('blockers.append("order_material_under_reserved")', self.audit)

    def test_extended_readiness_consumes_reservation_audit(self):
        self.assertIn("collect_reservation_audit", self.extended)
        self.assertIn('if not reservation_audit["safe"]', self.extended)
        self.assertIn('f"reservation:{code}"', self.extended)


if __name__ == "__main__":
    unittest.main()
