# 医疗吹膜 APS Wave 2 执行状态

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`

---

## 1. 当前结论

Wave 2 的 Domain Model、additive schema、官方来源 seed、显式 plant override contract 和 coverage gate 均已实现到分支，但尚未在项目实际 PostgreSQL 实例完成迁移/填充验证，因此当前不能标记 `verified`。

当前明确保持：

```text
domain_v2_enforcement_mode = LEGACY
```

所以当前 CP-SAT Solver 的正式业务行为不会因为 Wave 2 数据模型本身发生变化。

---

## 2. 已完成资产

### Domain / Contract

- `docs/medical-blownfilm-wave2-target-domain-model.md`
- `docs/medical-blownfilm-wave2-schema-compatibility-design.md`
- `docs/medical-blownfilm-wave2-data-contract-crosswalk.md`
- `docs/medical-blownfilm-wave2-master-data-population.md`

### Official / Master Data

- `data/wave2/official_material_catalog.json`
- `config/wave2_plant_master_overrides.example.json`

### Database

- `db/migrations/20260828_wave2_domain_schema.sql`
- `db/migrations/20260828_wave2_domain_schema_guardrails.sql`

### Tooling

- `scripts/apply_wave2_domain_schema.py`
- `scripts/seed_wave2_master_data.py`
- `scripts/apply_wave2_plant_overrides.py`
- `scripts/audit_wave2_domain_coverage.py`

### Tests

- `tests/test_wave2_domain_schema_contract.py`
- `tests/test_wave2_master_data_population_contract.py`

---

## 3. 已实现的 Wave 2 Schema 范围

新增：

```text
provenance_sources
entity_source_links
material_application_evidence
material_qualifications
cleaning_validation_groups
recipe_versions
recipe_layers
machine_capability_profiles
machine_extruders
machine_material_capabilities
machine_feature_capabilities
machine_recipe_capabilities
cleaning_transition_rules
material_lot_reservations
order_material_requirements
```

新增 compatibility fields：

```text
raw_materials.manufacturer
raw_materials.commercial_grade
raw_materials.polymer_family
raw_materials.melt_index_test_condition
material_inventory.release_status
material_inventory.received_at
material_inventory.use_before_date
material_inventory.supplier_lot
material_inventory.source_id
production_orders.recipe_version_id
production_orders.production_context
schedule_settings.domain_v2_enforcement_mode
```

---

## 4. 安全回填策略

### Recipe

```text
legacy recipe
-> MIGRATED_UNVERIFIED
-> process_route = UNKNOWN
```

不会自动 `RELEASED`。

### Machine

```text
legacy machine
-> process_route = UNKNOWN
-> medical_release_status = UNKNOWN
-> qualification_status = UNKNOWN
```

不会从 W&H/Rajoo/TekniPlex 通用能力范围猜 `LINE-xx` 的实际配置。

### Material

官方 catalog 采用：

```text
EXACT_ALIAS_ONLY
```

只填：

```text
manufacturer identity
typical official property
manufacturer application evidence
```

不会把 Healthcare statement 自动升级成 plant `APPROVED`。

### Exact 5101

明确厂商负向证据允许建立：

```text
EXPLICITLY_EXCLUDED_MEDICAL
EXCLUDED_MEDICAL
```

作为 fail-safe negative qualification。

### Bormed LE6601-PH

历史项目可能出现：

```text
Borealis_LE6601-PH
```

本轮不会把它 alias 到当前可验证的：

```text
Bormed LE6600-PH
```

而是进入 identity watchlist：

```text
KEEP_UNVERIFIED_NOT_ALIASED_TO_LE6600
```

---

## 5. Legacy Rule Provenance

现有：

```text
continuous_run_limit_mins
mandatory_cleaning_duration_minutes
weekly_disinfection_*
gmp_clearance_matrix
```

继续保留行为兼容，但绑定：

```text
SRC-SIM-LEGACY
LEGACY_ORIGIN
```

不再把 72h/周期消杀/URGENT-NORMAL-SAMPLE 清场矩阵表述成 ISO/FDA 通用固定规则。

---

## 6. Material Availability Guardrail

`v_material_lot_available.available_quantity_kg` 只有同时满足：

```text
status = IN_STOCK
release_status = RELEASED
not expired
```

才允许大于 0，并扣除：

```text
PLANNED / CONFIRMED reservations
```

以下状态物理有货也不可用：

```text
QC_HOLD
QUARANTINE
REJECTED
TECHNICAL_TRIAL_ONLY
EXPIRED
UNKNOWN
```

---

## 7. W2-D 官方材料 catalog

当前包含：

```text
Purell PE 2420 F
Purell PE 3020K
Purell SP170G
Bormed DM55pharm
Bormed LE6600-PH
SABIC HDPE PCGF0863
EVAL F171B
Plexar PX3236
Ultramid B36 L
Exact 5101
```

其中：

- Healthcare grades -> manufacturer evidence only；
- EVOH/TIE/PA -> technical film evidence only；
- Exact 5101 -> explicit medical exclusion；
- LE6601-PH -> legacy identity watchlist，不继承 LE6600 证据。

---

## 8. Population Tooling

### 官方 evidence seed

```bash
python scripts/seed_wave2_master_data.py --dry-run
python scripts/seed_wave2_master_data.py
```

可选：

```bash
--insert-missing-official-materials
--bootstrap-legacy-rate-shadow
```

Legacy rate shadow 只产生：

```text
eligibility_status = UNKNOWN
source = SRC-SIM-LEGACY
confidence = 0.10
```

不能作为 `QUALIFIED` rate。

### Plant Override

模板：

```text
config/wave2_plant_master_overrides.example.json
```

执行：

```bash
python scripts/apply_wave2_plant_overrides.py <config.json> --dry-run
python scripts/apply_wave2_plant_overrides.py <config.json>
```

模板所有数据均：

```json
"apply": false
```

避免误把示例值写入数据库。

---

## 9. Coverage Gate 已分层

`python scripts/audit_wave2_domain_coverage.py`

现在区分：

### safe_for_shadow

V2 数据足以开始：

```text
Legacy vs Domain V2
```

双轨诊断，但不改变正式求解结果。

### safe_for_benchmark_hard

允许 `SIMULATED` provenance 满足完整工业 benchmark 数据。

用于：

```text
算法研发
确定性冲突测试
约束回归
性能测试
```

### safe_for_production_hard

只把以下 operational provenance 计入生产 readiness：

```text
PLANT_MASTER
PLANT_SOP
ENGINEERING
LEARNED
```

`SIMULATED` 不计入生产 hard readiness。

---

## 10. Verification 层级

### 已实现静态 Contract

`tests/test_wave2_domain_schema_contract.py`

保护：

- additive-only migration；
- 不自动 RELEASE recipe；
- 不自动 APPROVED material；
- 不猜 process route；
- material lot availability guardrail。

`tests/test_wave2_master_data_population_contract.py`

保护：

- Python population script 可解析；
- exact alias 唯一；
- Healthcare evidence 不自动 APPROVED；
- 只有明确负向证据可自动 EXCLUDED；
- LE6601 不 alias LE6600；
- official missing grade 默认不自动插入；
- legacy rate bootstrap 只能 UNKNOWN shadow；
- RELEASED recipe 必须有 approval + ratio validation；
- override example 全部 apply=false。

### 尚未完成

当前环境没有项目实际 PostgreSQL 连接，因此尚未真实执行：

```bash
python scripts/apply_wave2_domain_schema.py
python scripts/seed_wave2_master_data.py
python scripts/audit_wave2_domain_coverage.py
```

数据库状态仍为：

```text
IMPLEMENTED_IN_BRANCH
NOT_DB_VERIFIED
```

---

## 11. Wave 2 工作项状态

### W2-A Schema Additive

`IMPLEMENTED_IN_BRANCH / DB_VERIFY_PENDING`

### W2-B Provenance Seed / Safe Legacy Backfill

`IMPLEMENTED_IN_MIGRATION / DB_VERIFY_PENDING`

### W2-C Domain Coverage Audit

`TOOL_IMPLEMENTED / REAL_OUTPUT_PENDING`

### W2-D Master Data Population

`IMPLEMENTED_IN_BRANCH / DB_POPULATION_PENDING`

已实现：

```text
official material catalog
exact identity matching
manufacturer evidence seed
LE6601 identity watchlist
explicit plant override contract
machine/material/feature/rate/cleaning/lot override loader
benchmark vs production provenance gate
```

未完成：

```text
real DB seed output
explicit simulated/plant machine route values
explicit released recipe values
explicit machine x recipe qualified rates
explicit lot release state
real coverage output
```

---

## 12. 进入 Wave 3 的 Gate

Wave 3 Solver Correctness 可以开始写 SHADOW 读取链，但不得直接开启 `HARD`。

最低 SHADOW 条件：

```text
active order -> recipe_version traceability complete
active machine -> capability profile exists
Domain V2 source/provenance schema available
current enforcement remains LEGACY
```

工业 Benchmark HARD 条件还要求：

```text
released recipe complete ratio + route
known machine route
explicit benchmark material qualification
explicit qualified machine x recipe rate
explicit lot release
canonical cleaning taxonomy
```

真实 Production HARD 还必须将上述 hard-driving 数据来源替换/覆盖为 operational provenance。

---

## 13. 当前状态

```text
Wave 1: COMPLETE
Wave 2 Design: COMPLETE
Wave 2 Schema Code: IMPLEMENTED_IN_BRANCH
Wave 2 Official Master Seed: IMPLEMENTED_IN_BRANCH
Wave 2 Plant Override Contract: IMPLEMENTED_IN_BRANCH
Wave 2 Real DB Migration: PENDING
Wave 2 Real DB Population: PENDING
Wave 3 Solver: NOT STARTED
```
