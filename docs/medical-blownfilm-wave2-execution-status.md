# 医疗吹膜 APS Wave 2 执行状态

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`

---

## 1. 当前结论

Wave 2 已从“设计”进入“additive schema implementation”，但尚未在项目实际 PostgreSQL 实例上完成迁移验证，因此当前不能标记 `verified`。

当前明确保持：

```text
domain_v2_enforcement_mode = LEGACY
```

所以即使迁移被执行，当前 CP-SAT Solver 的业务结果也不应因为 Wave 2 schema 本身发生变化。

---

## 2. 已完成资产

### Domain / Contract

- `docs/medical-blownfilm-wave2-target-domain-model.md`
- `docs/medical-blownfilm-wave2-schema-compatibility-design.md`
- `docs/medical-blownfilm-wave2-data-contract-crosswalk.md`

### Database

- `db/migrations/20260828_wave2_domain_schema.sql`
- `db/migrations/20260828_wave2_domain_schema_guardrails.sql`

### Tooling

- `scripts/apply_wave2_domain_schema.py`
- `scripts/audit_wave2_domain_coverage.py`

### Test

- `tests/test_wave2_domain_schema_contract.py`

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

迁移不会把 legacy 数据自动升级成医疗可生产状态。

### Recipe

```text
legacy recipe
-> RecipeVersion.status = MIGRATED_UNVERIFIED
-> process_route = UNKNOWN
```

不会自动：

```text
RELEASED
```

### Machine

```text
legacy machine
-> process_route = UNKNOWN
-> medical_release_status = UNKNOWN
-> qualification_status = UNKNOWN
```

### Material

不会根据 supplier/grade fuzzy match 创建 plant APPROVED qualification。

官方资料只会在 exact grade identity 匹配时创建 manufacturer evidence。

### Exact 5101

如果数据库中存在完全相同 grade：

```text
Exact 5101
```

会建立：

```text
EXPLICITLY_EXCLUDED_MEDICAL
```

的官方负向 evidence。

---

## 5. Legacy Rule Provenance 修正

以下现有字段仍然保留：

```text
continuous_run_limit_mins
mandatory_cleaning_duration_minutes
weekly_disinfection_*
gmp_clearance_matrix
```

但 migration 会通过 `entity_source_links` 将当前 legacy 值标记为：

```text
SRC-SIM-LEGACY
LEGACY_ORIGIN
```

明确不再把 72h/周期消杀/按 URGENT-NORMAL-SAMPLE 清场描述为 ISO/FDA 通用固定规则。

未来有真实 `PLANT_SOP` 后再替换其 provenance。

---

## 6. Material Availability Guardrail

`v_material_lot_available.available_quantity_kg` 只有同时满足：

```text
status = IN_STOCK
release_status = RELEASED
not expired
```

才允许大于 0。

以下 lot 即使有物理数量，也返回 0 available：

```text
QC_HOLD
QUARANTINE
REJECTED
TECHNICAL_TRIAL_ONLY
EXPIRED
UNKNOWN
```

同时扣除：

```text
PLANNED / CONFIRMED reservations
```

避免两个订单重复消费同一批 released stock。

---

## 7. Verification 层级

### 已有静态 contract

`tests/test_wave2_domain_schema_contract.py` 用于防止：

- DROP TABLE / DROP COLUMN / RENAME 等 destructive migration；
- 自动把 legacy recipe 标成 RELEASED；
- 自动写 plant material APPROVED；
- supplier-name medical inference；
- recipe ratio 被人为均分；
- process route 被自动猜测；
- Exact 5101 负向 evidence 丢失；
- QC Hold/Expired lot 被算作 available。

### 尚未完成

当前环境没有项目实际 PostgreSQL 连接，因此尚未实际执行：

```bash
python scripts/apply_wave2_domain_schema.py
```

也未获取真实输出：

```bash
python scripts/audit_wave2_domain_coverage.py
```

所以数据库 migration 当前状态为：

```text
IMPLEMENTED_IN_BRANCH
NOT_DB_VERIFIED
```

---

## 8. 实际 DB 验证命令

在项目 PostgreSQL 可访问环境执行：

```bash
python scripts/apply_wave2_domain_schema.py
```

期望至少：

```text
missing_tables: []
missing_views: []
domain_v2_enforcement_mode: LEGACY
material_availability_view_columns includes materially_usable
```

然后：

```bash
python scripts/audit_wave2_domain_coverage.py
```

该命令只做 coverage audit，不改变 mode。

典型迁移后初始结果预计会暴露大量：

```text
MIGRATED_UNVERIFIED recipe
UNKNOWN process route
0 plant material qualification
0 qualified machine-recipe rate
UNKNOWN material lot release
```

这不是 migration 失败，而是 Wave 2 正确暴露此前被默认值掩盖的领域数据缺口。

---

## 9. Wave 2 剩余工作

### W2-A Schema Additive

状态：`IMPLEMENTED_IN_BRANCH / DB_VERIFY_PENDING`

### W2-B Provenance Seed / Safe Legacy Backfill

状态：`IMPLEMENTED_IN_MIGRATION / DB_VERIFY_PENDING`

### W2-C Domain Coverage Audit

状态：`TOOL_IMPLEMENTED / REAL_OUTPUT_PENDING`

### W2-D Master Data Population

尚未开始。

需要根据官方 source registry + 项目模拟工厂数据，逐步填充：

```text
polymer_family
plant material qualification
recipe ratio / process route / release status
machine process route
machine material capability
machine feature capability
machine recipe rate
canonical cleaning group/rules
material lot release status
```

其中：

- 官方数据负责 manufacturer/OEM evidence；
- 模拟工厂资格必须标 `SIMULATED`；
- 不能把 manufacturer healthcare statement 自动升级成 plant approval。

---

## 10. 进入 Wave 3 的 Gate

Wave 3 Solver Correctness 可以开始编码，但 `HARD` mode 不能开启，直到至少完成：

```text
100% active order -> explicit recipe version
100% released recipe -> complete ratio + known process route
100% active machine -> known process route
commercial-medical materials -> explicit plant qualification
candidate machine×recipe -> explicit qualified rate
material lots -> explicit release status
canonical cleaning taxonomy -> populated
```

并通过 deterministic domain benchmark。

---

## 11. 当前推荐状态

```text
Wave 1: COMPLETE
Wave 2 Design: COMPLETE
Wave 2 Schema Code: IMPLEMENTED_IN_BRANCH
Wave 2 Real DB Migration: PENDING
Wave 2 Master Data Population: PENDING
Wave 3 Solver: NOT STARTED
```
