# 配置策略与换产规则闭环 Goal 计划

**生成日期**：2026-05-23
**目标范围**：解决“前台关闭所有 rules 后，新建 HTTP 预排程仍出现 ORD-001 -> ORD-009 换产间隔”的配置语义问题。
**优先级**：P0
**复杂度**：中

## 1. Goal

让调度结果完全受前台 UI / 数据库配置控制，避免 Excel fallback、内置默认值或历史草案状态在用户关闭规则后继续影响 HTTP 排程。

最终用户应能理解并验证：

- 关闭规则后，新建草案的 `policy_snapshot` 与当前 UI 配置一致。
- 新建草案不会继续引用 Excel fallback 换产矩阵。
- 甘特图上的空白、换产、生产、维护、停机有清晰区分。
- 对 `ORD-001 -> ORD-009` 这类订单，系统能说明间隔来源；如果 rules 全禁用，则不应产生隐藏换产时间。

## 2. 当前问题复盘

已确认现象：

- `#173` 不包含 `ORD-001` 和 `ORD-009`，实际包含这两个订单的是 `#174`。
- `#174` 创建时数据库规则行已全部禁用。
- `ORD-001` 生产结束时间为 `2026-05-17 22:30`。
- `ORD-009` 的 `setup_start_time` 为 `2026-05-17 22:30`，`start_time` 为 `2026-05-17 23:50`。
- 中间 80 分钟不是 idle，而是 `setup_time_mins=80`。

根因：

- HTTP 创建预排程时仍先从 `input/吹膜机排程数据.xlsx` 加载 `fallback_setup_mgr`。
- `DatabaseManager.load_master_data()` 使用 fallback manager 作为基础，再叠加数据库启用规则。
- 当数据库规则全禁用时，fallback 中的同物料、幅宽、厚度等规则不会被清空，仍参与换产时间计算。
- UI 上“rules 全关闭”的用户理解，与后端“DB rules 全禁用但 fallback 仍有效”的运行时语义不一致。

## 3. 产品口径

### 3.1 运行时配置原则

HTTP / UI 排程采用以下原则：

- 数据库配置是唯一运行时策略源。
- Excel 只允许作为初始化、导入或 CLI legacy 数据源，不允许在 HTTP 预排程中作为隐藏 fallback。
- 如果某类规则在 UI 中全部禁用，则该类规则不贡献时间、废料或阻断影响。
- 如果业务需要“基础换产时间永远存在”，必须作为 UI 可见、可启停、可审计的规则存在，不能作为代码默认值隐藏生效。

### 3.2 开关语义

- 全局 `setup_rules_enabled=false`：完全不计算换产时间和换产废料。
- 全局 `setup_rules_enabled=true`：只计算数据库中 `is_enabled=true` 的换产相关规则。
- 全局开关开启但所有换产规则行禁用：换产时间应为 0，除非存在 UI 可见且启用的“基础换产”规则。
- 维护、物料、洁净等级、机台能力等约束同理：禁用后必须在新建草案中体现，不影响历史草案。

## 4. Sprint 1：后端策略输入闭环

**Goal**：让 HTTP 排程彻底摆脱隐藏 fallback，保证 rules 禁用状态真实进入算法。

**Demo / Validation**：

- 在 `/config?tab=rules` 或相关配置页禁用所有 rules。
- 新建包含 `ORD-001` 和 `ORD-009` 的预排程草案。
- 检查新草案中 `ORD-009.setup_time_mins` 不再为 80。

### Task 1.1：拆分 Excel fallback 与 HTTP runtime

- **位置**：`api/routers/schedule.py`, `src/database.py`
- **描述**：HTTP 创建预排程时不再把 Excel 加载出的 `fallback_setup_mgr` 传入数据库运行时加载路径。保留 Excel fallback 仅用于初始化、导入或 CLI legacy 场景。
- **依赖**：无
- **验收标准**：
  - HTTP `create_preplan` 路径只使用数据库配置生成 `setup_mgr`。
  - 禁用 DB rules 后，新草案不会继承 Excel 中的同物料、幅宽、厚度、GMP 等规则。
  - CLI / 数据导入路径如仍需 Excel fallback，行为不被破坏。
- **验证**：
  - 单元测试覆盖 HTTP runtime 不传入 fallback 的场景。
  - 手工创建新草案后检查 `solver_params.policy_snapshot` 和任务换产时间。

### Task 1.2：提供 zero-rule setup manager

