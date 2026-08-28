# 医疗吹膜 APS Wave 2 数据契约 Crosswalk

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`  
**Purpose**: 明确 legacy 数据如何映射到 V2 Domain Model，以及 Wave 3 每个求解输入的权威来源。

---

## 1. 为什么需要独立 Crosswalk

仅仅创建新表还不够。

如果同一个概念同时存在：

```text
machines.hourly_output_kg
machine_recipe_capabilities.standard_rate_kg_h
```

但没有定义哪一个是权威值，系统会形成第二套不一致的数据源。

因此本文件定义：

```text
Legacy Source
Target Source of Truth
Compatibility Projection
Shadow Validation
Hard Enforcement
```

每一个字段都必须有明确切换规则。

---

## 2. Enforcement Mode 对数据契约的影响

| Mode | 读取权威源 | V2 缺失行为 | 发布影响 |
| --- | --- | --- | --- |
| LEGACY | 当前旧模型 | 只记录 coverage | 无变化 |
| SHADOW | 旧模型排程 + V2 并行检查 | 输出 diagnostic | 默认警告/可配置 blocker |
| HARD | V2 模型 | 不允许静默 fallback | 硬阻断或不可发布 |

HARD 模式的核心原则：

> 未知不是合格，缺失不是默认值。

---

## 3. Material Crosswalk

| 概念 | Current | V2 Source of Truth | LEGACY | SHADOW | HARD |
| --- | --- | --- | --- | --- | --- |
| Grade ID | `raw_materials.material_grade` | 同字段 | 使用 | 使用 | 使用 |
| Manufacturer | 文本/牌号推断 | `raw_materials.manufacturer` | 可空 | 缺失提示 | 资格判断不依赖品牌猜测 |
| Polymer family | 无稳定字段 | `raw_materials.polymer_family` | 不参与 | coverage | material capability hard gate |
| 厂商医疗声明 | `material_category` 推断 | `material_application_evidence` | 旧行为不变 | 比较并报警 | 只作 evidence，不直接 approve |
| 工厂医疗批准 | 无 | `material_qualifications` | 不参与 | coverage/diagnostic | hard gate |
| Medical exclusion | 无显式模型 | application evidence / qualification | 不参与 | critical warning | hard block |
| Melt index | `melt_index` | 保留 | 使用/展示 | 使用 | 非首批 hard gate |
| Density | `density` | 保留 | 使用/展示 | 使用 | 非首批 hard gate |

### 负向证据优先规则

如果存在：

```text
EXPLICITLY_EXCLUDED_MEDICAL
```

则商业医疗订单必须阻断，即使同时存在 generic technical film capability。

---

## 4. Recipe Crosswalk

| 概念 | Current | V2 Source of Truth | HARD 行为 |
| --- | --- | --- | --- |
| 产品关联 | `recipes.product_type` | `recipe_versions.product_type` | 必须存在 RELEASED version |
| Recipe identity | 按 product 隐式 | `recipe_version_id` | 订单必须引用 exact version |
| Revision | 无 | `recipe_versions.revision` | snapshot/hash 必须包含 |
| Layer count | materials list 长度 | `recipe_versions.layer_count` | 与 layer rows 一致 |
| Layer order | `recipes.layer` | `recipe_layers.layer_index/extruder_position` | position-aware |
| Material | `recipes.material_grade` | `recipe_layers.material_grade` | qualification check |
| Ratio | DB 有但 loader 丢失 | `recipe_layers.ratio_pct` | RELEASED 时必须完整 |
| Process route | 无 | `recipe_versions.process_route` | hard gate |
| Cleaning class | 订单 class 间接使用 | `cleaning_validation_group_id` | 清场 lookup key |
| Cleanroom requirement | product/order legacy label | recipe canonical requirement + order requirement | 统一 canonical comparison |

### Missing recipe

Current：

```text
fallback -> Standard_Med_LDPE
```

Target：

```text
NO RECIPE
-> screening.blocked_data_error
-> diagnostic missing_recipe
```

任何 mode 最终都不应把 synthetic material 当作正式配方；Wave 3 首项即移除生产 fallback。

---

## 5. Machine Crosswalk

| 概念 | Current | V2 Source of Truth | HARD 行为 |
| --- | --- | --- | --- |
| Machine ID | `machines.machine_id` | 同字段 | 保留 |
| Width | machines min/max | machines | hard |
| Thickness | machines min/max | machines | hard |
| Layer capacity | `layer_structure` | machines + extruder model | hard |
| Process route | 无 | `machine_capability_profiles.process_route` | hard |
| Cleanroom | `cleanroom_level` | capability profile canonical cleanroom | hard |
| Medical release | 无 | capability profile | hard |
| Polymer capability | 无 | machine_material_capabilities | hard |
| Extruder-position capability | 无 | machine_extruders + material capability | hard when relevant |
| Corona equipment | 无 | machine_feature_capabilities.CORONA | hard if order requires |
| IBC / gauge / dosing | 无 | feature capabilities | only hard for recipes that require feature |
| Nominal output | `hourly_output_kg` | legacy compatibility only | no silent use |
| Recipe-specific output | 无 | machine_recipe_capabilities.standard_rate_kg_h | duration authority |

---

## 6. Duration Contract

### Current

```text
minutes = ceil(order_qty / machines.hourly_output_kg × 60)
```

### V2

```text
cap = MachineRecipeCapability(machine_id, recipe_version_id)

