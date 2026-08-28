# 医疗吹膜 APS Wave 2 执行状态

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`  
**PR**: #1  
**Enforcement invariant**: `domain_v2_enforcement_mode = LEGACY`

---

## 1. 当前结论

Wave 2 的代码/数据契约范围已经推进到：

```text
Domain Model
+ Additive Schema
+ Provenance
+ Official Material Evidence
+ Exact Material Identity Governance
+ Plant/Engineering/Simulated Override Contract
+ Industrial Benchmark Plant Profile
+ Explicit Extruder Position Model
+ Machine x Recipe Rate Model
+ Order Material Requirement Derivation
+ Material Lot Release / Reservation Audit
+ Deterministic Benchmark Scenario Pack
+ Coverage / Readiness Gates
+ Static Contract CI
```

当前状态必须分开描述：

```text
Wave 2 static/domain contracts : VERIFIED
Wave 2 real PostgreSQL migration: PENDING
Wave 2 real DB population       : PENDING
Wave 2 benchmark DB readiness   : PENDING
Wave 3 solver integration       : NOT STARTED
```

当前 CP-SAT 正式行为没有被 Wave 2 修改。

---

## 2. 已验证证据

GitHub Actions：

```text
Workflow: Wave 2 Domain Contracts
Head:     2afa9221cd1daa224ad02392761f2a6104f23aa2
Result:   SUCCESS
```

CI 运行：

```text
https://github.com/xielforever/BlownFilmSchedule/actions/runs/33138521416
```

CI 执行：

```text
tests.test_wave2_domain_schema_contract
tests.test_wave2_master_data_population_contract
tests.test_wave2_override_candidate_generator_contract
tests.test_wave2_benchmark_profile_contract
tests.test_wave2_material_identity_contract
tests.test_wave2_reservation_audit_contract
```

并执行 repository diff guard：

```text
src/scheduler.py must not appear in Wave 2 diff
```

当前 `main...wave2-domain-schema` 差异审计显示 Wave 2 变更集中在：

```text
.github/workflows
config
data/wave2
db/migrations
docs
scripts
tests
```

没有 `src/scheduler.py`。

---

## 3. 官方来源与数据权威边界

继续以：

`docs/medical-blownfilm-official-source-registry.md`

作为证据基线。

核心规则：

```text
manufacturer healthcare evidence != plant APPROVED
OEM configurable envelope != LINE-xx plant nameplate
technical film suitability != medical qualification
SIMULATED benchmark qualification != production qualification
explicit manufacturer medical exclusion > simulated approval
```

Exact 5101 继续作为负向控制：

```text
EXPLICITLY_EXCLUDED_MEDICAL
-> EXCLUDED_MEDICAL
```

Bormed LE6601-PH / `Borealis_LE6601-PH` 不会 alias 到当前有官方证据的 LE6600-PH。

---

## 4. Wave 2 Schema

新增领域表：

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

关键兼容字段：

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

迁移仍然：

```text
ADDITIVE ONLY
LEGACY -> SHADOW -> HARD
```

不执行 breaking rename/drop。

---

## 5. Legacy Safe Backfill

### Recipe

```text
legacy recipe
-> MIGRATED_UNVERIFIED
-> process_route = UNKNOWN
```

### Machine

```text
legacy machine
-> route = UNKNOWN
-> medical release = UNKNOWN
-> qualification = UNKNOWN
```

### Material

官方目录：

```text
EXACT_ALIAS_ONLY
```

不会根据供应商名称猜医疗等级。

### Lot

可用量只允许：

```text
IN_STOCK
AND RELEASED
AND not expired
MINUS PLANNED/CONFIRMED reservation
```

---

## 6. Material Identity Governance

新增：

```text
config/wave2_material_identity_overrides.example.json
scripts/apply_wave2_material_identity_overrides.py
```

用途：为 legacy exact grade 补：

```text
polymer_family
manufacturer optional
commercial_grade optional
melt_index_test_condition optional
```

硬边界：

```text
exact existing material_grade only
no rename
no alias
no medical APPROVED
```

Benchmark generator 现在明确阻断：

```text
polymer_family = NULL / UNKNOWN / OTHER / UNCLASSIFIED
```

不会自动理解成 PE。

因此历史 LE6601 一类材料必须先经过显式 identity review。

---

## 7. Industrial Benchmark Plant Profile

权威配置：

```text
data/wave2/industrial_benchmark_policy.json
```

生成器：

```text
scripts/build_wave2_industrial_benchmark_profile.py
```

固定分类：

```text
source_type = SIMULATED
profile_class = SIMULATED_WITH_OFFICIAL_ENVELOPE
production_authority = false
```

Profile 保留运行时 DB 的：

```text
LINE identity
machine physical envelope
legacy nominal rate baseline
recipe layer/material/ratio
inventory id/lot/quantity
active orders
```

只模拟缺失的 V2 语义。

---

## 8. Machine / Extruder / Feature

Benchmark machine 会显式产生：

```text
process_route
medical benchmark release
qualification_status
CORONA
IBC
AUTO_GAUGE
GRAVIMETRIC_DOSING
```

新增显式 extruder position：

```text
machine.layer_structure = N
-> E1 ... EN
```

其中：

```text
extruder_position = explicit
screw_diameter_mm = NULL unless real authority exists
```

不会把 W&H 通用 screw diameter 列表套到具体 `LINE-xx`。

这为 Wave 3 的：

```text
3 -> 5 layer : EMPTY -> MATERIAL
5 -> 3 layer : MATERIAL -> EMPTY
```

建立了数据底座。

---

## 9. Machine x Recipe Rate

Benchmark 第一版：

```text
standard_rate_kg_h
= legacy machine hourly_output_kg
× recipe family factor
```

当前 benchmark factors：

```text
PE_MONO          1.00
PE_MULTILAYER    0.92
BARRIER_EVOH     0.72
BARRIER_PA       0.70
PP_WATER_QUENCH  0.90
```

这些全部属于 SIMULATED engineering benchmark，不是 OEM 或真实 plant rate。

Profile 同时生成：

```text
min_rate
standard_rate
max_rate
startup_rate_factor
confidence
validation_protocol_id
```

从而终止“所有 recipe 共用 machine constant kg/h”的 benchmark 模型。

---

## 10. Recipe Release Gate

Benchmark recipe 只有满足：

```text
layer_count_ok
ratio_complete
ratio_sum_ok
polymer_family known for every layer
```

才允许：

```text
RELEASED (SIMULATED benchmark)
```

禁止：

```text
missing ratio -> automatic equal split
UNKNOWN material -> assume PE
missing recipe -> Standard_Med_LDPE fallback
```

---

## 11. Order Material Requirement

工具：

```text
scripts/rebuild_wave2_order_material_requirements.py
```

计算：

```text
order quantity
× SUM(recipe ratio by material)
= material net requirement
```

写入：

```text
order_material_requirements
```

并记录：

```text
released_available_kg
shortage_quantity_kg
calculation_version
```

短缺是合法业务状态，不等于数据错误。

---

## 12. Reservation Integrity

新增：

```text
scripts/audit_wave2_material_reservations.py
```

阻断：

```text
reservation material != lot material
reservation against non-IN_STOCK lot
reservation against non-RELEASED lot
reservation against expired lot
lot total reservation > physical quantity
order/material reservation > calculated requirement
```

只报告、不阻断：

```text
under-reservation
```

因为 reservation 允许在 schedule/confirm 后再建立。

---

## 13. Coverage Gates

### Base

```text
scripts/audit_wave2_domain_coverage.py
```

区分：

```text
safe_for_shadow
safe_for_benchmark_hard
safe_for_production_hard
```

其中 `SIMULATED`：

```text
可满足 benchmark
永远不能满足 production authority
```

### Extended

```text
scripts/audit_wave2_benchmark_readiness.py
```

额外检查：

```text
active order material requirement coverage
active machine explicit CORONA
active machine extruder position completeness
machine material qualification
active released recipe -> >=1 qualified Machine x Recipe rate
released recipe material qualification
no EXCLUDED_MEDICAL material in released recipe
no UNKNOWN/OTHER polymer family in released recipe
reservation integrity
```

---

## 14. Benchmark Scenario Pack

```text
data/wave2/benchmark_scenarios.json
```

14 个固定领域场景：

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

Expected outcome 是领域不变量，不绑定某一个固定甘特图。

---

## 15. Wave 2 DB 执行顺序

真实项目 PostgreSQL 环境执行：

```bash
python scripts/apply_wave2_domain_schema.py
```

如有 legacy material identity 缺口，先 review candidate，再使用 exact-grade override：

```bash
python scripts/apply_wave2_material_identity_overrides.py config/<reviewed-material-identity>.json --dry-run
python scripts/apply_wave2_material_identity_overrides.py config/<reviewed-material-identity>.json
```

然后：

```bash
python scripts/seed_wave2_master_data.py --dry-run
python scripts/seed_wave2_master_data.py

