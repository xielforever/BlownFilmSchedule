# 医疗吹膜 APS Wave 2-D 主数据填充方案

**Generated**: 2026-08-28  
**Status**: active  
**Branch**: `wave2-domain-schema`  
**Scope**: 官方材料证据、Legacy 安全绑定、Plant/Engineering/Simulated Override、Coverage Gate。  
**Depends on**: `docs/medical-blownfilm-wave2-target-domain-model.md`

---

## 1. 目标

Wave 2-D 不负责“把所有 UNKNOWN 填满”，而是建立一条可审计的数据填充链：

```text
官方厂商事实
    -> Manufacturer Evidence

现有 Legacy 数据
    -> MIGRATED_UNVERIFIED / UNKNOWN / LEGACY_COMPAT

工厂/工程/历史实绩/明确模拟数据
    -> Plant Override

Coverage Audit
    -> SHADOW / BENCHMARK_HARD / PRODUCTION_HARD readiness
```

核心原则：

> 宁可保留 UNKNOWN，也不把相似牌号、通用 OEM 能力或厂商 Healthcare 声明伪装成工厂已批准事实。

---

## 2. 本轮新增资产

### 官方材料目录

`data/wave2/official_material_catalog.json`

用于保存：

- exact grade identity / exact aliases；
- manufacturer；
- polymer family；
- 官方典型 MFR / density（仅官方明确时）；
- manufacturer application evidence；
- source_id；
- 医疗资格自动化动作边界。

### 官方证据 seed

`python scripts/seed_wave2_master_data.py`

默认行为：

```text
match existing raw_materials only
exact aliases only
fill only null/blank official reference fields
insert manufacturer evidence
bind order -> unique migrated recipe_version where unambiguous
keep domain_v2_enforcement_mode = LEGACY
```

默认不会：

```text
插入所有缺失官方材料
自动 APPROVED
自动 RELEASED recipe
自动猜 machine process route
自动创建 QUALIFIED machine-recipe rate
把 LE6601 改名为 LE6600
```

### Plant Override

`config/wave2_plant_master_overrides.example.json`

`python scripts/apply_wave2_plant_overrides.py <config.json>`

这是唯一用于填充以下 plant-specific 数据的入口：

```text
machine process route
machine medical release / qualification
machine material capability
machine feature capability
recipe release / process route
plant material qualification
machine x recipe standard rate
cleaning validation group / transition rule
material lot release
```

Generic OEM / material manufacturer source不能作为该文件的 plant-specific authority。

---

## 3. 官方材料目录 v1

| Grade | Polymer | 官方用途证据 | 典型参考 | Wave 2 自动动作 |
| --- | --- | --- | --- | --- |
| Purell PE 2420 F | LDPE | Healthcare / pharmaceutical film | MFR 0.75 @190°C/2.16kg; density 0.923 | evidence only |
| Purell PE 3020K | LDPE | Healthcare / pharmaceutical film | MFR 4.0; density 0.928 | evidence only |
| Purell SP170G | PP | Healthcare blown film / BFS / IV-bag film layers | MFR 1.5 @230°C; density 0.90 | evidence only |
| Bormed DM55pharm | PP | Healthcare evaluation; water-quench film route | MFR 2.8 @230°C; density 0.90 | evidence only |
| Bormed LE6600-PH | LDPE | Current Borealis medical-use compliance statement | MFR 1.5 @190°C; density 0.919; EP/USP/DMF refs | evidence only |
| SABIC HDPE PCGF0863 | HDPE | Healthcare packaging/device reference | MFR 8; density 0.964 | evidence only |
| EVAL F171B | EVOH | Barrier-film technical source | MFR 1.6; density 1.19; Tm 183°C; OTR reference | technical evidence only |
| Plexar PX3236 | TIE | PA/EVOH tie layer, blown/cast/coex | MFR 2.0; density 0.922 | technical evidence only |
| Ultramid B36 L | PA6 | blown film / casing / water-cooled film | Tm 220°C | technical evidence only |
| Exact 5101 | ethylene plastomer | manufacturer explicitly excludes medical use | technical blown-film grade | global EXCLUDED_MEDICAL allowed |

其中 Healthcare evidence 均不等于企业最终批准。

---

## 4. LE6601-PH 与 LE6600-PH 身份治理

当前项目历史测试数据可见 `Borealis_LE6601-PH` 形式。

本轮查证结果：

- `Bormed LE6601-PH` 是历史上存在过的 Borealis/Bormed grade；
- 2026-08-28 未确认到当前 Borealis 官方产品页；
- 第三方历史数据库仍可找到该 grade，并存在 discontinued 标记；
- 当前 Borealis 可以直接核验的是 `Bormed LE6600-PH`，并有 2025-11-18 Edition 22 医疗使用合规声明。

因此：

```text
Borealis_LE6601-PH
!=
Bormed LE6600-PH
```

迁移规则：

```text
LE6601 exact legacy identity
-> KEEP_UNVERIFIED_NOT_ALIASED_TO_LE6600
```

除非后续获得：

```text
historical Borealis TDS
approved supplier certificate
plant approved material master
```

否则不得继承 LE6600 的官方证据。

---

## 5. Exact Alias Policy

材料 catalog 只做 representation-level normalization：

```text
trim whitespace
collapse repeated whitespace
case-insensitive compare
```

不做：

```text
substring fuzzy match
supplier-name inference
edit distance
family-name inference
nearest product replacement
```

例如：

```text
Purell_PE_3020K
```

可以是明确登记的 exact alias；但：

```text
contains "Purell"
```

绝不是医疗资格规则。

---

## 6. 官方 Evidence Seed 命令

先 dry-run：