require:
  eligibility_status permitted
  quality_status permitted
  standard_rate_kg_h > 0
  current timestamp in validity range

minutes = ceil(net_production_kg / cap.standard_rate_kg_h × 60)
```

### No fallback rule

HARD 模式：

```text
machine_recipe rate missing
!= use machines.hourly_output_kg

machine_recipe rate missing
= machine/order pair not eligible
```

SHADOW 模式可以计算：

```text
legacy_duration
v2_duration nullable
```

并记录 coverage gap。

---

## 7. Material Availability Contract

### Current

```text
production_orders.material_available_time
```

它仍保留，作为兼容/汇总字段。

### V2 authority

```text
RecipeLayer ratio
    ↓
OrderMaterialRequirement
    ↓
MaterialInventory logistics status
AND MaterialInventory release status
    ↓
Existing Reservations
    ↓
Inbound timing
    ↓
Earliest Material Feasible Time
```

### Released stock 定义

可用库存最小条件：

```text
material_inventory.status = IN_STOCK
release_status = RELEASED
use_before_date not expired
quantity - active_reservations > 0
```

以下均不可计入商业医疗 available stock：

```text
QC_HOLD
QUARANTINE
REJECTED
TECHNICAL_TRIAL_ONLY
EXPIRED
UNKNOWN
```

### material_available_time 的新定位

V2 计算后，可以把所有 grade 的 earliest feasible time 聚合成：

```text
order.material_available_time
= max(material requirement earliest feasible time)
```

因此该字段从“手工单值 source of truth”变为“兼容汇总/可人工 override 且有审计”的字段。

---

## 8. Setup Contract

### Material transition

Current：

```text
recipe_materials[]
min(len(from), len(to))
```

V2：

```text
RecipeLayer.extruder_position
MachineExtruder.position
```

先构造固定 machine position state：

```text
Position 1..N
```

每个位置状态：

```text
EMPTY
or material_grade
```

transition types：

```text
EMPTY -> EMPTY
EMPTY -> MATERIAL
MATERIAL -> EMPTY
MATERIAL_A -> MATERIAL_A
MATERIAL_A -> MATERIAL_B
```

Setup 时间仍可：

```text
MAX(position setup time)
+ width
+ thickness
+ corona
+ core
+ cleaning transition
```

Scrap 按企业规则逐 position Sum 或 rule-specific calculation。

---

## 9. Cleaning Crosswalk

| Current | Target |
| --- | --- |
| `gmp_clearance_matrix.from_order_class` | `cleaning_transition_rules.from_group_id` |
| `gmp_clearance_matrix.to_order_class` | `cleaning_transition_rules.to_group_id` |
| `URGENT/NORMAL/SAMPLE` | recipe/product cleaning validation group |
| “GMP” 默认描述 | source-backed plant cleaning rule |

### 订单优先级继续保留

```text
order_class = URGENT / NORMAL / SAMPLE
```

只用于：

```text
priority / tardiness objective
```

不用于 cleaning qualification。

---

## 10. Continuous Run / Weekly Sanitation Crosswalk

Current fields：

```text
continuous_run_limit_mins
mandatory_cleaning_duration_minutes
weekly_disinfection_*
```

不删除。

新增 field-level provenance：

```text
entity_source_links
```

无 plant SOP 时：

```text
source_type = SIMULATED
regulatory_claim = false
```

有工厂 SOP 时：

```text
source_type = PLANT_SOP
source revision / effective date
```

Solver hard/publish behavior由工厂策略决定，但文档/UI 不再称其为 ISO/FDA 通用固定要求。

---

## 11. Order Contract

### 新增 Solver-relevant fields

```text
recipe_version_id
production_context
```

现有字段继续保留：

```text
order_id
customer_id/customer_class
width
thickness
quantity
cleanroom
order_class
corona_req
core_size_inch
due_date
priority_override
```

### production_context

决定 medical qualification policy：

```text
COMMERCIAL_MEDICAL
  -> only APPROVED material/recipe/machine capability

VALIDATION_TRIAL
  -> may allow TECHNICAL_TRIAL_ONLY according to policy

ENGINEERING_TRIAL
  -> broader engineering eligibility, never auto-publish as commercial

