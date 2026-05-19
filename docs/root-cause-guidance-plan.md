# Plan: Root Cause Analysis and Guidance Direction

**Generated**: 2026-05-19
**Estimated Complexity**: High

## Overview

当前排程系统已经能完成自动排程、HTTP 后端展示、Dashboard/Gantt/配置页联动，但仍缺少一层稳定的“诊断解释引擎”。下一阶段目标不是只显示排程结果，而是让用户能回答三个问题：

- 为什么这个订单排不上、排晚了、或换产成本高？
- 哪些机台是瓶颈、闲置、受维护/停机影响，证据是什么？
- 下一步应该改订单、改机台、改规则，还是接受当前结果？

方案以“结构化诊断”为主线：调度器和数据库产生可追溯证据，HTTP API 输出统一诊断对象，UI 在 Dashboard、Gantt、订单/机台/规则配置页提供根因和可点击的修复入口。

## Scope

- 保持现有方向：后端 HTTP + 前端 UI。
- 保持 MVP 边界：订单输入 + 自动排程；不引入人工排产状态。
- 暂不 HTTP 化订单批量输入；诊断只使用现有订单、机台、规则、维护、停机和排程结果数据。
- 指导动作只链接到已有或近期需要补齐的配置入口，不提供拖拽改排程。

## Current Gaps

- `src/scheduler.py` 对无可用机台只返回一条文本错误，无法区分幅宽、厚度、洁净度、层数、机台状态等具体拦截原因。
- `api/routers/schedule.py` 已提供 Gantt 的 production/setup/maintenance/downtime/idle 事件，但 idle 原因仍是相邻事件推断，缺少置信度、业务解释和修复建议。
- `api/routers/dashboard.py` 主要返回 KPI 和逾期订单列表，没有 run-level 根因汇总。
- `web/src/pages/Dashboard.jsx` 目前靠解析失败日志展示无可用机台，容易受日志格式和编码影响。
- `web/src/pages/GanttPage.jsx` 能显示完整时间线事件，但 tooltip 还没有“中断/空档为什么出现、是否可处理、应该去哪里改”的解释。
- 数据库 `scheduled_tasks.setup_detail` 已预留 JSONB 字段，但当前保存任务时没有写入换产明细，可作为后续低风险扩展点。

## Diagnostic Taxonomy

### Infeasible Orders

- `eligibility.width_out_of_range`: 订单目标幅宽超出所有候选机台边界。
- `eligibility.thickness_out_of_range`: 订单厚度超出机台能力。
- `eligibility.cleanroom_mismatch`: Class_10K 订单只能上更高洁净能力机台。
- `eligibility.layer_mismatch`: 配方层数超过机台层数。
- `eligibility.machine_unavailable`: 机台 `OFFLINE`、非 active，或排程窗口内完全被禁排覆盖。
- `eligibility.no_capacity`: 有能力机台，但可用产能无法在计划域内承接。
- `material.not_available`: 原料齐套时间晚于可接受开工或交期。

### Late Orders

- `lateness.due_too_tight`: 最短理论生产时间也无法满足交期。
- `lateness.material_wait`: 原料齐套时间导致最早开工已晚。
- `lateness.machine_bottleneck`: 少数机台承担过多可行订单。
- `lateness.setup_burden`: 为减少换产或满足约束，订单被排在较晚位置。
- `lateness.maintenance_conflict`: 关键机台维护/禁排窗口压缩产能。
- `lateness.downtime_conflict`: 非计划停机影响产能或甘特区域连续性。
- `lateness.priority_tradeoff`: 当前权重下该订单让位给更高优先级订单。

### Idle Gaps

- `idle.before_maintenance`: 维护前空档，不一定可消除。
- `idle.after_maintenance`: 维护后恢复空档。
- `idle.before_downtime`: 停机前空档。
- `idle.after_downtime`: 停机后恢复空档。
- `idle.material_wait`: 有订单可做但原料未齐套。
- `idle.no_ready_eligible_order`: 没有已就绪且满足机台能力的订单。
- `idle.optimization_tradeoff`: 求解器为交期/换产目标保留空档。
- `idle.unexplained`: 当前数据不足以证明根因，必须显式标记为产品债。

### Setup and Scrap Cost

- `setup.material_switch`: 多层材料切换导致清洗时间/废料。
- `setup.width_change`: 幅宽上调/下调阶梯规则触发。
- `setup.thickness_change`: 厚度变化规则触发。
- `setup.gmp_clearance`: 订单等级切换触发 GMP 清场。
- `setup.corona_or_core`: 电晕或卷芯配置变化触发。

### Machine-Level Guidance