- **位置**：`src/setup_matrices.py`, `src/database.py`
- **描述**：增加明确的“空规则”初始化方式，避免 `SetupMatricesManager()` 自带 `same_material_time=30`、`corona_switch_time=20`、`core_size_switch_time=30` 等隐性默认值在 HTTP 路径生效。
- **依赖**：Task 1.1
- **验收标准**：
  - HTTP DB runtime 初始 manager 的 material/spec/gmp/corona/core/die/continuous cleaning 默认贡献为 0。
  - 只有数据库启用规则才会写入对应时间或废料值。
  - 如果 `setup_rules_enabled=false`，所有 setup component 固定为 0。
- **验证**：
  - 新增测试：所有规则禁用时，`ORD-001 -> ORD-009` 的 setup 计算结果为 0。
  - 新增测试：只启用幅宽规则时，只产生幅宽换产时间。
  - 新增测试：只启用同物料规则时，只产生同物料换批时间。

### Task 1.3：补充 policy snapshot 与 effective policy 诊断

- **位置**：`api/routers/schedule.py`, `src/database.py`
- **描述**：在草案结果中输出本次实际使用的 rule source、启用规则计数、全局开关状态和 fallback 使用状态。
- **依赖**：Task 1.1, Task 1.2
- **验收标准**：
  - `policy_snapshot` 中能看出 `runtime_rule_source=db_only`。
  - `fallback_setup_used=false`。
  - 每个规则组输出 enabled/disabled 计数。
  - 当前配置变更后，旧草案能提示 policy stale，新草案使用新策略。
- **验证**：
  - API 测试断言新建草案包含 runtime source 信息。
  - UI 手工查看草案复核区域能看到策略版本和是否过期。

## 5. Sprint 2：换产明细与甘特图解释闭环

**Goal**：让用户能区分“换产段”和“真实空闲”，并能看懂每段时间由哪些规则贡献。

**Demo / Validation**：

- 打开 `/gantt` 和 `/workbench`。
- 点击 `ORD-009` 或其前序换产区域。
- 页面展示 `ORD-001 -> ORD-009` 的换产明细；如果 rules 全禁用，则显示“无启用换产规则，本段无换产时间”。

### Task 2.1：保存 setup detail

- **位置**：`src/scheduler.py`, `src/database.py`, `db/init_schema.sql`
- **描述**：将换产时间拆解为结构化明细，例如 material、width、thickness、gmp、corona、core、die，每项包含分钟数、前序值、后续值、命中规则 id 或规则说明。
- **依赖**：Sprint 1
- **验收标准**：
  - `scheduled_tasks.setup_detail` 写入结构化 JSON。
  - `setup_time_mins` 等于 setup detail 中各项分钟数合计。
  - rules 全禁用时，setup detail 为空数组或全部为 0，并标记 no_enabled_rules。
- **验证**：
  - 单元测试断言 `ORD-001 -> ORD-009` 的明细与合计一致。
  - API 返回字段不破坏现有前端。

### Task 2.2：Gantt 事件展示换产段

- **位置**：`api/routers/schedule.py`, `web/src/pages/GanttPage.jsx`
- **描述**：确保 Gantt 明确绘制 setup 事件，tooltip 和详情面板展示换产原因，不把 setup 视觉上误判为空白。
- **依赖**：Task 2.1
- **验收标准**：
  - 生产段、换产段、维护段、停机段、idle 段颜色和图例不同。
  - 点击换产段显示前序订单、后续订单、总分钟数、分项原因。
  - 没有 setup 且没有 idle 时，订单条之间不出现无说明空白。
- **验证**：
  - 浏览器检查 `/gantt`。
  - E2E 或截图检查换产 legend、tooltip、详情面板存在。

### Task 2.3：Workbench 资源视图展示换产说明

- **位置**：`web/src/pages/ScheduleWorkbench.jsx`
- **描述**：在资源视图和右侧 Inspector 中显示当前选中订单的前序换产来源，避免只显示生产时间。
- **依赖**：Task 2.1
- **验收标准**：
  - 选择 `ORD-009` 时，Inspector 显示前序 `ORD-001`、换产开始、生产开始、换产总分钟数。
  - 如果换产为 0，显示“无启用换产规则产生换产时间”。
  - 如果存在 idle，明确显示 idle 原因，不与 setup 混淆。
- **验证**：
  - 手工点击 `/workbench` 中 `ORD-009`。
  - E2E 覆盖选中订单后 Inspector 展示 setup/idle 信息。

## 6. Sprint 3：配置 UI 语义与防误解

**Goal**：让前台用户清楚知道“全局开关”和“规则行启停”的区别，以及规则变更对新旧草案的影响。

**Demo / Validation**：

