-- ============================================================
-- 医疗PE薄膜吹膜机 APS 排程系统 — PostgreSQL 数据库初始化
-- 19 张表 · 6 个域 · 覆盖完整运营闭环
-- ============================================================

-- 域 1：客户与原料主数据 ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS customers (
    customer_id     VARCHAR(20)  PRIMARY KEY,
    customer_name   VARCHAR(100) NOT NULL,
    customer_class  VARCHAR(20)  NOT NULL CHECK (customer_class IN ('VIP', 'STANDARD')),
    contact_info    VARCHAR(200),
    notes           TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE customers IS '客户主数据';

CREATE TABLE IF NOT EXISTS raw_materials (
    material_grade      VARCHAR(50)   PRIMARY KEY,
    material_name       VARCHAR(100),
    supplier            VARCHAR(100),
    material_category   VARCHAR(30)   CHECK (material_category IN ('MEDICAL_HIGH', 'MEDICAL_STD', 'PACKAGING', 'SPECIAL')),
    melt_index          NUMERIC(6,2),
    density             NUMERIC(6,4),
    is_special          BOOLEAN       DEFAULT FALSE,
    scrap_per_layer_kg  NUMERIC(6,2)  DEFAULT 25,
    created_at          TIMESTAMPTZ   DEFAULT NOW()
);
COMMENT ON TABLE raw_materials IS '原料牌号主数据';

CREATE TABLE IF NOT EXISTS material_inventory (
    id                SERIAL       PRIMARY KEY,
    material_grade    VARCHAR(50)  NOT NULL REFERENCES raw_materials(material_grade),
    lot_number        VARCHAR(50),
    quantity_kg       NUMERIC(10,2) NOT NULL DEFAULT 0,
    expected_arrival  TIMESTAMPTZ,
    status            VARCHAR(20)  DEFAULT 'IN_STOCK' CHECK (status IN ('IN_STOCK', 'IN_TRANSIT', 'RESERVED', 'DEPLETED')),
    warehouse_location VARCHAR(50),
    created_at        TIMESTAMPTZ  DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE material_inventory IS '原料库存与到货计划';

-- 域 2：产品与配方 ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS products (
    product_type          VARCHAR(50)  PRIMARY KEY,
    product_category      VARCHAR(50),
    layer_type            VARCHAR(20),
    cleanroom_requirement VARCHAR(20),
    description           TEXT,
    created_at            TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE products IS '产品类型主数据';

CREATE TABLE IF NOT EXISTS recipes (
    id              SERIAL       PRIMARY KEY,
    recipe_id       VARCHAR(20)  NOT NULL,
    product_type    VARCHAR(50)  NOT NULL REFERENCES products(product_type),
    layer           VARCHAR(10)  NOT NULL,
    layer_name      VARCHAR(20),
    material_grade  VARCHAR(50)  NOT NULL REFERENCES raw_materials(material_grade),
    ratio_pct       NUMERIC(5,2),
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(product_type, layer)
);
COMMENT ON TABLE recipes IS '工艺配方（产品→层级→原料）';

-- 域 3：设备与维保 ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS machines (
    machine_id          VARCHAR(20)  PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    cleanroom_level     VARCHAR(20)  NOT NULL,
    layer_structure     INTEGER      NOT NULL,
    die_diameter_mm     INTEGER      NOT NULL,
    min_width           INTEGER      NOT NULL,
    max_width           INTEGER      NOT NULL,
    min_thickness       INTEGER      NOT NULL,
    max_thickness       INTEGER      NOT NULL,
    hourly_output_kg    INTEGER      NOT NULL,
    max_slitting_lanes  INTEGER      NOT NULL DEFAULT 1,
    status              VARCHAR(20)  DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'MAINTENANCE', 'OFFLINE')),
    created_at          TIMESTAMPTZ  DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE machines IS '吹膜机设备主数据';

CREATE TABLE IF NOT EXISTS machine_current_state (
    machine_id              VARCHAR(20) PRIMARY KEY REFERENCES machines(machine_id),
    current_material_lanes  TEXT[],
    current_width           INTEGER     DEFAULT 0,
    current_thickness       INTEGER     DEFAULT 0,
    current_corona          BOOLEAN     DEFAULT FALSE,
    current_core_size       INTEGER     DEFAULT 3,
    last_order_id           VARCHAR(20),
    continuous_run_mins     INTEGER     DEFAULT 0,
    last_cleaning_time      TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE machine_current_state IS '机台实时运行状态（滚动排程初始条件）';

CREATE TABLE IF NOT EXISTS machine_maintenance_calendar (
    id                SERIAL       PRIMARY KEY,
    machine_id        VARCHAR(20)  REFERENCES machines(machine_id),
    start_time        TIMESTAMPTZ  NOT NULL,
    end_time          TIMESTAMPTZ  NOT NULL,
    maintenance_type  VARCHAR(30)  DEFAULT 'ROUTINE' CHECK (maintenance_type IN ('ROUTINE', 'EMERGENCY', 'GMP_CLEANING', 'OVERHAUL')),
    reason            VARCHAR(200),
    is_recurring      BOOLEAN      DEFAULT FALSE,
    recurrence_rule   VARCHAR(100),
    is_enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    disabled_reason   TEXT,
    updated_by        VARCHAR(50),
    updated_at        TIMESTAMPTZ  DEFAULT NOW(),
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE machine_maintenance_calendar IS '维保/禁排日历';

CREATE TABLE IF NOT EXISTS machine_downtime_events (
    id                SERIAL       PRIMARY KEY,
    machine_id        VARCHAR(20)  NOT NULL REFERENCES machines(machine_id),
    event_type        VARCHAR(30)  NOT NULL CHECK (event_type IN ('BREAKDOWN', 'EMERGENCY_STOP', 'QUALITY_HOLD', 'MATERIAL_SHORTAGE', 'POWER_OUTAGE', 'OTHER')),
    severity          VARCHAR(10)  NOT NULL CHECK (severity IN ('CRITICAL', 'DEGRADED', 'MINOR')),
    start_time        TIMESTAMPTZ  NOT NULL,
    end_time          TIMESTAMPTZ,
    affected_order_id VARCHAR(20),
    root_cause        VARCHAR(100),
    resolution        TEXT,
    reported_by       VARCHAR(50),
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE machine_downtime_events IS '设备非计划停机事件日志';

-- 域 4：换产工艺配置 ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS material_switch_matrix (
    id                SERIAL       PRIMARY KEY,
    from_material     VARCHAR(50)  NOT NULL REFERENCES raw_materials(material_grade),
    to_material       VARCHAR(50)  NOT NULL REFERENCES raw_materials(material_grade),
    switch_time_mins  INTEGER      NOT NULL,
    scrap_weight_kg   NUMERIC(6,2),
    description       TEXT,
    is_enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    disabled_reason   TEXT,
    updated_by        VARCHAR(50),
    updated_at        TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(from_material, to_material)
);
COMMENT ON TABLE material_switch_matrix IS '原料切换矩阵';

CREATE TABLE IF NOT EXISTS spec_change_rules (
    id                SERIAL       PRIMARY KEY,
    attribute         VARCHAR(30)  NOT NULL,
    condition_desc    VARCHAR(100) NOT NULL,
    threshold_lower   INTEGER,
    threshold_upper   INTEGER,
    change_time_mins  INTEGER      NOT NULL,
    scrap_weight_kg   NUMERIC(6,2) DEFAULT 0,
    description       TEXT,
    is_enabled        BOOLEAN      NOT NULL DEFAULT TRUE,
    disabled_reason   TEXT,
    updated_by        VARCHAR(50),
    updated_at        TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE spec_change_rules IS '规格调机规则';

CREATE TABLE IF NOT EXISTS gmp_clearance_matrix (
    id                    SERIAL       PRIMARY KEY,
    from_order_class      VARCHAR(30)  NOT NULL,
    to_order_class        VARCHAR(30)  NOT NULL,
    clearance_time_mins   INTEGER      NOT NULL,
    description           TEXT,
    is_enabled            BOOLEAN      NOT NULL DEFAULT TRUE,
    disabled_reason       TEXT,
    updated_by            VARCHAR(50),
    updated_at            TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(from_order_class, to_order_class)
);
COMMENT ON TABLE gmp_clearance_matrix IS 'GMP合规清场矩阵';

-- 域 5：生产订单 ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS production_orders (
    order_id                VARCHAR(20)  PRIMARY KEY,
    customer_id             VARCHAR(20)  REFERENCES customers(customer_id),
    product_type            VARCHAR(50)  NOT NULL REFERENCES products(product_type),
    target_width            INTEGER      NOT NULL,
    target_thickness        INTEGER      NOT NULL,
    total_quantity_kg       INTEGER      NOT NULL,
    cleanroom_req           VARCHAR(20)  NOT NULL,
    order_class             VARCHAR(20)  NOT NULL CHECK (order_class IN ('URGENT', 'NORMAL', 'SAMPLE')),
    corona_req              BOOLEAN      DEFAULT FALSE,
    core_size_inch          INTEGER      DEFAULT 3,
    order_date              TIMESTAMPTZ,
    due_date                TIMESTAMPTZ  NOT NULL,
    material_available_time TIMESTAMPTZ,
    status                  VARCHAR(20)  DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'SCHEDULED', 'IN_PRODUCTION', 'COMPLETED', 'CANCELLED')),
    priority_override       INTEGER,
    created_at              TIMESTAMPTZ  DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE production_orders IS '生产工单';

CREATE TABLE IF NOT EXISTS order_revision_audit (
    id                      SERIAL       PRIMARY KEY,
    order_id                VARCHAR(20)  NOT NULL REFERENCES production_orders(order_id),
    action_type             VARCHAR(30)  NOT NULL,
    changed_fields          JSONB        NOT NULL,
    before_state            JSONB,
    after_state             JSONB,
    reason_code             VARCHAR(50),
    reason_text             TEXT,
    impacted_draft_run_ids  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    changed_by              VARCHAR(50),
    changed_at              TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE order_revision_audit IS '订单修订审计';

CREATE TABLE IF NOT EXISTS order_ingestion_batches (
    id                  SERIAL       PRIMARY KEY,
    source_name         VARCHAR(200),
    conflict_policy     VARCHAR(50)  NOT NULL DEFAULT 'reject_duplicates',
    total_rows          INTEGER      NOT NULL DEFAULT 0,
    accepted_rows       INTEGER      NOT NULL DEFAULT 0,
    rejected_rows       INTEGER      NOT NULL DEFAULT 0,
    created_by          VARCHAR(50),
    created_at          TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE order_ingestion_batches IS '订单导入批次';

CREATE TABLE IF NOT EXISTS order_ingestion_rows (
    id                  SERIAL       PRIMARY KEY,
    batch_id            INTEGER      NOT NULL REFERENCES order_ingestion_batches(id),
    row_index           INTEGER      NOT NULL,
    order_id            VARCHAR(20),
    row_status          VARCHAR(30)  NOT NULL,
    normalized_order    JSONB,
    errors              JSONB        NOT NULL DEFAULT '[]'::jsonb,
    warnings            JSONB        NOT NULL DEFAULT '[]'::jsonb,
    created_order       BOOLEAN      NOT NULL DEFAULT FALSE
);
COMMENT ON TABLE order_ingestion_rows IS '订单导入行级结果';

-- 域 6：排程结果与执行反馈 ──────────────────────────────────

CREATE TABLE IF NOT EXISTS schedule_runs (
    run_id                  SERIAL       PRIMARY KEY,
    baseline_time           TIMESTAMPTZ  NOT NULL,
    run_time                TIMESTAMPTZ  DEFAULT NOW(),
    triggered_by            VARCHAR(50),
    status                  VARCHAR(20)  NOT NULL,
    total_orders            INTEGER,
    total_machines_used     INTEGER,
    phase1_tardiness_score  INTEGER,
    phase2_setup_score      INTEGER,
    total_setup_time_mins   INTEGER,
    total_scrap_kg          NUMERIC(10,2),
    total_late_orders       INTEGER,
    vip_late_orders         INTEGER,
    solver_time_seconds     NUMERIC(8,2),
    solver_params           JSONB,
    mode                    VARCHAR(20)  DEFAULT 'AUTO' CHECK (mode IN ('AUTO', 'MANUAL', 'HYBRID')),
    lifecycle_status        VARCHAR(30)  DEFAULT 'CONFIRMED' CHECK (lifecycle_status IN ('DRAFT', 'VALIDATED', 'CONFIRMED', 'CANCELLED', 'SUPERSEDED')),
    confirmed_by            VARCHAR(50),
    confirmed_at            TIMESTAMPTZ,
    cancelled_by            VARCHAR(50),
    cancelled_at            TIMESTAMPTZ,
    cancel_reason           TEXT,
    is_active               BOOLEAN      DEFAULT TRUE
);
COMMENT ON TABLE schedule_runs IS '排程运行批次记录';

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id                          SERIAL        PRIMARY KEY,
    run_id                      INTEGER       NOT NULL REFERENCES schedule_runs(run_id),
    order_id                    VARCHAR(20)   NOT NULL REFERENCES production_orders(order_id),
    machine_id                  VARCHAR(20)   NOT NULL REFERENCES machines(machine_id),
    sequence_index              INTEGER       NOT NULL,
    setup_start_time            TIMESTAMPTZ,
    start_time                  TIMESTAMPTZ   NOT NULL,
    end_time                    TIMESTAMPTZ   NOT NULL,
    start_mins                  INTEGER       NOT NULL,
    end_mins                    INTEGER       NOT NULL,
    duration_mins               INTEGER       NOT NULL,
    setup_time_mins             INTEGER       NOT NULL DEFAULT 0,
    scrap_kg                    NUMERIC(10,2) NOT NULL DEFAULT 0,
    net_weight_kg               INTEGER       NOT NULL,
    actual_material_required_kg NUMERIC(10,2) NOT NULL,
    is_late                     BOOLEAN       DEFAULT FALSE,
    tardiness_mins              INTEGER       DEFAULT 0,
    prev_order_id               VARCHAR(20),
    setup_detail                JSONB,
    task_source                 VARCHAR(20)   DEFAULT 'AUTO' CHECK (task_source IN ('AUTO', 'ADJUSTED', 'MANUAL')),
    manual_lock_machine         BOOLEAN       DEFAULT FALSE,
    manual_lock_time            BOOLEAN       DEFAULT FALSE
);
COMMENT ON TABLE scheduled_tasks IS '排程任务明细';

CREATE TABLE IF NOT EXISTS schedule_settings (
    id                                  BOOLEAN PRIMARY KEY DEFAULT TRUE,
    review_required                     BOOLEAN NOT NULL DEFAULT TRUE,
    manual_adjust_enabled               BOOLEAN NOT NULL DEFAULT TRUE,
    manual_adjust_reason_required       BOOLEAN NOT NULL DEFAULT TRUE,
    publish_with_warnings_allowed       BOOLEAN NOT NULL DEFAULT TRUE,
    auto_release_enabled                BOOLEAN NOT NULL DEFAULT FALSE,
    material_constraint_enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    maintenance_constraint_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    setup_rules_enabled                 BOOLEAN NOT NULL DEFAULT TRUE,
    cleanroom_constraint_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    machine_capability_constraint_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    due_date_optimization_enabled       BOOLEAN NOT NULL DEFAULT TRUE,
    continuous_run_limit_mins           INTEGER NOT NULL DEFAULT 4320,
    continuous_run_enforcement_mode     VARCHAR(30) NOT NULL DEFAULT 'publish_blocker',
    phase2_feasible_tardiness_tolerance_mins INTEGER NOT NULL DEFAULT 0,
    solver_profile                      VARCHAR(30) NOT NULL DEFAULT 'standard',
    solver_time_limit_seconds           DOUBLE PRECISION NOT NULL DEFAULT 120,
    solver_relative_gap_limit           DOUBLE PRECISION NOT NULL DEFAULT 0,
    solver_random_seed                  INTEGER NOT NULL DEFAULT 0,
    solver_num_workers                  INTEGER NOT NULL DEFAULT 8,
    solver_log_search_progress          BOOLEAN NOT NULL DEFAULT FALSE,
    planning_must_schedule_horizon_days INTEGER NOT NULL DEFAULT 3,
    planning_candidate_horizon_days     INTEGER NOT NULL DEFAULT 14,
    candidate_reject_penalty            INTEGER NOT NULL DEFAULT 10000000,
    candidate_max_deferred_count        INTEGER,
    candidate_min_acceptance_ratio      DOUBLE PRECISION NOT NULL DEFAULT 0,
    arc_pruning_enabled                 BOOLEAN NOT NULL DEFAULT FALSE,
    arc_pruning_max_setup_mins          INTEGER NOT NULL DEFAULT 0,
    arc_pruning_top_k_per_order         INTEGER NOT NULL DEFAULT 0,
    screening_due_risk_min_slack_mins   INTEGER NOT NULL DEFAULT 240,
    screening_due_risk_duration_multiplier DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    screening_allowed_order_statuses    TEXT[] NOT NULL DEFAULT ARRAY['PENDING']::TEXT[],
    screening_prohibited_override_codes TEXT[] NOT NULL DEFAULT ARRAY['missing_product','missing_recipe','invalid_order_data','no_eligible_machine','status_not_pending']::TEXT[],
    screening_restricted_override_codes TEXT[] NOT NULL DEFAULT ARRAY['material_not_ready','due_risk']::TEXT[],
    screening_required_positive_order_fields TEXT[] NOT NULL DEFAULT ARRAY['due_date_mins','target_thickness','target_width','total_quantity_kg']::TEXT[],
    manual_adjust_review_delay_threshold_mins INTEGER NOT NULL DEFAULT 0,
    manual_adjust_review_setup_threshold_mins INTEGER NOT NULL DEFAULT 0,
    manual_adjust_review_tardiness_threshold_mins INTEGER NOT NULL DEFAULT 0,
    policy_version                      INTEGER NOT NULL DEFAULT 1,
    updated_by                          VARCHAR(50),
    change_reason                       TEXT,
    updated_at                          TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE schedule_settings IS '排程发布与人工复核开关';

CREATE TABLE IF NOT EXISTS config_change_audit (
    id              SERIAL       PRIMARY KEY,
    config_scope    VARCHAR(40)  NOT NULL,
    config_key      TEXT,
    entity_id       VARCHAR(80),
    policy_version  INTEGER,
    before_state    JSONB,
    after_state     JSONB,
    changed_by      VARCHAR(50),
    reason_text     TEXT,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE config_change_audit IS '全局配置与规则变更审计';
CREATE INDEX IF NOT EXISTS idx_config_change_audit_created
    ON config_change_audit(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS schedule_adjustment_audit (
    id                  SERIAL       PRIMARY KEY,
    run_id              INTEGER      NOT NULL REFERENCES schedule_runs(run_id),
    order_id            VARCHAR(20)  REFERENCES production_orders(order_id),
    action_type         VARCHAR(30)  NOT NULL,
    before_state        JSONB,
    after_state         JSONB,
    reason_code         VARCHAR(50),
    reason_text         TEXT,
    changed_by          VARCHAR(50),
    changed_at          TIMESTAMPTZ  DEFAULT NOW(),
    validation_status   VARCHAR(20)  DEFAULT 'PENDING',
    validation_messages JSONB
);
COMMENT ON TABLE schedule_adjustment_audit IS '人工复核与人工改动审计记录';

CREATE TABLE IF NOT EXISTS manufacturing_queue (
    id                  SERIAL       PRIMARY KEY,
    run_id              INTEGER      NOT NULL REFERENCES schedule_runs(run_id),
    scheduled_task_id   INTEGER      REFERENCES scheduled_tasks(id),
    order_id            VARCHAR(20)  NOT NULL REFERENCES production_orders(order_id),
    machine_id          VARCHAR(20)  NOT NULL REFERENCES machines(machine_id),
    sequence_index      INTEGER      NOT NULL,
    planned_start_time  TIMESTAMPTZ  NOT NULL,
    planned_end_time    TIMESTAMPTZ  NOT NULL,
    queue_status        VARCHAR(30)  NOT NULL DEFAULT 'QUEUED' CHECK (queue_status IN ('QUEUED', 'READY', 'IN_PRODUCTION', 'ON_HOLD', 'COMPLETED', 'CANCELLED')),
    released_by         VARCHAR(50),
    released_at         TIMESTAMPTZ  DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    UNIQUE(run_id, order_id)
);
COMMENT ON TABLE manufacturing_queue IS '确认发布后的制造队列';

CREATE TABLE IF NOT EXISTS schedule_publish_audit (
    id                   SERIAL       PRIMARY KEY,
    run_id               INTEGER      REFERENCES schedule_runs(run_id),
    event_type           VARCHAR(40)  NOT NULL,
    actor                VARCHAR(50),
    selected_order_count INTEGER      NOT NULL DEFAULT 0,
    warning_count        INTEGER      NOT NULL DEFAULT 0,
    queue_row_count      INTEGER      NOT NULL DEFAULT 0,
    details              JSONB,
    created_at           TIMESTAMPTZ  DEFAULT NOW()
);
COMMENT ON TABLE schedule_publish_audit IS '排程发布和撤销审计';

CREATE TABLE IF NOT EXISTS production_actuals (
    id                  SERIAL        PRIMARY KEY,
    scheduled_task_id   INTEGER       REFERENCES scheduled_tasks(id),
    order_id            VARCHAR(20)   NOT NULL REFERENCES production_orders(order_id),
    machine_id          VARCHAR(20)   NOT NULL REFERENCES machines(machine_id),
    actual_start_time   TIMESTAMPTZ,
    actual_end_time     TIMESTAMPTZ,
    actual_setup_mins   INTEGER,
    actual_scrap_kg     NUMERIC(10,2),
    actual_quantity_kg  NUMERIC(10,2),
    quality_status      VARCHAR(20)   CHECK (quality_status IN ('PASSED', 'FAILED', 'ON_HOLD')),
    batch_number        VARCHAR(50),
    operator_id         VARCHAR(50),
    notes               TEXT,
    created_at          TIMESTAMPTZ   DEFAULT NOW()
);
COMMENT ON TABLE production_actuals IS '实际执行反馈（计划vs实际闭环）';

-- ─── 索引 ───────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_orders_status ON production_orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_due_date ON production_orders(due_date);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON production_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON scheduled_tasks(run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_machine_time ON scheduled_tasks(machine_id, start_time);
CREATE INDEX IF NOT EXISTS idx_tasks_order ON scheduled_tasks(order_id);
CREATE INDEX IF NOT EXISTS idx_schedule_runs_lifecycle ON schedule_runs(lifecycle_status, run_id DESC);
CREATE INDEX IF NOT EXISTS idx_maint_machine_time ON machine_maintenance_calendar(machine_id, start_time, end_time);
CREATE INDEX IF NOT EXISTS idx_downtime_machine ON machine_downtime_events(machine_id, start_time);
CREATE INDEX IF NOT EXISTS idx_recipes_product ON recipes(product_type);
CREATE INDEX IF NOT EXISTS idx_inventory_material ON material_inventory(material_grade, status);
CREATE INDEX IF NOT EXISTS idx_actuals_task ON production_actuals(scheduled_task_id);
CREATE INDEX IF NOT EXISTS idx_queue_status ON manufacturing_queue(queue_status, planned_start_time);
CREATE INDEX IF NOT EXISTS idx_schedule_publish_audit_run ON schedule_publish_audit(run_id, created_at DESC);

INSERT INTO schedule_settings (id)
VALUES (TRUE)
ON CONFLICT (id) DO NOTHING;
