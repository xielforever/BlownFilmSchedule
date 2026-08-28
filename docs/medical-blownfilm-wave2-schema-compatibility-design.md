# 医疗吹膜 APS Wave 2 Schema 兼容迁移设计

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`  
**Scope**: 数据库结构、兼容策略、回填与切换顺序；不修改当前求解器行为。  
**Depends on**: `docs/medical-blownfilm-wave2-target-domain-model.md`

---

## 1. 迁移策略结论

本项目不适合执行一次性 breaking migration。

原因：当前 API、数据库加载器、订单初筛、机器配置页、排程快照和执行闭环都直接依赖以下旧表/字段：

```text
raw_materials
material_inventory
products
recipes
machines
production_orders
machine_current_state
gmp_clearance_matrix
schedule_settings
```

因此 Wave 2 采用：

```text
ADD -> BACKFILL -> SHADOW -> SWITCH -> DEPRECATE
```

而不是：

```text
RENAME/DROP -> rewrite everything
```

### 强制规则

Wave 2 不允许：

- 删除现有主键；
- 重命名现有 API 已使用字段；
- 把 `recipes` 直接替换成 View；
- 修改现有 CP-SAT 输入结构；
- 自动把 legacy 数据标为医疗 `APPROVED`；
- 自动把旧配方标为 `RELEASED`；
- 自动为未知设备猜测 process route。

---

## 2. 迁移模式

新增一个迁移期策略：

```text
domain_v2_enforcement_mode
```

允许值：

```text
LEGACY
SHADOW
HARD
```

语义：

### LEGACY

现有 solver 行为完全不变，新表只写入/展示，不参与 eligibility。

### SHADOW

现有 solver 仍能排程，但同时计算 V2 blocker 并输出 diagnostics，例如：

```text
shadow.process_route_unknown
shadow.material_qualification_unknown
shadow.recipe_ratio_missing
shadow.machine_recipe_rate_missing
```

发布页必须能看到 shadow 风险，但尚不强制阻断旧 benchmark。

### HARD

V2 资格正式进入生产可行域。

进入 HARD 后：

- missing recipe version -> blocked；
- non-released recipe -> blocked；
- medical material qualification invalid -> blocked；
- process route mismatch -> blocked；
- machine recipe rate missing -> blocked；
- released material unavailable -> blocked/deferred；
- legacy fake fallback 禁止。

迁移完成后 `LEGACY` 只能用于测试环境，不允许普通排程用户切回。

---

## 3. 现有表保留与少量扩展

## 3.1 raw_materials

现表保留 `material_grade` 主键。

建议新增：

```sql
ALTER TABLE raw_materials
    ADD COLUMN IF NOT EXISTS manufacturer VARCHAR(100),
    ADD COLUMN IF NOT EXISTS commercial_grade VARCHAR(100),
    ADD COLUMN IF NOT EXISTS polymer_family VARCHAR(30),
    ADD COLUMN IF NOT EXISTS melt_index_test_condition VARCHAR(100),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
```

现有：

```text
material_category
is_special
```

暂不删除，仅标记为 legacy compatibility 字段。

禁止继续用它们判断医疗资格。

---

## 3.2 material_inventory

现表继续作为 material lot / stock 主体。

建议新增：

```sql
ALTER TABLE material_inventory
    ADD COLUMN IF NOT EXISTS release_status VARCHAR(30) DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS received_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS use_before_date TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS supplier_lot VARCHAR(80),
    ADD COLUMN IF NOT EXISTS source_id VARCHAR(80);
```

新增 release 状态约束建议：

```text
RELEASED
QC_HOLD
QUARANTINE
REJECTED
TECHNICAL_TRIAL_ONLY
EXPIRED
UNKNOWN
```

注意：原字段 `status` 继续表示物流状态：

```text
IN_STOCK / IN_TRANSIT / RESERVED / DEPLETED
```

不得把 logistics status 与 quality/release status 合并。

---

## 3.3 machines

旧字段完整保留。

不建议把全部新能力直接塞进 `machines` 宽表；仅新增 migration/audit 辅助字段可选。

建议真正的工艺/资格信息进入独立 capability 表。

旧 `hourly_output_kg` 保留：

```text
legacy nominal output / compatibility fallback
```

进入 HARD 模式后，duration 不再依赖它作为唯一标准产能。

---

## 3.4 production_orders

建议新增：

```sql
ALTER TABLE production_orders
    ADD COLUMN IF NOT EXISTS recipe_version_id VARCHAR(80),
    ADD COLUMN IF NOT EXISTS production_context VARCHAR(30) DEFAULT 'COMMERCIAL_MEDICAL';