- 用户在配置页关闭所有 rules 后，页面提示“仅影响新建草案”。
- 页面显示当前策略版本。
- 历史草案标记为旧策略，新建草案使用新策略。

### Task 3.1：规则页增加生效范围提示

- **位置**：`web/src/pages/ConfigPage.jsx`
- **描述**：在规则配置页显示策略版本、最后更新时间、是否影响历史草案、是否需要重新创建草案。
- **依赖**：Sprint 1
- **验收标准**：
  - 保存规则启停后显示轻量状态提示。
  - 文案说明“只影响新建预排程草案，历史草案保留创建时策略快照”。
  - 如果全局 setup 开启但某类规则全禁用，显示“该类当前不贡献换产时间”。
- **验证**：
  - 前端交互测试保存规则开关。
  - 手工查看配置页提示。

### Task 3.2：全局配置页增加策略总览

- **位置**：`web/src/pages/ConfigPage.jsx`, `api/routers/schedule.py`
- **描述**：提供“当前排程策略总览”，展示 setup/material/maintenance/cleanroom/machine capability/due date optimization 的开关状态和启用规则数量。
- **依赖**：Task 3.1
- **验收标准**：
  - 用户无需查数据库即可知道当前排程会考虑哪些约束。
  - 所有关键开关和规则数量都中文化。
  - 策略总览与新建草案 `policy_snapshot` 一致。
- **验证**：
  - API 测试对比 summary 与 snapshot。
  - UI 手工核对配置页与草案详情。

## 7. Sprint 4：回归测试与演示验收

**Goal**：用自动化和手工流程证明问题关闭，避免后续 fallback 或默认值回归。

### Task 4.1：后端测试矩阵

- **位置**：`tests/test_rule_enablement.py`, `tests/test_policy_settings.py`, `tests/test_preplan_contract.py`
- **描述**：补充 rules enablement 与 setup 计算回归测试。
- **依赖**：Sprint 1, Sprint 2
- **验收标准**：
  - 全部 rules 禁用时，`ORD-001 -> ORD-009` setup 为 0。
  - 仅启用部分规则时，只计算对应规则类别。
  - 全局 `setup_rules_enabled=false` 时，即使规则行启用也不产生 setup。
  - 新建草案 snapshot 记录策略版本和规则计数。
- **验证**：
  - `python -m pytest tests/test_rule_enablement.py tests/test_policy_settings.py tests/test_preplan_contract.py`

### Task 4.2：前端 E2E 验收

- **位置**：`web/e2e/config-policy.spec.js`, `web/e2e/workbench.spec.js`
- **描述**：补齐配置开关、创建草案、查看换产解释、历史草案 stale 提示的端到端测试。
- **依赖**：Sprint 2, Sprint 3
- **验收标准**：
  - E2E 能禁用 rules，并创建新草案。
  - E2E 能确认工作台或 Gantt 不显示无解释空白。
  - E2E 能确认草案策略快照与当前配置一致。
- **验证**：
  - `cd web && npm run e2e -- config-policy.spec.js workbench.spec.js`

### Task 4.3：人工演示脚本

- **位置**：`docs/config-policy-setup-rules-closed-loop-goal-plan.md`
- **描述**：保留一套可重复人工验收步骤，作为演示前检查清单。
- **依赖**：全部任务
- **验收标准**：
  - 非开发人员可按步骤复现配置变更和排程结果变化。
  - 复现用例包含 `ORD-001` 和 `ORD-009`。
  - 能解释历史草案与新草案差异。
- **验证**：
  - 按文档从 UI 执行一遍，记录新 run id 和关键截图。

## 8. 总体验收矩阵

| 场景 | 操作 | 期望结果 | 优先级 |
| --- | --- | --- | --- |
| 全部 rules 禁用 | 新建包含 `ORD-001`, `ORD-009` 的草案 | `ORD-009.setup_time_mins=0`，两单之间没有隐藏换产间隔 | P0 |
| 只启用幅宽规则 | 新建同一草案 | `ORD-009` 只体现幅宽变化贡献，不体现同物料/厚度/GMP | P0 |
| 全局 setup 关闭 | 即使规则行启用也新建草案 | 所有任务 setup 时间为 0 | P0 |
| 历史草案查看 | 查看规则关闭前创建的草案 | 保留原 snapshot，并提示与当前策略不一致 | P1 |
| Gantt 展示 | 查看 `/gantt` | setup、production、idle、maintenance、downtime 视觉和 tooltip 区分清楚 | P1 |
| Workbench 复核 | 选择 `ORD-009` | Inspector 显示前序订单、换产来源或无换产说明 | P1 |
| 配置保存 | 在配置页启停规则 | 显示保存成功、策略版本更新、仅影响新建草案 | P2 |

