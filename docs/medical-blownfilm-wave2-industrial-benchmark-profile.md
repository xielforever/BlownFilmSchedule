# 医疗吹膜 APS Wave 2 Industrial Benchmark Plant Profile

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`  
**Profile class**: `SIMULATED_WITH_OFFICIAL_ENVELOPE`  
**Production authority**: **false**

---

## 1. 目标

Wave 2 需要两套完全分离的可用性口径：

```text
Production Master
  -> 必须来自 PLANT_MASTER / PLANT_SOP / ENGINEERING / LEARNED

Industrial Benchmark Master
  -> 允许 SIMULATED
  -> 但必须受官方 OEM / 材料 / 标准资料约束
  -> 不能冒充真实工厂参数
```

本 Profile 的目的，是让当前 `BlownFilmSchedule` 的 10 台既有 `LINE-xx`、既有产品、既有 recipe、既有库存，拥有一套完整、可重复、可追溯的 V2 benchmark master data，从而在 Wave 3 做 Legacy vs V2 SHADOW 比较。

本 Profile **不改变 `scheduler.py`，不切换 `domain_v2_enforcement_mode`，不代表真实工厂投产资格**。

---

## 2. 数据来源边界

### 保留自当前项目的事实

运行时直接读取数据库，不重新发明：

```text
machine_id
machine physical width/thickness/layer envelope
legacy hourly_output_kg baseline
product_type
recipe_version_id
recipe layer order
recipe material grade
recipe ratio_pct
inventory_id / lot / quantity / logistics status
active order / quantity / corona requirement
```

### 官方资料负责定义“合理能力维度与边界”

依据：

- W&H VAREX II：层数、材料家族、线宽、挤出机/模头等是独立能力维度；OEM configurable range 不能当作具体 `LINE-xx` 铭牌。
- TekniPlex Healthcare 5-layer：医疗洁净环境、多层共挤、50–200 μm、320–650 mm 可作为窄幅医疗阻隔膜 benchmark archetype 参考，但不是所有机台的事实。
- Rajoo AQUAFLEX：`DOWNWARD_WATER_QUENCH` 是独立 process route，不能与普通 upward air line 混为同一资源。
- Purell / Bormed / SABIC：manufacturer healthcare evidence 可作为材料候选依据，但不能自动转成真实 plant approval。
- EVAL / Plexar / Ultramid：只证明阻隔、粘接、PA 膜加工技术适用；真实医疗资格仍需工厂/产品验证。
- Exact 5101：官方明确排除医疗用途，作为负向控制；benchmark 也不得把它 APPROVED。

官方来源完整清单见：

`docs/medical-blownfilm-official-source-registry.md`

---

## 3. Benchmark Policy

权威配置：

`data/wave2/industrial_benchmark_policy.json`

所有由该配置生成的工厂特定字段统一来源：

```text
source_id   = SRC-SIM-WAVE2-INDUSTRIAL-BENCHMARK
source_type = SIMULATED
class       = SIMULATED_WITH_OFFICIAL_ENVELOPE
production_authority = false
```

因此即使最终 `safe_for_benchmark_hard=true`：

```text
safe_for_production_hard
```

仍必须保持 false，直到相同字段被真实 plant/engineering/learned authority 替换。

---

## 4. Recipe Family 与模拟产能

第一版不建立复杂非线性物理模型。

基线：

```text
Machine legacy hourly_output_kg
        ×
Recipe family factor
        =