```

迁移阶段 `recipe_version_id` 允许 NULL。

HARD 模式要求：

```text
recipe_version_id IS NOT NULL
recipe_version.status = RELEASED
```

`production_context`：

```text
COMMERCIAL_MEDICAL
VALIDATION_TRIAL
ENGINEERING_TRIAL
NON_MEDICAL
```

---

## 3.5 recipes

原 `recipes` 表在 Wave 2/3 均保留。

它变成：

```text
Legacy Recipe Projection
```

原因：当前 DB loader、machine end-state、API 等路径均直接依赖 `recipes`。

策略：

- 新权威配方写 `recipe_versions / recipe_layers`；
- 兼容适配器把当前 RELEASED recipe 投影回 `recipes`；
- 旧读路径在 Wave 3 分批切到新模型；
- 全部消费方切换完成后，才讨论废弃 `recipes`。

不能在当前阶段把 `recipes` 替换成 View，因为现有代码存在 INSERT/UPDATE 语义。

---

## 3.6 gmp_clearance_matrix

保留，不删除。

但从 Wave 2 起明确：

```text
gmp_clearance_matrix = LEGACY compatibility rule
```

不再把 `NORMAL/URGENT/SAMPLE` 描述为真实 GMP cleaning taxonomy。

新权威规则写入：

```text
cleaning_validation_groups
cleaning_transition_rules
```

---

## 4. 新增表设计

## 4.1 provenance_sources

```sql
CREATE TABLE IF NOT EXISTS provenance_sources (
    source_id           VARCHAR(80) PRIMARY KEY,
    source_type         VARCHAR(40) NOT NULL,
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
```

`source_type` 必须限定为项目来源注册表中的枚举。

---

## 4.2 entity_source_links

用于旧表字段、策略字段和多来源实体的 field-level provenance。

```sql
CREATE TABLE IF NOT EXISTS entity_source_links (
    id                  BIGSERIAL PRIMARY KEY,
    entity_type         VARCHAR(60) NOT NULL,
    entity_key          VARCHAR(200) NOT NULL,
    field_name          VARCHAR(100),
    source_id           VARCHAR(80) NOT NULL REFERENCES provenance_sources(source_id),
    source_role         VARCHAR(30) NOT NULL DEFAULT 'PRIMARY',
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`source_role`：

```text
PRIMARY
SUPPORTING
NEGATIVE_CONTROL
PLANT_APPROVAL
LEGACY_ORIGIN
```

用途示例：

```text
entity_type = schedule_setting
entity_key = singleton
field_name = continuous_run_limit_mins
source_id = SRC-SIM-LEGACY-CONTINUOUS-RUN
```

---

## 4.3 material_application_evidence

```sql
CREATE TABLE IF NOT EXISTS material_application_evidence (
    evidence_id         BIGSERIAL PRIMARY KEY,
    material_grade      VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    evidence_type       VARCHAR(40) NOT NULL,
    application_scope   TEXT,
    evidence_status     VARCHAR(40) NOT NULL,
    source_id           VARCHAR(80) NOT NULL REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

这张表记录厂商声明，不直接等于 plant approval。

---

## 4.4 material_qualifications

```sql
CREATE TABLE IF NOT EXISTS material_qualifications (
    qualification_id        BIGSERIAL PRIMARY KEY,
    material_grade          VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    qualification_scope_type VARCHAR(30) NOT NULL DEFAULT 'GLOBAL',
    product_type            VARCHAR(50) REFERENCES products(product_type),
    recipe_version_id       VARCHAR(80),
    process_route           VARCHAR(40),
    qualification_status    VARCHAR(40) NOT NULL,
    condition_expression    JSONB,
    source_id               VARCHAR(80) REFERENCES provenance_sources(source_id),
    approved_by             VARCHAR(80),
    approved_at             TIMESTAMPTZ,
    valid_from              TIMESTAMPTZ,
    valid_to                TIMESTAMPTZ,
    reason                  TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

正式 solver 资格以此表为准，而不是 `material_category`。

---

## 4.5 cleaning_validation_groups

```sql
CREATE TABLE IF NOT EXISTS cleaning_validation_groups (
    group_id             VARCHAR(60) PRIMARY KEY,
    group_name           VARCHAR(120) NOT NULL,
    description          TEXT,
    status               VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    source_id            VARCHAR(80) REFERENCES provenance_sources(source_id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 4.6 recipe_versions

```sql
CREATE TABLE IF NOT EXISTS recipe_versions (
    recipe_version_id             VARCHAR(80) PRIMARY KEY,
    recipe_code                   VARCHAR(80) NOT NULL,
    product_type                  VARCHAR(50) NOT NULL REFERENCES products(product_type),
    revision                      INTEGER NOT NULL,
    process_route                 VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
    layer_count                   INTEGER NOT NULL CHECK (layer_count > 0),
    status                        VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
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
```

建议 partial unique index：每个 product 最多一个 active RELEASED revision。

---

## 4.7 recipe_layers

```sql
CREATE TABLE IF NOT EXISTS recipe_layers (
    recipe_version_id          VARCHAR(80) NOT NULL REFERENCES recipe_versions(recipe_version_id) ON DELETE CASCADE,
    layer_index                INTEGER NOT NULL,
    layer_code                 VARCHAR(20),
    extruder_position          INTEGER NOT NULL,
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
```

迁移期 `ratio_pct` 允许 NULL；RELEASE validation 要求完整并合计 100%。

---

## 4.8 machine_capability_profiles

```sql
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
```

---

## 4.9 machine_extruders

```sql
CREATE TABLE IF NOT EXISTS machine_extruders (
    machine_id          VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    extruder_position   INTEGER NOT NULL,
    extruder_code       VARCHAR(50),
    screw_diameter_mm   NUMERIC(8,2),
    status              VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(machine_id, extruder_position)
);
```

Legacy backfill 仅可根据 `layer_structure` 创建 position 1..N，占位状态标 `AVAILABLE/UNVERIFIED` 时需有 source 标识；不能因此推断每个 position 支持所有材料。

---

## 4.10 machine_material_capabilities

```sql
CREATE TABLE IF NOT EXISTS machine_material_capabilities (
    id                  BIGSERIAL PRIMARY KEY,
    machine_id          VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    extruder_position   INTEGER,
    polymer_family      VARCHAR(30) NOT NULL,
    capability_status   VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(machine_id, extruder_position, polymer_family)
);
```

---

## 4.11 machine_feature_capabilities

```sql
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
```

首个 hard-consumed feature：`CORONA`。

---

## 4.12 machine_recipe_capabilities

```sql
CREATE TABLE IF NOT EXISTS machine_recipe_capabilities (
    machine_id              VARCHAR(20) NOT NULL REFERENCES machines(machine_id),
    recipe_version_id       VARCHAR(80) NOT NULL REFERENCES recipe_versions(recipe_version_id),
    eligibility_status      VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN',
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
```

进入 HARD 模式后：

```text
eligibility_status must permit production
standard_rate_kg_h > 0
quality_status must permit production
```

缺 rate 不允许静默退回 `machines.hourly_output_kg`。

---

## 4.13 cleaning_transition_rules

```sql
CREATE TABLE IF NOT EXISTS cleaning_transition_rules (
    id                  BIGSERIAL PRIMARY KEY,
    from_group_id       VARCHAR(60) NOT NULL REFERENCES cleaning_validation_groups(group_id),
    to_group_id         VARCHAR(60) NOT NULL REFERENCES cleaning_validation_groups(group_id),
    change_time_mins    INTEGER NOT NULL CHECK (change_time_mins >= 0),
    scrap_weight_kg     NUMERIC(10,3),
    enforcement_mode    VARCHAR(30) NOT NULL DEFAULT 'HARD',
    source_id           VARCHAR(80) REFERENCES provenance_sources(source_id),
    valid_from          TIMESTAMPTZ,
    valid_to            TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(from_group_id, to_group_id)
);
```

---

## 4.14 material_lot_reservations

```sql
CREATE TABLE IF NOT EXISTS material_lot_reservations (
    reservation_id          BIGSERIAL PRIMARY KEY,
    inventory_id            INTEGER NOT NULL REFERENCES material_inventory(id),
    order_id                 VARCHAR(20) NOT NULL REFERENCES production_orders(order_id),
    recipe_version_id        VARCHAR(80) REFERENCES recipe_versions(recipe_version_id),
    material_grade           VARCHAR(50) NOT NULL REFERENCES raw_materials(material_grade),
    reserved_quantity_kg     NUMERIC(12,3) NOT NULL CHECK (reserved_quantity_kg > 0),
    reservation_status       VARCHAR(30) NOT NULL DEFAULT 'PLANNED',
    schedule_run_id          INTEGER REFERENCES schedule_runs(run_id),
    expires_at               TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`available stock` 必须扣除 active reservations。

---

## 4.15 order_material_requirements

```sql
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
    calculated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(order_id, recipe_version_id, material_grade, layer_index, calculation_version)
);
```

该表是 derived planning input，不是 ERP 库存账本。

---

## 5. 外键创建顺序

为避免循环依赖，建议 migration 分两步：

### Phase A — 基础表

```text
provenance_sources
cleaning_validation_groups
recipe_versions
recipe_layers
machine_capability_profiles
machine_extruders
machine_material_capabilities
machine_feature_capabilities
machine_recipe_capabilities
material_application_evidence
cleaning_transition_rules
```

### Phase B — 依赖 recipe_version 的资格/订单字段

```text
material_qualifications
production_orders.recipe_version_id FK
material_lot_reservations
order_material_requirements
entity_source_links
```

`material_qualifications.recipe_version_id` 的 FK 应在 recipe_versions 创建后再加。

---

## 6. Legacy 数据回填规则

## 6.1 provenance seed

至少创建：

```text
SRC-SIM-LEGACY
SRC-LEGACY-UNKNOWN
```

同时可把 `medical-blownfilm-official-source-registry.md` 中已核实的官方 source 注册到表中。

### 规则

只有 grade identity 完全匹配官方 source 时，才能自动建立 manufacturer evidence。

禁止 fuzzy match：

```text
contains "Purell"
contains "Borealis"
contains "SABIC"
```

不能作为资格依据。

---

## 6.2 raw_materials

旧材料：

- `material_category` 保留；
- `polymer_family` 无法确定时填 `UNKNOWN`；
- 不创建 `APPROVED` material qualification；
- 可创建 `LEGACY_ORIGIN` source link。

---

## 6.3 recipes -> recipe_versions

每个当前 `product_type` 生成一个迁移版本：

```text
recipe_version_id = LEGACY:<product_type>:R1
status = MIGRATED_UNVERIFIED
process_route = UNKNOWN
source_id = SRC-LEGACY-UNKNOWN
```

每条 legacy recipe row 迁移为 recipe layer。

如果 `ratio_pct IS NULL`：

```text
recipe_layers.ratio_pct = NULL
```

禁止自动均分。

---

## 6.4 machines

每台 machine 创建 capability profile：

```text
process_route = UNKNOWN
medical_release_status = UNKNOWN
qualification_status = UNKNOWN
source_id = SRC-LEGACY-UNKNOWN
```

根据 `layer_structure=N` 可创建 N 个 extruder position 结构占位，但这些 position 只是结构迁移，不证明材料资格。

---

## 6.5 hourly_output_kg

不自动创建 `QUALIFIED machine_recipe_capability`。

若为了 shadow benchmark 建立迁移记录，只能：

```text
eligibility_status = UNKNOWN
standard_rate_kg_h = legacy hourly_output_kg
source_id = SRC-SIM-LEGACY
confidence = low
```

HARD 模式不能消费这种 UNKNOWN capability。

---

## 6.6 gmp_clearance_matrix

旧规则可映射到 legacy cleaning groups：

```text
LEGACY_ORDER_CLASS_NORMAL
LEGACY_ORDER_CLASS_URGENT
LEGACY_ORDER_CLASS_SAMPLE
```

但：

```text
source_id = SRC-SIM-LEGACY or explicit plant source
```

并加醒目标识：

```text
NOT_CANONICAL_CLEANING_TAXONOMY
```

Wave 3 HARD 模式不得继续用这些 legacy groups，除非工厂明确验证这些分类本身就是实际 cleaning taxonomy。

---

## 7. 兼容读取策略

### 7.1 当前 API

在 Wave 2 不改变响应契约：

```text
GET /api/machines
GET /api/orders
rules/config endpoints
schedule endpoints
```

继续按旧字段返回。

未来新增 V2 detail endpoint 或在响应中 additive 增加：

```text
capability_profile
qualification_summary
recipe_version
material_feasibility
provenance
```

但现有前端不应因新增字段破坏。

### 7.2 当前 database loader

Wave 2 暂不改：

```text
_load_recipes_map()
_load_machines_from_db()
ProductionOrderModel
BlownFilmMachineModel
```

Wave 3 再引入 V2 loader：

```text
_load_recipe_versions()
_load_machine_capabilities()
_load_material_qualifications()
_load_order_material_requirements()
```

然后通过 enforcement mode 控制新旧路径。

---

## 8. 双写策略

从 Wave 3 开始，新配方维护流程必须：

```text
write recipe_versions / recipe_layers
        ↓
if version RELEASED
        ↓
project compatibility rows into legacy recipes
```

Legacy `recipes` 不再是 source of truth。

推荐：

```text
V2 authority -> legacy projection
```

禁止：

```text
legacy recipes <-> V2 two-way uncontrolled sync
```

否则会出现版本回写冲突。

---

## 9. Snapshot 兼容设计

现有 `schedule_runs.solver_params` JSONB 可继续承载 input snapshot，无需新增 schedule_run 表。

Wave 3 的 snapshot 至少新增 hash：

```text
recipe_versions
machine_capability_profiles
machine_material_capabilities
machine_feature_capabilities
machine_recipe_capabilities
material_qualifications
material_inventory_release
material_reservations
cleaning_transition_rules
```

Order snapshot 补齐：

```text
customer_id/customer_class-derived priority
corona_req
core_size_inch
recipe_version_id
production_context
```

原则：任何会影响 eligibility、duration、setup、material demand、objective、lock 的字段都必须进入 snapshot/hash。

---

## 10. Index 设计

建议至少建立：

```sql
CREATE INDEX IF NOT EXISTS idx_recipe_versions_product_status
    ON recipe_versions(product_type, status, valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_recipe_layers_version
    ON recipe_layers(recipe_version_id, layer_index);

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
```

---

## 11. 数据完整性规则

不能只依赖 UI 校验。

### Recipe release validation

在 service 层或 transaction 中校验：

```text
count(layers) == layer_count
all ratio_pct not null
sum(ratio_pct) ~= 100
process_route != UNKNOWN
cleaning group resolved where required
all materials exist
```

### Machine recipe qualification

`QUALIFIED` 时要求：

```text
standard_rate_kg_h > 0
source_id present
validity current
machine capability profile not UNKNOWN
```

### Material qualification

`APPROVED` 时要求：

```text
approved_by
approved_at
source_id
scope resolved
```

模拟 benchmark 例外：允许 `source_type=SIMULATED`，但必须显式可见。

---

## 12. 迁移执行顺序

### W2-A — Schema Additive

- 创建新表；
- 增加兼容列；
- 增加 index；
- 默认 `domain_v2_enforcement_mode=LEGACY`；
- 不改变 solver 结果。

### W2-B — Provenance Seed / Legacy Backfill

- 写入官方 source registry；
- 写入 legacy/simulated source；
- 创建 migrated recipe versions；
- 创建 machine profile placeholders；
- 迁移 lot release status 为 UNKNOWN；
- 旧 72h/weekly/gmp rule 绑定来源，禁止继续称通用法规。

### W2-C — Contract Readiness

- 创建 V2 repository/load service 接口；
- 不接 Solver，只做 consistency audit；
- 输出缺失能力/资格覆盖率。

### Wave 3 Entry Gate

只有达到：

```text
recipe coverage ready
machine process-route coverage ready
medical material qualification coverage ready
machine×recipe rate coverage ready
cleaning taxonomy ready
```

才能把 `domain_v2_enforcement_mode` 从 LEGACY 切到 SHADOW。

完成 shadow benchmark 后，才允许 HARD。

---

## 13. 回滚策略

由于 Wave 2 是 additive：

- 旧代码继续使用旧表；
- 新表异常时把 mode 保持 LEGACY；
- 不需要回滚旧数据结构；
- 不删除 V2 数据，只停止消费；
- migration 必须幂等。

这也是选择 additive migration 而不是一次性重构的主要原因。

---

## 14. Wave 2 Schema 封板条件

满足以下条件后，Schema Design 可以进入实现：

- 所有新实体有唯一职责；
- manufacturer evidence 与 plant qualification 分离；
- recipe version/layer/ratio 可独立版本化；
- machine process/material/feature/recipe capability 可表达官方资料和工厂真实数据；
- lot logistics 与 release state 分离；
- reservation 能防止两个订单重复消费同一库存；
- cleaning taxonomy 与 urgency 解耦；
- legacy API 不需要 breaking change；
- migration 可以 LEGACY → SHADOW → HARD 渐进切换；
- provenance 能覆盖旧 72h/weekly cleaning 等模拟规则；
- Wave 3 不需要再次修改核心 schema 才能实现 P0 eligibility/duration/material feasibility。