- `machine.high_load`: 负载超过阈值，是排程瓶颈。
- `machine.low_load`: 负载低但仍可承接部分订单。
- `machine.unused_capacity_missing`: 未使用，因为能力参数无法覆盖订单池。
- `machine.unused_no_ready_orders`: 有能力但无可用订单。
- `machine.unused_lost_to_better_choice`: 有能力但被更优机台抢走。
- `machine.changeover_heavy`: 换产时间占用过高，应检查规则或订单组合。

## Diagnostic Data Contract

新增统一诊断对象，所有接口复用同一结构，避免前端继续解析日志文本。

```json
{
  "id": "diag-run-7-order-ORD-BLOCKED-WIDTH",
  "run_id": 7,
  "entity_type": "run|order|machine|event",
  "entity_id": "ORD-BLOCKED-WIDTH",
  "severity": "critical|warning|info",
  "category": "eligibility|lateness|idle|setup|material|maintenance|downtime|capacity",
  "code": "eligibility.width_out_of_range",
  "confidence": "proven|inferred|unknown",
  "root_cause": "订单幅宽 1718mm 超过所有可用机台能力上限。",
  "evidence": [
    { "metric": "target_width", "actual": 1718, "unit": "mm" },
    { "metric": "best_machine_max_width", "actual": 1200, "unit": "mm", "entity_id": "LINE-03" }
  ],
  "recommendations": [
    {
      "action": "edit_order_width",
      "label": "检查订单幅宽",
      "href": "/config?tab=orders&order=ORD-BLOCKED-WIDTH"
    },
    {
      "action": "enable_or_adjust_machine_capacity",
      "label": "检查机台能力边界",
      "href": "/config?tab=machines"
    }
  ],
  "related_event": {
    "type": "idle|production|setup|maintenance|downtime",
    "machine_id": "LINE-03",
    "start": "2026-05-19T22:43:00+08:00",
    "end": "2026-05-27T08:35:00+08:00"
  }
}
```

## Sprint 1: Backend Diagnostic Engine

**Goal**: 先让后端能用结构化数据解释订单、机台和结果，不依赖日志解析。

**Validation**:

- 对边界不可排订单返回明确的无可用机台根因。
- 对逾期订单、维护/停机、idle 空档生成诊断列表。
- 单元测试覆盖每类核心诊断。

### Task 1.1: Define Diagnostic Models

- **Location**: `src/diagnostics.py`
- **Description**: 新增 `Diagnostic`, `DiagnosticEvidence`, `DiagnosticRecommendation` dataclass 或轻量模型。
- **Dependencies**: None
- **Acceptance Criteria**:
  - severity/category/code/confidence 字段枚举化。
  - 提供 `to_dict()`，可直接被 API 返回。
- **Validation**: 新增 `tests/test_diagnostics.py` 验证序列化和字段稳定性。

### Task 1.2: Explain Machine Eligibility

- **Location**: `src/models.py`, `src/diagnostics.py`, `src/scheduler.py`
- **Description**: 将 `BlownFilmMachineModel.can_produce()` 的布尔结果旁路扩展为可解释评估函数，例如 `evaluate_machine_fit(order, machine)`，返回每台机的拦截原因。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - 不破坏现有 `can_produce()` 调用。
  - 对幅宽、厚度、洁净度、层数至少输出 proven 级证据。
  - `ScheduleResult.validation_errors` 可继续保留，但不再是 UI 主数据源。
- **Validation**: 覆盖边界不可排订单和边界机台能力测试。

### Task 1.3: Add Order-Level Diagnostics to ScheduleResult

- **Location**: `src/scheduler.py`
- **Description**: 在 `ScheduleResult` 增加 `diagnostics` 列表；无可用机台、求解失败、校验失败都写入结构化诊断。
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - 排程失败时仍能返回可解释诊断。
  - 同一订单可同时包含多个候选根因，但有一个主根因排序靠前。
- **Validation**: `tests/test_scheduler_validation.py` 增加结构化诊断断言。

### Task 1.4: Classify Lateness and Setup Burden

- **Location**: `src/diagnostics.py`, `src/scheduler.py`
- **Description**: 基于已排任务、due date、material_available、setup_time、prev_order 生成逾期和换产成本诊断。
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - 逾期订单至少输出 due/material/capacity/setup 的最可能原因。
  - setup 诊断给出换产分钟数、前序订单、规则类别。
- **Validation**: 用非演示 fixture 或当前订单数据断言存在逾期和换产诊断。

### Task 1.5: Classify Machine Load and Unused Machines

- **Location**: `src/diagnostics.py`, `src/scheduler.py`
- **Description**: 按机台统计负载、空闲、换产占比、未使用原因。
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - 输出 high_load、low_load、unused、changeover_heavy。
  - unused 区分能力不足、无就绪订单、输给更优选择。
