# 医疗吹膜 APS Wave 2 执行状态

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`

---

## 1. 当前结论

Wave 2 的 Domain Model、additive schema、官方来源 seed、显式 plant override contract、industrial benchmark profile、material requirement derivation 和 coverage gate 均已实现到分支，但尚未在项目实际 PostgreSQL 实例完成迁移/填充验证，因此当前不能标记 `verified`。

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
- `docs/medical-blownfilm-wave2-industrial-benchmark-profile.md`

### Official / Benchmark / Master Data

- `data/wave2/official_material_catalog.json`
- `data/wave2/industrial_benchmark_policy.json`
- `data/wave2/benchmark_scenarios.json`
- `config/wave2_plant_master_overrides.example.json`

### Database

- `db/migrations/20260828_wave2_domain_schema.sql`
- `db/migrations/20260828_wave2_domain_schema_guardrails.sql`

### Tooling

- `scripts/apply_wave2_domain_schema.py`
- `scripts/seed_wave2_master_data.py`
- `scripts/apply_wave2_plant_overrides.py`
- `scripts/generate_wave2_override_candidates.py`
- `scripts/build_wave2_industrial_benchmark_profile.py`
- `scripts/rebuild_wave2_order_material_requirements.py`
- `scripts/audit_wave2_domain_coverage.py`
- `scripts/audit_wave2_benchmark_readiness.py`

### Tests

- `tests/test_wave2_domain_schema_contract.py`
- `tests/test_wave2_master_data_population_contract.py`
- `tests/test_wave2_override_candidate_generator_contract.py`
- `tests/test_wave2_benchmark_profile_contract.py`

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

### Runtime Candidate Generator

```bash
python scripts/generate_wave2_override_candidates.py
```

从当前 DB 提取机器、recipe、lot 和 legacy physical feasibility，只生成：

```text
apply=false
UNKNOWN rate qualification
SIMULATED low-confidence candidate
```

不自动批准任何 plant master。

---

## 9. Industrial Benchmark Plant Profile

已实现：

```text
data/wave2/industrial_benchmark_policy.json
scripts/build_wave2_industrial_benchmark_profile.py
docs/medical-blownfilm-wave2-industrial-benchmark-profile.md
```

Profile 分类固定：

```text
SIMULATED_WITH_OFFICIAL_ENVELOPE
production_authority = false
```

其原则是：

```text
保留当前 DB 的 machine identity / physical envelope / recipe ratio / inventory ID
只模拟 V2 缺失语义
```

首批模拟语义包括：

```text
process route
machine medical benchmark release
machine feature capability
machine material capability
recipe benchmark release
material benchmark qualification
Machine x Recipe rate
cleaning taxonomy
lot release status
```

Benchmark recipe rate：

```text
legacy machine hourly_output_kg × recipe family factor
```

而不是继续把 machine constant rate 当作所有 recipe 的实际 rate。

如果 recipe ratio/layer validation 不完整：

```text
BLOCK_PROFILE_GENERATION_FOR_RECIPE
```

不会自动均分 ratio。

---

## 10. Order Material Requirement Derivation

已实现：

`scripts/rebuild_wave2_order_material_requirements.py`

计算链：

```text
order.total_quantity_kg
× SUM(recipe_layers.ratio_pct by material)
= material net requirement
```

写入：

```text
order_material_requirements
```

并读取 `v_material_lot_available` 记录 released availability 与 shortage。

当前默认 setup buffer 为 0，因为真正 sequence-dependent startup scrap 尚未进入 V2 Solver；如做保守 benchmark 可显式传入模拟 buffer。

---

## 11. Coverage Gate 已分层

`python scripts/audit_wave2_domain_coverage.py`

区分：

### safe_for_shadow

V2 数据足以开始 Legacy vs V2 双轨诊断，但不改变正式求解结果。

### safe_for_benchmark_hard

允许 `SIMULATED` provenance 满足完整工业 benchmark 数据。

### safe_for_production_hard

只把以下 operational provenance 计入生产 readiness：

```text
PLANT_MASTER
PLANT_SOP
ENGINEERING
LEARNED
```

`SIMULATED` 永远不计入生产 hard readiness。

### Extended Benchmark Gate

新增：

```bash
python scripts/audit_wave2_benchmark_readiness.py
```

额外检查：

```text
active order material requirement coverage
explicit CORONA capability for every active machine
qualified machine material capability
active released recipe -> >= 1 qualified Machine x Recipe rate
released recipe material qualification completeness
released recipe cannot contain EXCLUDED_MEDICAL material
```

Material shortage 是合法业务状态，不作为数据完整性失败；它会作为场景输入报告。

---

## 12. Benchmark Scenario Pack

已实现：

`data/wave2/benchmark_scenarios.json`

固定 14 个场景：

```text
S01 baseline feasible
S02 Machine x Recipe rate differentiation
S03 CORONA scarcity
S04 explicit medical exclusion
S05 unreleased/missing recipe
S06 QC Hold lot
S07 competing lot reservations
S08 process route mismatch
S09 3 -> 5 layer transition
S10 5 -> 3 layer transition
S11 maintenance + breakdown
S12 urgent insert replan
S13 plan stability
S14 recipe revision
```

Expected outcome 定义为领域不变量，而不是固定甘特图结果。

---

## 13. Verification 层级

### 已实现静态 Contract

- `tests/test_wave2_domain_schema_contract.py`
- `tests/test_wave2_master_data_population_contract.py`
- `tests/test_wave2_override_candidate_generator_contract.py`
- `tests/test_wave2_benchmark_profile_contract.py`

保护包括：

```text
additive-only migration
no auto real APPROVED
no supplier fuzzy classification
no LE6601 -> LE6600 alias
no missing ratio fabrication
benchmark source must remain SIMULATED
benchmark cannot import/modify scheduler
Exact negative evidence wins
CORONA must be explicit/scarce
cleaning transition matrix is complete
material requirement derives from ratio
```

### 尚未完成

当前环境没有项目实际 PostgreSQL 连接，也无法从当前执行环境访问 GitHub 网络运行仓库测试，因此尚未真实执行 migration/population/coverage。

数据库状态仍为：

```text
IMPLEMENTED_IN_BRANCH
NOT_DB_VERIFIED
```

---

## 14. Wave 2 工作项状态

### W2-A Schema Additive

`IMPLEMENTED_IN_BRANCH / DB_VERIFY_PENDING`

### W2-B Provenance Seed / Safe Legacy Backfill

`IMPLEMENTED_IN_MIGRATION / DB_VERIFY_PENDING`

### W2-C Domain Coverage Audit

`TOOL_IMPLEMENTED / REAL_OUTPUT_PENDING`

### W2-D Master Data Population

`IMPLEMENTED_IN_BRANCH / DB_POPULATION_PENDING`

### W2-E Industrial Benchmark Plant Profile

`IMPLEMENTED_IN_BRANCH / DB_GENERATION_AND_APPLY_PENDING`

已实现：

```text
benchmark policy
runtime benchmark profile generator
Machine x Recipe differentiated simulated rates
benchmark machine/material/feature qualification
benchmark recipe release gate
benchmark cleaning taxonomy
benchmark lot release
order material requirement derivation
extended benchmark readiness audit
14-scenario deterministic domain pack
```

仍未完成：

```text
real DB migration output
real DB official seed output
real DB benchmark profile generation
real DB benchmark override dry-run/apply
real DB order material requirement rebuild
real DB coverage/readiness report
```

---

## 15. Wave 2 完整 DB 执行顺序

在项目 PostgreSQL 可访问环境执行：

```bash
python scripts/apply_wave2_domain_schema.py
python -m unittest tests.test_wave2_domain_schema_contract
python -m unittest tests.test_wave2_master_data_population_contract
python -m unittest tests.test_wave2_override_candidate_generator_contract
python -m unittest tests.test_wave2_benchmark_profile_contract