```bash
python scripts/seed_wave2_master_data.py --dry-run
```

确认 summary 后执行：

```bash
python scripts/seed_wave2_master_data.py
```

### 可选：插入 catalog 中数据库尚不存在的官方 grade

默认关闭。

```bash
python scripts/seed_wave2_master_data.py \
  --insert-missing-official-materials \
  --dry-run
```

只有在你希望 benchmark 主数据正式引入这些 grade 时再开启。

### 可选：Legacy rate shadow bootstrap

```bash
python scripts/seed_wave2_master_data.py \
  --bootstrap-legacy-rate-shadow \
  --dry-run
```

它只会创建：

```text
eligibility_status = UNKNOWN
standard_rate_kg_h = legacy machines.hourly_output_kg
source = SRC-SIM-LEGACY
confidence = 0.10
```

用途仅为后续 Wave 3 SHADOW 对照。

不能：

```text
当成 QUALIFIED Machine×Recipe rate
满足工业 rate coverage
用于 PRODUCTION_HARD
```

---

## 7. Plant Override 命令

复制模板：

```text
config/wave2_plant_master_overrides.example.json
```

到实际配置文件，例如：

```text
config/wave2_plant_master_overrides.local.json
```

然后先运行：

```bash
python scripts/apply_wave2_plant_overrides.py \
  config/wave2_plant_master_overrides.local.json \
  --dry-run
```

再正式提交：

```bash
python scripts/apply_wave2_plant_overrides.py \
  config/wave2_plant_master_overrides.local.json
```

每一条数据必须显式：

```json
"apply": true
```

模板全部为 `false`，避免误操作。

---

## 8. Recipe RELEASE Guardrail

显式 override 想把：

```text
MIGRATED_UNVERIFIED
-> RELEASED
```

至少需要：

```text
known process_route
approved_by
approved_at
```

并通过：

```text
v_recipe_version_validation
```

必须满足：

```text
layer_count_ok = true
ratio_complete = true
ratio_sum_ok = true
```

因此旧 recipe 中 ratio 为空时不能通过“平均分层”偷偷 RELEASE。

---

## 9. Machine×Recipe Rate 来源

`standard_rate_kg_h` 是后续 Wave 3 duration 权威输入。

允许的来源语义：

### SIMULATED

用于工业 benchmark：

```text
source_type = SIMULATED
eligibility_status = QUALIFIED
confidence explicitly set
```

它可以用于：

```text
safe_for_benchmark_hard
```

但不能证明真实工厂可生产。

### PLANT_MASTER / ENGINEERING / LEARNED

可成为真实生产候选来源。

例如：

```text
PLANT_MASTER
  工艺工程批准标准产能

ENGINEERING
  工艺工程师确认试车数据

LEARNED
  MES 历史实绩统计
```

未来建议 LEARNED 增加：

```text
sample_count
median
p10
p90
last_observed_at
```

---

## 10. Coverage Gate 已升级

执行：

```bash
python scripts/audit_wave2_domain_coverage.py
```

现在输出三个层次：

### `safe_for_shadow`

用于开始 Wave 3 双轨诊断：

```text
Legacy decision
vs
Domain V2 decision
```

不改变正式 Solver。

### `safe_for_benchmark_hard`

允许 `SIMULATED` provenance 满足完整工业 benchmark 数据需求。

适合本项目：

```text
算法开发
约束回归
确定性冲突场景
性能测试
```

### `safe_for_production_hard`

只认可：

```text
PLANT_MASTER
PLANT_SOP
ENGINEERING
LEARNED
```

等 operational provenance。

`SIMULATED` 不计入生产 readiness。

---

## 11. 仍然保持 UNKNOWN 的数据

当前没有真实 plant master/SOP 的情况下，以下不自动填：

```text
LINE-01..LINE-10 process_route
LINE-xx cleanroom canonical ISO qualification
LINE-xx medical_release_status
LINE-xx polymer/extruder qualification
CORONA / IBC / AUTO_GAUGE 等实际设备功能
Recipe 的正式 RELEASE 状态
Recipe 的未知 ratio
Machine×Recipe 真实 standard_rate
lot QC release
canonical cleaning transition minutes
```

这些 UNKNOWN 是正确结果，不是数据填充失败。

---

## 12. 本轮推荐执行顺序

```text
1. apply_wave2_domain_schema.py
2. seed_wave2_master_data.py --dry-run
3. seed_wave2_master_data.py
4. audit_wave2_domain_coverage.py
5. 准备显式 plant/simulated override
6. apply_wave2_plant_overrides.py --dry-run
7. apply_wave2_plant_overrides.py
8. audit_wave2_domain_coverage.py
9. 才决定是否进入 Wave 3 SHADOW
```

在本仓库连接环境中无法访问项目实际 PostgreSQL，因此当前只完成代码与契约资产，不能把实际 DB population 标为 verified。

---

## 13. Wave 2-D Definition of Done

代码/资产层：

- [x] 官方材料 catalog；
- [x] exact alias matching policy；
- [x] LE6601 identity watchlist；
- [x] manufacturer evidence seed；
- [x] explicit medical exclusion guardrail；
- [x] unambiguous order -> recipe version traceability binding；
- [x] optional legacy rate shadow；
- [x] plant override contract；
- [x] plant override loader；
- [x] benchmark vs production coverage separation；
- [x] static safety contract tests；
- [ ] real PostgreSQL migration executed；
- [ ] real DB official evidence seed executed；
- [ ] plant/simulated override populated；
- [ ] real coverage report captured；

因此当前状态：

```text
W2-D = IMPLEMENTED_IN_BRANCH / DB_POPULATION_PENDING
```