MachineRecipeCapability.standard_rate_kg_h
```

Benchmark factors：

| Recipe family | Factor | 说明 |
| --- | ---: | --- |
| PE_MONO | 1.00 | benchmark baseline |
| PE_MULTILAYER | 0.92 | 多层共挤复杂度模拟 |
| BARRIER_EVOH | 0.72 | 高阻隔复杂度模拟 |
| BARRIER_PA | 0.70 | PA 多层复杂度模拟 |
| PP_WATER_QUENCH | 0.90 | 仅在运行时确实存在 PP-dominant recipe 时启用 |

范围：

```text
min_rate = standard × 0.90
max_rate = standard × 1.10
startup_rate_factor = 0.85
confidence = 0.75
```

这些数字属于 **benchmark engineering simulation**，不是 W&H/Rajoo/OEM 公布的具体机台产能。

---

## 5. Process Route

项目仍然坚持 PE-first。

默认：

```text
existing active machines -> UPWARD_AIR
```

只有当运行时 recipe master **确实存在 PP-dominant recipe** 时，生成器才会从现有 physically layer-capable machines 中确定最多两台 benchmark water-quench resources：

```text
DOWNWARD_WATER_QUENCH
```

这只是模拟资源角色分配，不声称 `LINE-xx` 的真实机械结构已经被 OEM/工厂文件证实。

---

## 6. Recipe Release

Benchmark 也不允许通过“为了跑起来”伪造 recipe。

只有同时满足：

```text
layer_count_ok
ratio_complete
ratio_sum_ok
```

才生成：

```text
status = RELEASED
source = SIMULATED benchmark
```

如果 legacy recipe 缺 ratio：

```text
BLOCK_PROFILE_GENERATION_FOR_RECIPE
```

不会：

```text
100 / layer_count
```

自动均分。

这样可以继续保护 Wave 1 已经锁定的“ratio 必须是真正的配方输入”原则。

---

## 7. Material Qualification

Benchmark released recipes 所使用的材料会建立模拟 plant qualification：

```text
APPROVED
source_type = SIMULATED
```

其语义只是：

> 在这个人工构造的 benchmark plant 中，该材料被假定已通过该工厂验证。

不表示厂商 healthcare evidence 自动成为真实 plant approval。

### Fail-safe negative rule

如果材料存在：

```text
EXPLICITLY_EXCLUDED_MEDICAL
```

则 benchmark generator 必须生成：

```text
EXCLUDED_MEDICAL
```

而不是 APPROVED。

因此 Exact 5101 仍然是硬负向测试用例。

---

## 8. Machine Features

Wave 3 第一批真正需要的是 CORONA，因此 benchmark 必须逐机显式建立：

```text
CORONA = true / false
```

不能继续通过字段缺失理解成 false 或 true。

为了制造真实的 scarce-resource 排程冲突：

```text
CORONA enabled target ≈ 70%
```

其他 benchmark feature：

```text
IBC
AUTO_GAUGE
GRAVIMETRIC_DOSING
```

全部带 SIMULATED provenance。

---

## 9. Cleaning Taxonomy

Benchmark groups：

```text
GENERAL_MEDICAL_PE
BARRIER_EVOH
BARRIER_PA
PP_WATER_QUENCH
TECHNICAL_TRIAL
```

注意：这些不是 ISO/FDA 法规定义的枚举。

Benchmark transition matrix 为完整 5×5 有向矩阵，典型值：

```text
PE -> PE             20 min
PE -> barrier        70 min
EVOH -> PA           80 min
PE -> PP            120 min
barrier -> PP       110 min
trial transition     90 min
```

启动废料 benchmark：

```text
8 + 0.45 × change_time_mins
```

这些值的数量级参考此前换型资料，但仍是 `SIMULATED`，不描述为 OEM 标准换型时间或法规要求。

---

## 10. Inventory / Lot

Benchmark 对所有 legacy lot 强制补明确 release status：

```text
IN_STOCK   -> RELEASED
RESERVED   -> RELEASED
IN_TRANSIT -> QC_HOLD
DEPLETED   -> RELEASED (logistics status keeps it unusable)
```

若 grade 被明确排除医疗用途：

```text
release_status -> QC_HOLD
```

真正 APS available quantity 仍由：

```text
v_material_lot_available
```

统一计算，要求：

```text
IN_STOCK + RELEASED + not expired - active reservations
```

---

## 11. Order Material Requirement

新增：

`scripts/rebuild_wave2_order_material_requirements.py`

计算：

```text
order total quantity
× recipe material ratio
= material net quantity
```

同一 recipe 中相同 material 出现在多层时先：

```text
SUM(ratio_pct)
```

再计算物料总需求。

当前默认：

```text
setup_buffer_per_material_kg = 0
```

因为真正 sequence-dependent startup scrap 尚未进入 Wave 3 Solver。

如果专门做保守 benchmark，可显式传：

```bash
--setup-buffer-per-material-kg N
```

但必须记录该值是模拟 buffer，而不是配方比例的一部分。

---

## 12. 执行顺序

在项目 PostgreSQL 环境：

```bash
python scripts/apply_wave2_domain_schema.py
python scripts/seed_wave2_master_data.py

python scripts/build_wave2_industrial_benchmark_profile.py
python scripts/apply_wave2_plant_overrides.py output/wave2_industrial_benchmark_profile.json --dry-run
python scripts/apply_wave2_plant_overrides.py output/wave2_industrial_benchmark_profile.json

python scripts/rebuild_wave2_order_material_requirements.py --dry-run
python scripts/rebuild_wave2_order_material_requirements.py

python scripts/audit_wave2_domain_coverage.py
python scripts/audit_wave2_benchmark_readiness.py
```

整个 Wave 2 执行结束后仍要求：

```text
domain_v2_enforcement_mode = LEGACY
```

---

## 13. Wave 3 Benchmark Scenario Pack

固定场景：

`data/wave2/benchmark_scenarios.json`

包含：

```text
S01 baseline feasible
S02 Machine x Recipe dynamic duration
S03 CORONA scarcity
S04 explicit medical exclusion
S05 recipe not released / missing recipe
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

这些场景的 expected outcome 是**领域不变量**，不是预先规定优化器必须产生某个具体甘特图。

---

## 14. Wave 2 → Wave 3 Gate

进入 Wave 3 SHADOW benchmark 前，执行：

```bash
python scripts/audit_wave2_benchmark_readiness.py
```

至少要求：

```text
safe_for_benchmark_hard = true
active orders 100% have released recipe
active orders 100% have material requirements
active machines 100% have process route
active machines 100% have explicit CORONA capability
released recipe materials have benchmark qualification
active released recipes each have >=1 qualified Machine x Recipe rate
no released recipe contains EXCLUDED_MEDICAL material
lot release status has no UNKNOWN
cleaning taxonomy complete
```

允许存在：

```text
material shortage
```

因为 shortage 本身是一个合法业务状态和 benchmark 场景，不代表主数据不完整。

---

## 15. 当前边界

本阶段仍不做：

```text
修改 scheduler.py
修改 objective
启用 SHADOW/HARD mode
真实生产 APPROVED 声明
真实工厂 SOP 声明
复杂 BUR / melt temperature / rheology 非线性产能模型
卷级母卷/子卷优化
```

这些保持在后续 Wave。