python scripts/seed_wave2_master_data.py --dry-run
python scripts/seed_wave2_master_data.py

python scripts/build_wave2_industrial_benchmark_profile.py
python scripts/apply_wave2_plant_overrides.py output/wave2_industrial_benchmark_profile.json --dry-run
python scripts/apply_wave2_plant_overrides.py output/wave2_industrial_benchmark_profile.json

python scripts/rebuild_wave2_order_material_requirements.py --dry-run
python scripts/rebuild_wave2_order_material_requirements.py

python scripts/audit_wave2_domain_coverage.py
python scripts/audit_wave2_benchmark_readiness.py
```

全流程结束后仍要求：

```text
domain_v2_enforcement_mode = LEGACY
```

---

## 16. 进入 Wave 3 的 Gate

Wave 3 只允许先进入 SHADOW 读取/比较链，不能直接开启生产 `HARD`。

最低 Benchmark SHADOW 条件：

```text
safe_for_benchmark_hard = true
safe_for_wave3_shadow_benchmark = true
current enforcement = LEGACY
```

并保留：

```text
safe_for_production_hard = false
```

直到 hard-driving 数据来源被真实 operational provenance 替换并通过 production benchmark。

---

## 17. 当前状态

```text
Wave 1: COMPLETE
Wave 2 Design: COMPLETE
Wave 2 Schema Code: IMPLEMENTED_IN_BRANCH
Wave 2 Official Master Seed: IMPLEMENTED_IN_BRANCH
Wave 2 Plant Override Contract: IMPLEMENTED_IN_BRANCH
Wave 2 Industrial Benchmark Profile: IMPLEMENTED_IN_BRANCH
Wave 2 Material Requirement Derivation: IMPLEMENTED_IN_BRANCH
Wave 2 Benchmark Scenario Pack: IMPLEMENTED_IN_BRANCH
Wave 2 Real DB Migration: PENDING
Wave 2 Real DB Population: PENDING
Wave 2 Real DB Benchmark Readiness: PENDING
Wave 3 Solver: NOT STARTED
```