- **Validation**: 使用真实机台数据或非演示 fixture 覆盖 unused、low-load 和压力场景。

## Sprint 2: Persist and Serve Diagnostics Over HTTP

**Goal**: 让 HTTP 后端稳定提供诊断，不要求前端解析日志。

**Validation**:

- `/api/schedule/diagnostics` 能返回当前 active run 的诊断。
- `/api/schedule/gantt` 的事件可关联诊断。
- Dashboard 失败场景不再依赖乱码日志。

### Task 2.1: Add Diagnostic Persistence

- **Location**: `db/init_schema.sql`, optional migration script, `src/database.py`
- **Description**: 新增 `schedule_diagnostics` 表，或先用 `schedule_runs.solver_params`/JSONB 承载 MVP 诊断。推荐独立表，便于筛选和历史追溯。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 字段包含 run_id、entity_type、entity_id、severity、category、code、confidence、root_cause、evidence JSONB、recommendations JSONB、related_event JSONB。
  - 保存排程结果时同步保存诊断。
- **Validation**: 数据库单元测试或集成测试确认 run 保存后能查回诊断。

### Task 2.2: Add Diagnostics API

- **Location**: `api/routers/schedule.py`, `web/src/api/client.js`
- **Description**: 新增 `GET /api/schedule/diagnostics?run_id=&entity_type=&entity_id=&severity=`。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 默认返回 active run。
  - 支持按订单、机台、事件过滤。
  - 失败排程的 job status 能携带结构化 diagnostics。
- **Validation**: `tests/test_api.py` 增加 API contract 测试。

### Task 2.3: Attach Event Diagnostics to Gantt

- **Location**: `api/routers/schedule.py`
- **Description**: 为 production/setup/maintenance/downtime/idle 事件附加 `diagnostic_ids` 和简短 `guidance`。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - idle 空档至少区分维护/停机/无就绪订单/未知。
  - 无法证明的 idle 必须 `confidence=unknown`，UI 不能假装已知。
- **Validation**: `tests/test_schedule_gantt.py` 增加 idle 诊断关联断言。

### Task 2.4: Replace Dashboard Log Parsing With Structured Errors

- **Location**: `api/routers/schedule.py`, `web/src/pages/Dashboard.jsx`
- **Description**: `Run Schedule` 失败时优先展示 job diagnostics，日志只作为“原始日志”折叠详情。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - 中文根因不再出现乱码风险。
  - 每条失败订单都能链接到 `/config?tab=orders&order=...`。
- **Validation**: 触发真实或测试边界订单不可排，确认 Dashboard 展示结构化诊断。

## Sprint 3: UI Guidance Surfaces

**Goal**: 将诊断变成用户可行动的界面，而不是仅有报告。

**Validation**:

- Dashboard 首屏出现 “Root Cause & Next Actions”。
- Gantt 中断/空档点击后能看到原因和下一步。
- 订单/机台/规则配置页能从诊断入口跳转并定位。

### Task 3.1: Dashboard Root Cause Panel

- **Location**: `web/src/pages/Dashboard.jsx`, `web/src/index.css`
- **Description**: 新增根因汇总面板，按 critical/warning/info 和 category 聚合。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 展示 Top 5 根因、受影响订单/机台数量、主要建议动作。
  - 不挤占现有 KPI 和 Run Schedule 状态。
- **Validation**: 浏览器 smoke 验证 active run、failed trigger 两种状态。

### Task 3.2: Gantt Event Detail Drawer

- **Location**: `web/src/pages/GanttPage.jsx`, `web/src/index.css`
- **Description**: 点击生产、换产、维护、停机、idle 事件时打开详情抽屉，展示根因、证据和建议。
- **Dependencies**: Task 2.3
- **Acceptance Criteria**:
  - 甘特图仍保持完整覆盖线；idle 是解释层，不是缺失区域。
  - 对 unknown idle 明确显示“当前数据不足以证明原因”。
- **Validation**: 桌面和窄屏截图检查无文本重叠。

### Task 3.3: Order Configuration Warning Panel

- **Location**: `web/src/pages/ConfigPage.jsx`
- **Description**: 当 URL 带 `order=` 时，显示该订单相关诊断和可编辑字段。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - 无可用机台时突出显示 width/thickness/cleanroom/product_type/due_date/material_available_time。
  - 保存后提示需要重新运行排程。
- **Validation**: 不可排订单链接进入配置页能看到根因。

### Task 3.4: Machine Guidance Panel

- **Location**: `web/src/pages/MachinesPage.jsx`
- **Description**: 在机台页显示高负载、低负载、未使用、换产重机台的原因。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - 机台状态、能力边界、当前状态和诊断同屏可对照。
  - 建议动作链接到机台编辑和维护配置。