NON_MEDICAL
  -> medical qualification rules not automatically applied
```

---

## 12. Snapshot Contract

V2 input snapshot 必须回答：

> 如果任何影响本次排程可行性、时长、换型、物料、目标函数的数据发生变化，旧 draft 能否被识别为 stale？

### Order hash

必须包含：

```text
product_type
recipe_version_id
production_context
target_width
target_thickness
total_quantity_kg
cleanroom_req
customer/customer class effect
order_class
corona_req
core_size_inch
due_date
material override
priority_override
status
```

### Process hash

```text
recipe_version header
all recipe layers
ratios
process route
cleaning group
status / validity
```

### Machine capability hash

```text
physical machines fields
machine profile
extruders
material capability
feature capability
machine recipe capability/rate
```

### Material hash

```text
qualification
released lot stock
reservation state
```

### Rule hash

```text
material transition
physical setup
cleaning transition
maintenance
continuous-run / sanitation policy provenance
```

---

## 13. V2 Solver Input Snapshot 目标结构

Wave 3 内存对象不应继续只传：

```text
order.recipe_materials: List[str]
machine.hourly_output_kg
```

目标不可变 snapshot：

```yaml
order:
  order_id: ORD-001
  product_type: IV_BAG_FILM
  recipe_version_id: RCP-IV-R3
  production_context: COMMERCIAL_MEDICAL
  quantity_kg: 800
  target_width_mm: 800
  target_thickness_um: 100
  corona_required: true
  core_size_inch: 3

recipe:
  process_route: DOWNWARD_WATER_QUENCH
  cleaning_group: PP_WQ_MEDICAL
  layers:
    - position: 1
      material_grade: GRADE-A
      polymer_family: PP
      ratio_pct: 30
    - position: 2
      material_grade: GRADE-B
      polymer_family: PP
      ratio_pct: 40
    - position: 3
      material_grade: GRADE-A
      polymer_family: PP
      ratio_pct: 30

machine_candidate:
  machine_id: BF-06
  process_route: DOWNWARD_WATER_QUENCH
  standard_rate_kg_h: 170
  capability_source: PLANT_MASTER
  corona_capable: true

material_feasibility:
  feasible: true
  earliest_feasible_mins: 240
  requirements:
    - material_grade: GRADE-A
      gross_qty_kg: 485
      released_available_kg: 920
    - material_grade: GRADE-B
      gross_qty_kg: 325
      released_available_kg: 600
```

具体数值仅是结构示例，不是官方工艺值。

---

## 14. V2 Diagnostic Contract

每个 blocker 至少返回：

```text
code
entity_type
entity_id
machine_id nullable
source/confidence
actual
required
recommendation
```

首批新增 codes：

```text
eligibility.recipe_missing
eligibility.recipe_not_released
eligibility.process_route_mismatch
eligibility.machine_medical_release_missing
eligibility.material_family_unsupported
eligibility.material_medical_excluded
eligibility.material_qualification_missing
eligibility.feature_corona_missing
eligibility.machine_recipe_not_qualified
capacity.machine_recipe_rate_missing
material.released_stock_shortage
material.qc_hold_only
setup.extruder_transition_rule_missing
cleaning.transition_rule_missing
provenance.hard_rule_source_missing
```

---

## 15. Compatibility Projection Rules

### V2 -> legacy recipes

只投影当前 RELEASED recipe：

```text
recipe_layers
-> recipes(product_type, layer, material_grade, ratio_pct)
```

### V2 -> legacy order material ready time

```text
max(order_material_requirements.earliest_feasible_time)
-> production_orders.material_available_time
```

### V2 -> legacy machine output

不建议反向覆盖 `machines.hourly_output_kg`。

因为：

```text
machine_recipe rate != one machine constant rate
```

legacy machine output 仅作为 UI/兼容参考值。

---

## 16. Wave 3 读取切换顺序

推荐：

1. Recipe loader；
2. Material qualification loader；
3. Machine capability loader；
4. Machine×Recipe rate loader；
5. Material feasibility service；
6. Screening V2 shadow；
7. Duration cache V2；
8. Setup position normalization；
9. Snapshot V2；
10. HARD mode。

不要先改 objective；先保证 feasibility 和 duration 正确。

---

## 17. Crosswalk 封板条件

- 每个 current solver-relevant field 有目标 authority；
- legacy 和 V2 冲突时有明确 precedence；
- HARD 模式无任何隐式默认医疗资格；
- rate 缺失无 silent fallback；
- recipe 缺失无 synthetic fallback；
- material shortage 可解释到 grade/lot；
- cleaning rule 不再由 urgency 决定；
- snapshot 能检测新模型变化；
- diagnostics 能解释哪个资格层导致 blocked；
- 旧 API 在 Wave 2 不 breaking。