## 9. 手工验收步骤

1. 打开 `http://localhost:3000/config?tab=rules` 或当前规则配置入口。
2. 确认 material、spec、gmp、maintenance rules 全部禁用。
3. 确认全局 `setup_rules_enabled=true`。
4. 进入 `http://localhost:3000/workbench`。
5. 选择至少包含 `ORD-001` 和 `ORD-009` 的订单，创建新的预排程草案。
6. 打开草案详情，确认 `policy_snapshot.enabled_rule_counts` 全部为 0。
7. 检查 `ORD-001` 与 `ORD-009`：
   - `ORD-001.end_time` 应等于 `ORD-009.start_time`，或 `ORD-009.setup_time_mins=0`。
   - 如果存在时间差，必须有 setup 或 idle 明细解释，且来源是 UI 可见启用规则。
8. 打开 `/gantt`，确认两单之间没有无说明空白。
9. 选择 `ORD-009`，确认 Inspector 或详情面板显示“无启用换产规则产生换产时间”。
10. 重新启用一条幅宽规则，再创建新草案，确认换产时间只来自幅宽规则。

## 10. 风险与注意事项

- 历史草案不应被新规则重算，否则会破坏审计可追溯性；应通过 stale 提示解释差异。
- 如果业务坚持“基础换产时间必须永远存在”，需要先把基础换产规则产品化，而不是保留代码默认值。
- `SetupMatricesManager()` 当前有隐性默认值，修复时必须避免影响 CLI legacy 场景。
- 前端看到的“间隔”可能来自 setup，也可能来自 idle；修复时不能只改算法，还要让 UI 解释时间段类型。
- E2E 测试如果会修改共享数据库，需要加入 setup/cleanup，避免污染用户当前数据。

## 11. 建议提交边界

推荐拆成 3 个 commit：

1. `fix: make http scheduling use db-only setup rules`
2. `feat: expose setup detail and policy runtime snapshot`
3. `test: cover rule disablement and setup visualization`

## 12. 本轮实现与验收记录

**状态**：已实现并通过本轮验收。

### 已实现

- HTTP 预排程、人工调整候选换产计算、草案重排换产重算均不再加载 Excel fallback setup matrix。
- 数据库运行时使用 `SetupMatricesManager.empty_rules()` 作为空规则起点，避免同物料 30 分钟、幅宽/厚度/电晕/卷芯等默认值在 rules 全禁用后隐藏生效。
- `policy_snapshot` 增加 `runtime_rule_source=db_only` 与 `fallback_setup_used=false`。
- `scheduled_tasks.setup_detail` 写入并通过 API 返回结构化换产明细。
- Gantt 换产 tooltip / 事件详情展示换产分项；Workbench Inspector 展示前序订单、换产区间和“无启用换产规则产生换产时间”说明。
- 配置页 rules 区域提示“规则启停只影响新建预排程草案，历史草案保留创建时策略快照”，并在换产相关规则全禁用时提示新草案不应产生隐藏换产时间。

### 关键验收证据

- 单元测试：`python -m pytest tests/test_rule_enablement.py tests/test_policy_settings.py -q`，17 passed。
- 换产回归测试：`python -m pytest tests/test_setup_time.py tests/test_scheduler_validation.py -q`，23 passed。
- HTTP 合约测试：`APS_RUN_HTTP_TESTS=1 APS_API_BASE_URL=http://127.0.0.1:8000 python -m pytest tests/test_preplan_contract.py -q`，1 passed。
- 前端构建：`cd web && npm run build`，passed。
- 前端 E2E：`cd web && npm run e2e -- config-policy.spec.js workbench.spec.js`，6 passed, 1 skipped。
- 真实 HTTP 验收：在当前 rules 全禁用、`setup_rules_enabled=true`、`policy_version=41` 下创建并清理 `#176` 草案：
  - `policy_snapshot.runtime_rule_source=db_only`
  - `policy_snapshot.fallback_setup_used=false`
  - material/spec/gmp/maintenance enabled counts 全为 0
  - `ORD-001.setup_time_mins=0`
  - `ORD-009.setup_time_mins=0`
  - 两单 `setup_detail.no_enabled_rules=true`
- 浏览器验收：
  - `/config?tab=rules` 显示运行时提示，且无 console error。
  - `/workbench` 打开 `#176` 并选择 `ORD-009`，Inspector 显示“无启用换产规则产生换产时间”，且无 console error。