- **Validation**: 当前机台或非演示 fixture 至少覆盖一个 unused 或 low-load 说明。

## Sprint 4: Real Data Walkthrough and Regression Tests

**Goal**: 让当前订单数据能清楚讲出“结果、根因、指导动作”的闭环。

**Validation**:

- 当前数据或非演示 fixture 能覆盖 blocked、late、maintenance idle、downtime、setup burden、unused machine。
- 文档说明真实数据检查路径和预期截图点。

### Task 4.1: Extend Real-Data Regression Assertions

- **Location**: `tests/test_diagnostics.py`, `tests/test_scheduler_validation.py`, `tests/test_schedule_gantt.py`
- **Description**: 不依赖演示 seed，保证真实数据同类问题有稳定的诊断覆盖面。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - 测试断言关键诊断 code 存在。
  - 不依赖数据库状态或人工切换脚本。
- **Validation**: `python -m unittest discover -s tests -q`。

### Task 4.2: Update Real-Data Walkthrough Documentation

- **Location**: `docs/real_data_scheduling.md`
- **Description**: 增加“根因分析真实数据检查脚本”：Dashboard 看汇总、Gantt 看中断解释、Config 修复不可排订单、重新 run schedule。
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - 每一步有 URL、预期现象、讲解口径。
  - 说明哪些根因是 proven，哪些是 inferred/unknown。
- **Validation**: 按文档完整走一遍真实数据检查。

### Task 4.3: Add Browser Smoke Checklist

- **Location**: optional `docs/real_data_scheduling.md` or `tests/`
- **Description**: 固化浏览器检查点，避免 UI 演示时出现甘特图中断未说明、链接无效、文本溢出。
- **Dependencies**: Sprint 3
- **Acceptance Criteria**:
  - Dashboard、Gantt、Orders、Machines、Config 都有检查项。
  - 关键截图点覆盖桌面宽屏。
- **Validation**: 本地 Vite build + 浏览器 smoke。

## Sprint 5: Later What-If Guidance

**Goal**: 在结构化诊断稳定后，再考虑“如果怎么改会怎样”的模拟建议。

**Non-Goal for Now**:

- 不在当前阶段做拖拽改排程。
- 不做自动修改订单/机台/规则。
- 不承诺最优业务策略，只给可验证的候选动作。

### Task 5.1: Lightweight What-If API

- **Location**: future `api/routers/schedule.py`, `src/diagnostics.py`
- **Description**: 对单个订单或机台配置变更做临时模拟，返回影响估算。
- **Dependencies**: Sprint 1-4 全部稳定
- **Acceptance Criteria**:
  - 输入不落库。
  - 输出影响范围、风险和需要正式重新排程的提示。
- **Validation**: 单订单 width/due_date/material_available_time 模拟测试。

## Testing Strategy

- Unit tests:
  - 诊断模型序列化。
  - 机台能力拦截分类。
  - 逾期、换产、idle、机台负载分类。
- API tests:
  - `/api/schedule/diagnostics` contract。
  - `/api/schedule/gantt` event diagnostic linkage。
  - failed trigger 返回结构化 diagnostics。
- Scenario tests:
  - 边界不可排订单必须有 proven eligibility 诊断。
  - 真实数据或非演示 fixture 必须覆盖 maintenance/downtime/idle/setup/late 中至少 4 类。
- Frontend validation:
  - `npm run build`。
  - 浏览器 smoke：Dashboard、Gantt、Config、Machines。
  - 检查 Gantt 缩放后 idle/maintenance/downtime 仍连续覆盖并有说明。

## Potential Risks and Gotchas

- idle 根因可能不是唯一真因。必须引入 `confidence`，不能把推断写成事实。
- CP-SAT 求解器不会天然告诉我们“为什么没选某个订单填空档”。需要用启发式证据解释，并保留 unknown 类别。
- 不要继续依赖日志文本解析。日志可以留作 raw detail，但产品展示必须来自结构化诊断。
- 诊断建议不能暗示用户手工拖排，只能引导修改订单、机台、维护、停机或规则配置，然后重新自动排程。
- 如果后续迁移数据库，要考虑已有本地库缺少新表的升级路径。
- 旧记忆里提到的 `machine_insights` 等实现当前仓库未完整保留，实施前必须以当前代码为准重新接入。

## Rollback Plan

- Sprint 1 可通过不暴露 diagnostics 字段回退，不影响现有排程。
- Sprint 2 若数据库迁移有风险，先改为运行时 API 计算，不落库。
- Sprint 3 UI 面板可以 feature flag 或仅在 diagnostics 存在时渲染。
- Sprint 4 回归不依赖数据切换脚本，失败时保留当前 active run。