python scripts/build_wave2_industrial_benchmark_profile.py
python scripts/apply_wave2_plant_overrides.py output/wave2_industrial_benchmark_profile.json --dry-run
python scripts/apply_wave2_plant_overrides.py output/wave2_industrial_benchmark_profile.json

python scripts/rebuild_wave2_order_material_requirements.py --dry-run
python scripts/rebuild_wave2_order_material_requirements.py

python scripts/audit_wave2_material_reservations.py
python scripts/audit_wave2_domain_coverage.py
python scripts/audit_wave2_benchmark_readiness.py
```

执行前后都必须保持：

```text
domain_v2_enforcement_mode = LEGACY
```

---

## 16. Wave 2 Closure Gate

### Static gate — PASS

```text
Wave 2 contract CI = PASS
Solver diff guard = PASS
```

### DB gate — PENDING

还必须获得真实输出：

```text
schema missing_tables = []
schema missing_views = []
mode = LEGACY
benchmark profile generation completed
material requirements rebuilt
reservation audit safe = true
safe_for_benchmark_hard = true
safe_for_wave3_shadow_benchmark = true
```

允许：

```text
safe_for_production_hard = false
```

因为当前 Benchmark 主数据本身就是 SIMULATED。

---

## 17. 工作项状态

| Work item | Status |
| --- | --- |
| W2-A Schema Additive | STATIC VERIFIED / DB PENDING |
| W2-B Provenance + Safe Legacy Backfill | STATIC VERIFIED / DB PENDING |
| W2-C Coverage Audit | STATIC VERIFIED / REAL OUTPUT PENDING |
| W2-D Master Data Population | STATIC VERIFIED / DB POPULATION PENDING |
| W2-E Industrial Benchmark Profile | STATIC VERIFIED / DB APPLY PENDING |
| W2-F Material Identity + Extruder + Reservation Integrity | STATIC VERIFIED / DB AUDIT PENDING |
| Wave 2 Solver changes | NOT IN SCOPE / NONE |

---

## 18. 当前状态

```text
Wave 1: COMPLETE
Wave 2 Design: COMPLETE
Wave 2 Static Contract CI: VERIFIED
Wave 2 Schema/Data/Benchmark Code: IMPLEMENTED
Wave 2 Real DB Migration: PENDING
Wave 2 Real DB Population: PENDING
Wave 2 Benchmark Readiness Output: PENDING
Wave 3 Solver: NOT STARTED
```

因此 Wave 2 当前不是“未完成设计”，而是：

> **代码与数据契约已完成并通过静态 CI；剩余门槛是实际 PostgreSQL 上的迁移、填充和 readiness 证据。**
