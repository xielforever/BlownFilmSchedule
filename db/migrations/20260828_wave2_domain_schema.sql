-- Medical Blown Film APS Wave 2 additive domain schema
-- Date: 2026-08-28
-- Safety model: ADDITIVE ONLY. No DROP/RENAME. Current solver remains LEGACY by default.

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. Provenance registry
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provenance_sources (
    source_id           VARCHAR(80) PRIMARY KEY,
    source_type         VARCHAR(40) NOT NULL CHECK (source_type IN (
        'STANDARD_REGULATOR', 'OEM_OFFICIAL', 'MATERIAL_OEM_OFFICIAL',
        'CONVERTER_OFFICIAL', 'PLANT_MASTER', 'PLANT_SOP', 'ENGINEERING',
        'LEARNED', 'SIMULATED'
    )),
    organization        VARCHAR(150),
    title               VARCHAR(300) NOT NULL,
    url_or_reference    TEXT,
    revision            VARCHAR(100),
    document_date       DATE,
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    confidence          VARCHAR(20),
    regulatory_claim    BOOLEAN NOT NULL DEFAULT FALSE,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO provenance_sources
    (source_id, source_type, organization, title, url_or_reference, confidence, regulatory_claim, metadata)
VALUES
    ('SRC-LEGACY-UNKNOWN', 'SIMULATED', 'BlownFilmSchedule', 'Legacy master data with unverified provenance', NULL, 'LOW', FALSE,
        '{"purpose":"migration_placeholder","official":false}'::jsonb),
    ('SRC-SIM-LEGACY', 'SIMULATED', 'BlownFilmSchedule', 'Legacy simulated scheduling rules and values', NULL, 'LOW', FALSE,
        '{"purpose":"legacy_compatibility","official":false}'::jsonb),
    ('SRC-STD-ISO11607-1', 'STANDARD_REGULATOR', 'ISO', 'ISO 11607-1:2019 + Amd 1:2023',
        'https://www.iso.org/standard/70799.html', 'HIGH', TRUE,
        '{"scope":"sterile barrier and packaging systems","does_not_define":"universal blown-film output/changeover/72h cleaning"}'::jsonb),
    ('SRC-REG-FDA-11607', 'STANDARD_REGULATOR', 'U.S. FDA', 'Recognized Consensus Standards - ISO 11607-1/2 AMD1:2023',
        'https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfstandards/results.cfm?referencenumber=11607&sortcolumn=pdd&start_search=1', 'HIGH', TRUE,
        '{"scope":"FDA recognition of packaging consensus standards"}'::jsonb),
    ('SRC-STD-ISO14644-1', 'STANDARD_REGULATOR', 'ISO', 'ISO 14644-1:2015',
        'https://www.iso.org/standard/53394.html', 'HIGH', TRUE,
        '{"scope":"air cleanliness classification","does_not_define":"one universal medical blown-film cleanroom class"}'::jsonb),
    ('SRC-GMP-EU-ANNEX1', 'STANDARD_REGULATOR', 'European Commission', 'EudraLex Volume 4 Annex 1',
        'https://health.ec.europa.eu/medicinal-products/eudralex/eudralex-volume-4_en', 'HIGH', TRUE,
        '{"scope":"sterile medicinal product GMP where applicable","does_not_define":"universal blown-film 72h cleaning interval"}'::jsonb),
    ('SRC-OEM-WH-VAREX2', 'OEM_OFFICIAL', 'Windmoller & Holscher', 'VAREX II blown film line',
        'https://www.wh.group/na/en/our_products/extrusion/blown_film_lines/varex_ii/', 'HIGH', FALSE,
        '{"use":"generic capability envelope; not a specific plant nameplate"}'::jsonb),
    ('SRC-CONV-TEKNIPLEX-5L', 'CONVERTER_OFFICIAL', 'TekniPlex Healthcare', '5-Layer Blown Film Extrusion',
        'https://tekni-plex.com/en/healthcare/products/5-layer-blown-film-extrusion', 'HIGH', FALSE,
        '{"use":"healthcare five-layer cleanroom production capability example"}'::jsonb),
    ('SRC-OEM-RAJOO-AQUAFLEX', 'OEM_OFFICIAL', 'Rajoo Engineers', 'AQUAFLEX downward water-quench blown film line',
        'https://rajoo.com/aquaflex.html', 'HIGH', FALSE,
        '{"use":"process-route reference"}'::jsonb),
    ('SRC-MAT-PURELL-2420F', 'MATERIAL_OEM_OFFICIAL', 'LyondellBasell', 'Purell PE 2420 F',
        'https://www.lyondellbasell.com/en/polymers/p/Purell-PE-2420-F/0f3c5e78-3b06-4f33-993b-6144d46d32c0', 'HIGH', FALSE,
        '{"use":"manufacturer healthcare/pharmaceutical film evidence; not plant approval"}'::jsonb),
    ('SRC-MAT-PURELL-3020K', 'MATERIAL_OEM_OFFICIAL', 'LyondellBasell', 'Purell PE 3020K',
        'https://www.lyondellbasell.com/en/polymers/p/Purell-PE-3020K/f782c9ba-1ad5-4608-af62-33aef4930f3b', 'HIGH', FALSE,
        '{"use":"manufacturer healthcare film evidence; not plant approval"}'::jsonb),
    ('SRC-MAT-PURELL-SP170G', 'MATERIAL_OEM_OFFICIAL', 'LyondellBasell', 'Purell SP170G',
        'https://www.lyondellbasell.com/en/polymers/p/Purell-SP170G/38b2ffd8-8447-45e3-84dd-b4c48db5c0f3', 'HIGH', FALSE,
        '{"use":"manufacturer healthcare blown-film evidence; application discussion still required"}'::jsonb),
    ('SRC-MAT-BORMED-DM55PHARM', 'MATERIAL_OEM_OFFICIAL', 'Borealis', 'Bormed DM55pharm',
        'https://www.borealisgroup.com/products/product-catalogue/bormed-dm55pharm-11', 'HIGH', FALSE,
        '{"use":"manufacturer healthcare evaluation and water-quench film evidence; not plant approval"}'::jsonb),
    ('SRC-MAT-SABIC-PCGF0863', 'MATERIAL_OEM_OFFICIAL', 'SABIC', 'SABIC HDPE PCGF0863',
        'https://www.sabic.com/en/products/polymers/polyethylene-pe/sabic-hdpe', 'HIGH', FALSE,
        '{"use":"manufacturer healthcare material evidence; not plant approval"}'::jsonb),
    ('SRC-MAT-EVAL-F171B', 'MATERIAL_OEM_OFFICIAL', 'Kuraray', 'EVAL F171B EVOH',
        'https://eval.kuraray.com/en-emea/downloads/tds-eval-f171b/', 'HIGH', FALSE,
        '{"use":"technical barrier reference; no medical approval inferred"}'::jsonb),
    ('SRC-MAT-PLEXAR-PX3236', 'MATERIAL_OEM_OFFICIAL', 'LyondellBasell', 'Plexar PX3236',
        'https://www.lyondellbasell.com/en/polymers/p/Plexar-PX3236/e105e830-491c-447f-b3c3-8babe86106ea', 'HIGH', FALSE,
        '{"use":"technical tie-layer reference; no medical approval inferred"}'::jsonb),
    ('SRC-MAT-BASF-B36L', 'MATERIAL_OEM_OFFICIAL', 'BASF', 'Ultramid B36 L',
        'https://chemicals.basf.com/global/en/Monomers/polyamides-and-precursors', 'HIGH', FALSE,
        '{"use":"PA6 extrusion/film technical reference; no medical approval inferred"}'::jsonb),
    ('SRC-MAT-EXACT5101-EXCLUDE', 'MATERIAL_OEM_OFFICIAL', 'ExxonMobil', 'Exact 5101 technical data sheet',
        'https://www.exxonmobilchemical.com/en/chemicals/webapi/dps/v1/datasheets/150000103377/0/en', 'HIGH', FALSE,
        '{"use":"negative control; manufacturer states not intended for medical applications"}'::jsonb)
ON CONFLICT (source_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS entity_source_links (
    id                  BIGSERIAL PRIMARY KEY,
    entity_type         VARCHAR(60) NOT NULL,
    entity_key          VARCHAR(200) NOT NULL,
    field_name          VARCHAR(100),
    source_id           VARCHAR(80) NOT NULL REFERENCES provenance_sources(source_id),
    source_role         VARCHAR(30) NOT NULL DEFAULT 'PRIMARY' CHECK (source_role IN (
        'PRIMARY', 'SUPPORTING', 'NEGATIVE_CONTROL', 'PLANT_APPROVAL', 'LEGACY_ORIGIN'
    )),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_source_link
    ON entity_source_links(entity_type, entity_key, COALESCE(field_name, ''), source_id, source_role);

-- -----------------------------------------------------------------------------
-- 2. Additive legacy table extensions
-- -----------------------------------------------------------------------------
ALTER TABLE raw_materials
    ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(100),
    ADD COLUMN IF NOT EXISTS commercial_grade VARCHAR(100),
    ADD COLUMN IF NOT EXISTS polymer_family VARCHAR(30),
    ADD COLUMN IF NOT EXISTS melt_index_test_condition VARCHAR(100),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE material_inventory
    ADD COLUMN IF NOT EXISTS release_status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS use_before_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS supplier_lot VARCHAR(80),
    ADD COLUMN IF NOT EXISTS source_id VARCHAR(80);

ALTER TABLE schedule_settings
    ADD COLUMN IF NOT EXISTS domain_v2_enforcement_mode VARCHAR(20) NOT NULL DEFAULT 'LEGACY';

-- Keep current solver behavior unchanged after migration.
UPDATE schedule_settings
SET domain_v2_enforcement_mode = 'LEGACY'
WHERE domain_v2_enforcement_mode IS NULL;

-- -----------------------------------------------------------------------------
-- 3. Cleaning taxonomy + versioned recipe model
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cleaning_validation_groups (
    group_id             VARCHAR(60) PRIMARY KEY,
    group_name           VARCHAR(120) NOT NULL,
    description          TEXT,
    status               VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    source_id            VARCHAR(80) REFERENCES provenance_sources(source_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recipe_versions (
    recipe_version_id             VARCHAR(80) PRIMARY KEY,
    recipe_code                   VARCHAR(80) NOT NULL,
    product_type                  VARCHAR(50) NOT NULL REFERENCES products(product_type),
    revision                      INTEGER NOT NULL CHECK (revision > 0),
    process_route                 VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
    layer_count                   INTEGER NOT NULL CHECK (layer_count > 0),
    status                        VARCHAR(30) NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT', 'MIGRATED_UNVERIFIED', 'VALIDATED', 'RELEASED', 'RETIRED'
    )),
    required_cleanroom_standard   VARCHAR(40),
    required_cleanroom_iso_class  INTEGER,
    cleaning_validation_group_id  VARCHAR(60) REFERENCES cleaning_validation_groups(group_id),
    source_id                     VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from                    TIMESTAMPTZ,
    valid_to                      TIMESTAMPTZ,
    approved_by                   VARCHAR(80),
    approved_at                   TIMESTAMPTZ,
    change_reason                 TEXT,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(product_type, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_recipe_one_released_per_product
    ON recipe_versions(product_type)
    WHERE status = 'RELEASED' AND valid_to IS NULL;

CREATE TABLE IF NOT EXISTS recipe_layers (
    recipe_version_id          VARCHAR(80) NOT NULL REFERENCES recipe_versions(recipe_version_id) ON DELETE CASCADE,
    layer_index                INTEGER NOT NULL CHECK (layer_index > 0),
    layer_code                 VARCHAR(20),
    extruder_position          INTEGER NOT NULL CHECK (extruder_position > 0),
    material_grade             VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    material_role              VARCHAR(30),
    ratio_pct                  NUMERIC(7,4),
    target_layer_thickness_um  NUMERIC(8,3),
    source_id                  VARCHAR(80) REFERENCES provenance_sources(source_id),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(recipe_version_id, layer_index),
    UNIQUE(recipe_version_id, extruder_position)
);

ALTER TABLE production_orders
    ADD COLUMN IF NOT EXISTS recipe_version_id VARCHAR(80),
    ADD COLUMN IF NOT EXISTS production_context VARCHAR(30) NOT NULL DEFAULT 'COMMERCIAL_MEDICAL';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_production_orders_recipe_version'
    ) THEN
        ALTER TABLE production_orders
            ADD CONSTRAINT fk_production_orders_recipe_version
            FOREIGN KEY (recipe_version_id) REFERENCES recipe_versions(recipe_version_id);
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- 4. Material evidence and plant qualification
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS material_application_evidence (
    evidence_id         BIGSERIAL PRIMARY KEY,
    material_grade      VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    evidence_type       VARCHAR(40) NOT NULL,
    application_scope   TEXT,
    evidence_status     VARCHAR(40) NOT NULL CHECK (evidence_status IN (
        'HEALTHCARE_INTENDED', 'HEALTHCARE_EVALUATION', 'TECHNICAL_FILM_ONLY',
        'EXPLICITLY_EXCLUDED_MEDICAL', 'UNKNOWN'
    )),
    source_id           VARCHAR(80) NOT NULL REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_material_application_evidence
    ON material_application_evidence(material_grade, evidence_status, source_id);

CREATE TABLE IF NOT EXISTS material_qualifications (
    qualification_id         BIGSERIAL PRIMARY KEY,
    material_grade           VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    qualification_scope_type VARCHAR(30) NOT NULL DEFAULT 'GLOBAL',
    product_type             VARCHAR(50) REFERENCES products(product_type),
    recipe_version_id        VARCHAR(80) REFERENCES recipe_versions(recipe_version_id),
    process_route            VARCHAR(40),
    qualification_status     VARCHAR(40) NOT NULL CHECK (qualification_status IN (
        'APPROVED', 'CONDITIONAL', 'TECHNICAL_TRIAL_ONLY', 'EXCLUDED_MEDICAL', 'UNKNOWN'
    )),
    condition_expression     JSONB,
    source_id                VARCHAR(80) REFERENCES provenance_sources(source_id),
    approved_by              VARCHAR(80),
    approved_at              TIMESTAMPTZ,
    valid_from               TIMESTAMPTZ,
    valid_to                 TIMESTAMPTZ,
    reason                   TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 5. Machine capability model
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS machine_capability_profiles (
    machine_id                    VARCHAR(20) PRIMARY KEY REFERENCES machines(machine_id),
    process_route                 VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
    medical_release_status        VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    cleanroom_standard            VARCHAR(40),
    cleanroom_iso_class           INTEGER,
    qualification_status          VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    qualification_valid_until     TIMESTAMPTZ,
    source_id                     VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from                    TIMESTAMPTZ,
    valid_to                      TIMESTAMPTZ,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS machine_extruders (
    machine_id          VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    extruder_position   INTEGER NOT NULL CHECK (extruder_position > 0),
    extruder_code       VARCHAR(50),
    screw_diameter_mm   NUMERIC(8,2),
    status              VARCHAR(30) NOT NULL DEFAULT 'AVAILABLE',
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(machine_id, extruder_position)
);

CREATE TABLE IF NOT EXISTS machine_material_capabilities (
    id                  BIGSERIAL PRIMARY KEY,
    machine_id          VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    extruder_position   INTEGER,
    polymer_family      VARCHAR(30) NOT NULL,
    capability_status   VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN' CHECK (capability_status IN (
        'QUALIFIED', 'CONDITIONAL', 'TECHNICAL_ONLY', 'NOT_SUPPORTED', 'UNKNOWN'
    )),
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_machine_material_capability
    ON machine_material_capabilities(machine_id, COALESCE(extruder_position, 0), polymer_family);

CREATE TABLE IF NOT EXISTS machine_feature_capabilities (
    machine_id          VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    feature_code        VARCHAR(50) NOT NULL,
    enabled             BOOLEAN NOT NULL,
    value_number        NUMERIC(14,4),
    value_text          TEXT,
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(machine_id, feature_code)
);

CREATE TABLE IF NOT EXISTS machine_recipe_capabilities (
    machine_id              VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    recipe_version_id       VARCHAR(80) NOT NULL REFERENCES recipe_versions(recipe_version_id),
    eligibility_status      VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN' CHECK (eligibility_status IN (
        'QUALIFIED', 'CONDITIONAL', 'TECHNICAL_TRIAL_ONLY', 'NOT_QUALIFIED', 'UNKNOWN'
    )),
    standard_rate_kg_h      NUMERIC(10,3),
    min_rate_kg_h           NUMERIC(10,3),
    max_rate_kg_h           NUMERIC(10,3),
    startup_rate_factor     NUMERIC(8,4),
    quality_status          VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    validation_protocol_id  VARCHAR(100),
    confidence              NUMERIC(5,4),
    source_id               VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from              TIMESTAMPTZ,
    valid_to                TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(machine_id, recipe_version_id)
);

-- -----------------------------------------------------------------------------
-- 6. Canonical cleaning transition rules
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cleaning_transition_rules (
    id                  BIGSERIAL PRIMARY KEY,
    from_group_id       VARCHAR(60) NOT NULL REFERENCES cleaning_validation_groups(group_id),
    to_group_id         VARCHAR(60) NOT NULL REFERENCES cleaning_validation_groups(group_id),
    change_time_mins    INTEGER NOT NULL CHECK (change_time_mins >= 0),
    scrap_weight_kg     NUMERIC(10,3),
    enforcement_mode    VARCHAR(30) NOT NULL DEFAULT 'HARD' CHECK (enforcement_mode IN (
        'HARD', 'PUBLISH_BLOCKER', 'SHADOW'
    )),
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(from_group_id, to_group_id)
);

-- -----------------------------------------------------------------------------
-- 7. Material reservation / derived material requirement
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS material_lot_reservations (
    reservation_id          BIGSERIAL PRIMARY KEY,
    inventory_id            INTEGER NOT NULL REFERENCES material_inventory(id),
    order_id                 VARCHAR(20) NOT NULL REFERENCES production_orders(order_id),
    recipe_version_id        VARCHAR(80) REFERENCES recipe_versions(recipe_version_id),
    material_grade           VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    reserved_quantity_kg     NUMERIC(12,3) NOT NULL CHECK (reserved_quantity_kg > 0),
    reservation_status       VARCHAR(30) NOT NULL DEFAULT 'PLANNED' CHECK (reservation_status IN (
        'PLANNED', 'CONFIRMED', 'CONSUMED', 'RELEASED', 'CANCELLED'
    )),
    schedule_run_id          INTEGER REFERENCES schedule_runs(run_id),
    expires_at               TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS order_material_requirements (
    id                       BIGSERIAL PRIMARY KEY,
    order_id                 VARCHAR(20) NOT NULL REFERENCES production_orders(order_id),
    recipe_version_id        VARCHAR(80) REFERENCES recipe_versions(recipe_version_id),
    material_grade           VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    layer_index              INTEGER,
    net_quantity_kg          NUMERIC(12,3) NOT NULL,
    setup_buffer_kg          NUMERIC(12,3) NOT NULL DEFAULT 0,
    gross_quantity_kg        NUMERIC(12,3) NOT NULL,
    released_available_kg    NUMERIC(12,3),
    shortage_quantity_kg     NUMERIC(12,3),
    earliest_feasible_time   TIMESTAMPTZ,
    calculation_version      VARCHAR(80) NOT NULL,
    calculated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_order_material_requirement_calc
    ON order_material_requirements(
        order_id,
        COALESCE(recipe_version_id, ''),
        material_grade,
        COALESCE(layer_index, 0),
        calculation_version
    );

-- -----------------------------------------------------------------------------
-- 8. Safe legacy backfill: UNKNOWN / MIGRATED_UNVERIFIED only
-- -----------------------------------------------------------------------------
INSERT INTO recipe_versions
    (recipe_version_id, recipe_code, product_type, revision, process_route,
     layer_count, status, source_id, change_reason)
SELECT
    'LEGACY-' || md5(r.product_type),
    'LEGACY-' || left(md5(r.product_type), 16),
    r.product_type,
    1,
    'UNKNOWN',
    COUNT(*)::INTEGER,
    'MIGRATED_UNVERIFIED',
    'SRC-LEGACY-UNKNOWN',
    'Wave 2 migration from legacy recipes; not automatically released.'
FROM recipes r
GROUP BY r.product_type
ON CONFLICT (recipe_version_id) DO NOTHING;

WITH ranked_layers AS (
    SELECT
        r.*,
        ROW_NUMBER() OVER (PARTITION BY r.product_type ORDER BY r.layer, r.id)::INTEGER AS layer_pos
    FROM recipes r
)
INSERT INTO recipe_layers
    (recipe_version_id, layer_index, layer_code, extruder_position,
     material_grade, ratio_pct, source_id)
SELECT
    'LEGACY-' || md5(r.product_type),
    r.layer_pos,
    r.layer,
    r.layer_pos,
    r.material_grade,
    r.ratio_pct,
    'SRC-LEGACY-UNKNOWN'
FROM ranked_layers r
ON CONFLICT (recipe_version_id, layer_index) DO NOTHING;

UPDATE production_orders o
SET recipe_version_id = 'LEGACY-' || md5(o.product_type)
WHERE o.recipe_version_id IS NULL
  AND EXISTS (
      SELECT 1 FROM recipe_versions rv
      WHERE rv.recipe_version_id = 'LEGACY-' || md5(o.product_type)
  );

INSERT INTO machine_capability_profiles
    (machine_id, process_route, medical_release_status, qualification_status, source_id)
SELECT
    m.machine_id, 'UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'SRC-LEGACY-UNKNOWN'
FROM machines m
ON CONFLICT (machine_id) DO NOTHING;

INSERT INTO machine_extruders
    (machine_id, extruder_position, extruder_code, status, source_id)
SELECT
    m.machine_id,
    pos,
    'E' || pos::TEXT,
    'AVAILABLE',
    'SRC-LEGACY-UNKNOWN'
FROM machines m
CROSS JOIN LATERAL generate_series(1, GREATEST(m.layer_structure, 0)) AS pos
ON CONFLICT (machine_id, extruder_position) DO NOTHING;

-- Exact grade identity only. No supplier-name or fuzzy matching is permitted.
INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'MANUFACTURER_APPLICATION', 'healthcare/pharmaceutical film',
       'HEALTHCARE_INTENDED', 'SRC-MAT-PURELL-2420F',
       'Manufacturer application evidence only; does not create plant APPROVED qualification.'
FROM raw_materials WHERE material_grade = 'Purell PE 2420 F'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'MANUFACTURER_APPLICATION', 'healthcare film',
       'HEALTHCARE_INTENDED', 'SRC-MAT-PURELL-3020K',
       'Manufacturer application evidence only; does not create plant APPROVED qualification.'
FROM raw_materials WHERE material_grade = 'Purell PE 3020K'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'MANUFACTURER_APPLICATION', 'healthcare blown film / BFS',
       'HEALTHCARE_INTENDED', 'SRC-MAT-PURELL-SP170G',
       'Manufacturer evidence only; application-specific discussion/qualification remains required.'
FROM raw_materials WHERE material_grade = 'Purell SP170G'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'MANUFACTURER_APPLICATION', 'healthcare evaluation / tubular water-quench film',
       'HEALTHCARE_EVALUATION', 'SRC-MAT-BORMED-DM55PHARM',
       'Manufacturer says intended for evaluation; not converted to plant APPROVED.'
FROM raw_materials WHERE material_grade = 'Bormed DM55pharm'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'MANUFACTURER_APPLICATION', 'healthcare HDPE / flexible packaging',
       'HEALTHCARE_INTENDED', 'SRC-MAT-SABIC-PCGF0863',
       'Manufacturer application evidence only; does not create plant APPROVED qualification.'
FROM raw_materials WHERE material_grade = 'SABIC HDPE PCGF0863'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'TECHNICAL_REFERENCE', 'EVOH barrier film',
       'TECHNICAL_FILM_ONLY', 'SRC-MAT-EVAL-F171B',
       'Technical reference only; no healthcare approval inferred.'
FROM raw_materials WHERE material_grade = 'EVAL F171B'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'TECHNICAL_REFERENCE', 'tie layer for PA/EVOH coextrusion',
       'TECHNICAL_FILM_ONLY', 'SRC-MAT-PLEXAR-PX3236',
       'Technical reference only; no healthcare approval inferred.'
FROM raw_materials WHERE material_grade = 'Plexar PX3236'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'TECHNICAL_REFERENCE', 'PA6 blown/water-cooled film',
       'TECHNICAL_FILM_ONLY', 'SRC-MAT-BASF-B36L',
       'Technical reference only; no healthcare approval inferred.'
FROM raw_materials WHERE material_grade = 'Ultramid B36 L'
ON CONFLICT DO NOTHING;

INSERT INTO material_application_evidence
    (material_grade, evidence_type, application_scope, evidence_status, source_id, notes)
SELECT material_grade, 'MANUFACTURER_EXCLUSION', 'medical applications',
       'EXPLICITLY_EXCLUDED_MEDICAL', 'SRC-MAT-EXACT5101-EXCLUDE',
       'Negative control: manufacturer TDS states not intended for medical applications.'
FROM raw_materials WHERE material_grade = 'Exact 5101'
ON CONFLICT DO NOTHING;

-- Legacy scheduling rules receive explicit simulated/unverified provenance.
INSERT INTO entity_source_links
    (entity_type, entity_key, field_name, source_id, source_role, notes)
VALUES
    ('schedule_settings', 'singleton', 'continuous_run_limit_mins', 'SRC-SIM-LEGACY', 'LEGACY_ORIGIN',
        'Legacy 72h value. Not asserted as a universal ISO/FDA rule.'),
    ('schedule_settings', 'singleton', 'mandatory_cleaning_duration_minutes', 'SRC-SIM-LEGACY', 'LEGACY_ORIGIN',
        'Legacy cleaning duration. Requires PLANT_SOP/ENGINEERING source before canonical hard use.'),
    ('schedule_settings', 'singleton', 'weekly_disinfection_enabled', 'SRC-SIM-LEGACY', 'LEGACY_ORIGIN',
        'Legacy periodic sanitation policy. Not a universal regulatory interval.'),
    ('schedule_settings', 'singleton', 'weekly_disinfection_day', 'SRC-SIM-LEGACY', 'LEGACY_ORIGIN',
        'Legacy periodic sanitation schedule.'),
    ('schedule_settings', 'singleton', 'weekly_disinfection_start_time', 'SRC-SIM-LEGACY', 'LEGACY_ORIGIN',
        'Legacy periodic sanitation schedule.'),
    ('schedule_settings', 'singleton', 'weekly_disinfection_duration_mins', 'SRC-SIM-LEGACY', 'LEGACY_ORIGIN',
        'Legacy periodic sanitation schedule.')
ON CONFLICT DO NOTHING;

INSERT INTO entity_source_links
    (entity_type, entity_key, field_name, source_id, source_role, notes)
SELECT
    'gmp_clearance_matrix',
    g.id::TEXT,
    'clearance_time_mins',
    'SRC-SIM-LEGACY',
    'LEGACY_ORIGIN',
    'Legacy rule keyed by order urgency/class; not canonical cleaning taxonomy.'
FROM gmp_clearance_matrix g
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 9. Useful V2 validation / availability views
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_recipe_version_validation AS
SELECT
    rv.recipe_version_id,
    rv.product_type,
    rv.revision,
    rv.status,
    rv.layer_count AS declared_layer_count,
    COUNT(rl.layer_index)::INTEGER AS actual_layer_count,
    COUNT(*) FILTER (WHERE rl.ratio_pct IS NULL)::INTEGER AS missing_ratio_count,
    COALESCE(SUM(rl.ratio_pct), 0)::NUMERIC(10,4) AS ratio_sum_pct,
    (
        COUNT(rl.layer_index) = rv.layer_count
        AND COUNT(*) FILTER (WHERE rl.ratio_pct IS NULL) = 0
        AND ABS(COALESCE(SUM(rl.ratio_pct), 0) - 100.0) <= 0.01
        AND rv.process_route <> 'UNKNOWN'
    ) AS structurally_releasable
FROM recipe_versions rv
LEFT JOIN recipe_layers rl ON rl.recipe_version_id = rv.recipe_version_id
GROUP BY rv.recipe_version_id, rv.product_type, rv.revision, rv.status, rv.layer_count, rv.process_route;

CREATE OR REPLACE VIEW v_material_lot_available AS
SELECT
    mi.id AS inventory_id,
    mi.material_grade,
    mi.lot_number,
    mi.quantity_kg,
    mi.status AS logistics_status,
    mi.release_status,
    mi.expected_arrival,
    mi.use_before_date,
    COALESCE(SUM(r.reserved_quantity_kg) FILTER (
        WHERE r.reservation_status IN ('PLANNED', 'CONFIRMED')
    ), 0)::NUMERIC(12,3) AS active_reserved_kg,
    GREATEST(
        mi.quantity_kg - COALESCE(SUM(r.reserved_quantity_kg) FILTER (
            WHERE r.reservation_status IN ('PLANNED', 'CONFIRMED')
        ), 0),
        0
    )::NUMERIC(12,3) AS available_quantity_kg
FROM material_inventory mi
LEFT JOIN material_lot_reservations r ON r.inventory_id = mi.id
GROUP BY mi.id, mi.material_grade, mi.lot_number, mi.quantity_kg,
         mi.status, mi.release_status, mi.expected_arrival, mi.use_before_date;

-- -----------------------------------------------------------------------------
-- 10. Indexes
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_recipe_versions_product_status
    ON recipe_versions(product_type, status, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_recipe_layers_version
    ON recipe_layers(recipe_version_id, layer_index);
CREATE INDEX IF NOT EXISTS idx_material_evidence_grade_status
    ON material_application_evidence(material_grade, evidence_status);
CREATE INDEX IF NOT EXISTS idx_material_qual_grade_status
    ON material_qualifications(material_grade, qualification_status, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_machine_material_capability
    ON machine_material_capabilities(machine_id, polymer_family, capability_status);
CREATE INDEX IF NOT EXISTS idx_machine_recipe_capability_status
    ON machine_recipe_capabilities(machine_id, recipe_version_id, eligibility_status);
CREATE INDEX IF NOT EXISTS idx_material_inventory_release
    ON material_inventory(material_grade, status, release_status, expected_arrival);
CREATE INDEX IF NOT EXISTS idx_lot_reservation_order_status
    ON material_lot_reservations(order_id, reservation_status);
CREATE INDEX IF NOT EXISTS idx_lot_reservation_inventory_status
    ON material_lot_reservations(inventory_id, reservation_status);
CREATE INDEX IF NOT EXISTS idx_order_material_req_order
    ON order_material_requirements(order_id, calculation_version);
CREATE INDEX IF NOT EXISTS idx_entity_source_entity
    ON entity_source_links(entity_type, entity_key);

COMMENT ON COLUMN raw_materials.material_category IS
    'LEGACY compatibility classification. Must not be used as authoritative medical qualification in Domain V2.';
COMMENT ON COLUMN machines.hourly_output_kg IS
    'LEGACY nominal machine output. Domain V2 production duration authority is machine_recipe_capabilities.standard_rate_kg_h.';
COMMENT ON TABLE gmp_clearance_matrix IS
    'LEGACY clearance matrix keyed by order class. Domain V2 canonical cleaning rules are cleaning_transition_rules.';
COMMENT ON COLUMN schedule_settings.domain_v2_enforcement_mode IS
    'Migration mode: LEGACY keeps current behavior; SHADOW computes V2 diagnostics; HARD makes V2 qualifications authoritative.';

COMMIT;
