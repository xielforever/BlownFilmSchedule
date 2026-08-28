-- Wave 2 domain schema guardrails
-- Apply after 20260828_wave2_domain_schema.sql.

BEGIN;

-- Keep migration mode values explicit and auditable.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_schedule_settings_domain_v2_mode'
          AND conrelid = 'schedule_settings'::regclass
    ) THEN
        ALTER TABLE schedule_settings
            ADD CONSTRAINT ck_schedule_settings_domain_v2_mode
            CHECK (domain_v2_enforcement_mode IN ('LEGACY', 'SHADOW', 'HARD'));
    END IF;
END $$;

-- The word "available" must mean materially usable by a commercial schedule,
-- not merely positive physical quantity. QC-held/quarantined/rejected/expired
-- or non-stock lots expose zero available quantity here.
CREATE OR REPLACE VIEW v_material_lot_available AS
WITH reservation_totals AS (
    SELECT
        inventory_id,
        COALESCE(SUM(reserved_quantity_kg) FILTER (
            WHERE reservation_status IN ('PLANNED', 'CONFIRMED')
        ), 0)::NUMERIC(12,3) AS active_reserved_kg
    FROM material_lot_reservations
    GROUP BY inventory_id
)
SELECT
    mi.id AS inventory_id,
    mi.material_grade,
    mi.lot_number,
    mi.quantity_kg,
    mi.status AS logistics_status,
    mi.release_status,
    mi.expected_arrival,
    mi.received_at,
    mi.use_before_date,
    COALESCE(rt.active_reserved_kg, 0)::NUMERIC(12,3) AS active_reserved_kg,
    (
        mi.status = 'IN_STOCK'
        AND mi.release_status = 'RELEASED'
        AND (mi.use_before_date IS NULL OR mi.use_before_date > NOW())
    ) AS materially_usable,
    CASE
        WHEN mi.status = 'IN_STOCK'
         AND mi.release_status = 'RELEASED'
         AND (mi.use_before_date IS NULL OR mi.use_before_date > NOW())
        THEN GREATEST(mi.quantity_kg - COALESCE(rt.active_reserved_kg, 0), 0)
        ELSE 0
    END::NUMERIC(12,3) AS available_quantity_kg
FROM material_inventory mi
LEFT JOIN reservation_totals rt ON rt.inventory_id = mi.id;

COMMENT ON VIEW v_material_lot_available IS
    'Domain V2 lot availability. available_quantity_kg is positive only for in-stock, RELEASED and non-expired lots after active reservations.';

COMMIT;
