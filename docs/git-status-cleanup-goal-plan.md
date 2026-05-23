# Git Status Cleanup And Commit Goal Plan

**Generated**: 2026-05-23
**Branch**: `codex/order-flow-sprint1`
**Baseline Commit**: `0f37d7d feat: add workbench wizard flow and pagination`
**Execution Status**: Completed on 2026-05-23
**Complexity**: Medium

## Overview

当前工作区在工作台向导流提交之后仍保留大量未提交变更。变更混合了后端 HTTP 闭环、规则开关、订单入库/初筛、前端配置与中文化、e2e、文档、本地日志和排程输出产物。

本计划目标是把工作区恢复到可审查、可验证、可分批提交的状态，避免一次性提交所有文件造成历史污染。

## Goals

- 只提交有产品价值和可验证闭环的文件。
- 将本地运行日志、脑暴原型和临时产物排除出版本控制。
- 修复或重建乱码文档，保证提交后的文档可读。
- 按业务边界拆分提交，方便回滚和 review。
- 每个功能提交都有对应测试或手工验收依据。

## Non-Goals

- 不直接执行 `git add .`。
- 不回滚用户或其他流程产生的未提交源码改动。
- 不把 `output/*` 生成产物混入功能提交，除非明确需要刷新演示基线。
- 不在本计划阶段继续扩展业务功能。

## Current State Snapshot

- 计划生成时暂存区为空，tracked modified 文件共 18 个，untracked 展开项共 42 个。
- 执行后本地运行目录已忽略，`output/*` 生成产物未纳入功能提交。
- 执行后源码、测试和文档已按功能域拆分提交。
- `git diff --check` 仅有 LF/CRLF 提示，没有 whitespace 错误。
- 仓库当前未配置 remote。

## Execution Results

- `6371180 chore: ignore local runtime artifacts`
- `ee320cc feat: close schedule policy and rule runtime loop`
- `2b88ab0 feat: add order ingestion and screening flow`
- `118dab5 feat: complete config UI and localization checks`
- 文档提交在本计划 P2 阶段单独落地。

## P0: Repository Hygiene

**Goal**: 先清掉最容易污染提交历史的本地产物和编码风险。

**Demo/Validation**:
- `git status --short` 不再显示 `.codex-logs/` 和 `.superpowers/`。
- 新增或保留的文档首行在编辑器和 `git diff` 中可读。
- 暂存区仍只包含本阶段明确文件。

### Task P0.1: Ignore Local Runtime Artifacts

- **Location**: `.gitignore`
- **Description**: 增加本地运行日志和脑暴原型目录忽略规则。
- **Dependencies**: None
- **Acceptance Criteria**:
  - `.codex-logs/` 被忽略。
  - `.superpowers/` 被忽略。
  - 不删除本地文件，只是不再进入 Git 状态。
- **Validation**:
  - `git status --short`
  - `git check-ignore .codex-logs/backend.out.log .superpowers/brainstorm/...`

### Task P0.2: Review And Repair Goal Documents

- **Location**:
  - `docs/config-policy-setup-rules-closed-loop-goal-plan.md`
  - `docs/order-flow-closed-loop-goal-plan.md`
  - `docs/workbench-interaction-cleanup-goal-plan.md`
  - `docs/workbench-wizard-flow-goal-plan.md`
- **Description**: 检查文档是否真实乱码。如果文件内容已经损坏，则用当前业务结论重建；如果只是 PowerShell 显示编码问题，则保留并记录验证方式。
- **Dependencies**: None
- **Acceptance Criteria**:
  - 每份文档标题、章节、验收标准可读。
  - 文档内容和当前已实现/待实现状态一致。
  - 不提交不可读文档。
- **Validation**:
  - `git diff -- docs/*.md`
  - 编辑器打开抽查。

### Task P0.3: Decide Output Baseline Policy

- **Location**:
  - `output/material_correction.csv`
  - `output/schedule_result.csv`
  - `output/schedule_result.json`
- **Description**: 判断这些 tracked 输出是否作为演示基线需要更新。
- **Dependencies**: None
- **Acceptance Criteria**:
  - 若只是本地运行产物，不纳入提交。
  - 若需要刷新演示基线，单独提交并在 commit message 中说明生成方式。
- **Validation**:
  - `git diff --stat -- output`
  - 手工确认是否用于 README、演示或测试断言。

## P1: Functional Commit Split

**Goal**: 将业务代码拆成可 review、可回滚的提交。

**Demo/Validation**:
- 每个提交只覆盖一个功能域。
- 每个提交后可运行对应测试。
- `git show --stat HEAD` 能清晰表达提交边界。

### Task P1.1: Commit Backend Policy And Rule Runtime Closure

- **Location**:
  - `api/routers/rules.py`
  - `api/routers/schedule.py`
  - `src/database.py`
  - `src/setup_matrices.py`
  - `src/scheduler.py`
  - `db/init_schema.sql`
  - `tests/test_policy_settings.py`
  - `tests/test_rule_enablement.py`
  - `tests/test_publish_audit.py`
  - `tests/test_queue_transitions.py`
  - `tests/test_preplan_contract.py`
- **Description**: 提交全局策略、规则启停、HTTP runtime 不再使用隐藏 Excel fallback、发布审计和制造队列状态流转。
- **Dependencies**: P0.1, P0.2
- **Acceptance Criteria**:
  - 关闭 rules 后不会产生隐藏换产时间。
  - `policy_snapshot` 能表达实际启用策略。
  - 规则启停有原因和审计。
  - 发布/队列关键动作有测试覆盖。
- **Validation**:
  - `python -m pytest tests/test_policy_settings.py tests/test_rule_enablement.py tests/test_publish_audit.py tests/test_queue_transitions.py tests/test_preplan_contract.py`

### Task P1.2: Commit Order Ingestion And Screening Closure

- **Location**:
  - `api/routers/orders.py`
  - `src/order_screening.py`
  - `tests/test_order_flow_sprint1.py`
  - `tests/test_order_import_flow.py`
  - `tests/test_order_screening.py`
  - `web/src/pages/OrdersPage.jsx`
  - `web/src/api/client.js`
- **Description**: 提交订单新建、导入预览/提交、订单修订审计、订单初筛和订单页初筛状态展示。
- **Dependencies**: P1.1 if shared API client changes conflict; otherwise can parallel review.
- **Acceptance Criteria**:
  - 新订单默认待排且可审计。
  - 导入可预览、可拒绝重复、可记录批次。
  - 订单初筛能给出可排、风险、阻断结果。
  - 订单页展示初筛状态，不影响分页/筛选。
- **Validation**:
  - `python -m pytest tests/test_order_flow_sprint1.py tests/test_order_import_flow.py tests/test_order_screening.py`
  - `cd web; npm run lint`

### Task P1.3: Commit Config UI And Localization

- **Location**:
  - `web/src/pages/ConfigPage.jsx`
  - `web/src/components/Layout.jsx`
  - `web/src/pages/Dashboard.jsx`
  - `web/src/pages/GanttPage.jsx`
  - `web/src/pages/MachinesPage.jsx`
  - `web/e2e/config-orders.spec.js`
  - `web/e2e/config-policy.spec.js`
  - `web/e2e/localization.spec.js`
  - `web/e2e/smoke-routes.spec.js`
- **Description**: 提交配置中心、规则启停 UI、订单配置入口、必要英文中文化和相关 e2e。
- **Dependencies**: P1.1, P1.2
- **Acceptance Criteria**:
  - `/config?tab=orders` 可完成订单配置动作。
  - `/config?tab=rules` 可启停规则并要求原因。
  - 主导航和页面核心文案中文化。
  - e2e 覆盖配置、中文化和主要路由。
- **Validation**:
  - `cd web; npm run e2e -- config-orders.spec.js config-policy.spec.js localization.spec.js smoke-routes.spec.js`
  - `cd web; npm run build`

## P2: Documentation And Demo Baseline

**Goal**: 把计划文档和演示输出变成可维护资产，而不是临时状态。

**Demo/Validation**:
- 文档可读、准确反映当前系统边界。
- 演示基线如果提交，能复现生成步骤。

### Task P2.1: Commit Clean Goal Documents

- **Location**:
  - `docs/config-policy-setup-rules-closed-loop-goal-plan.md`
  - `docs/order-flow-closed-loop-goal-plan.md`
  - `docs/workbench-interaction-cleanup-goal-plan.md`
  - `docs/workbench-wizard-flow-goal-plan.md`
  - `docs/git-status-cleanup-goal-plan.md`
- **Description**: 在确认无乱码后提交计划文档。
- **Dependencies**: P0.2
- **Acceptance Criteria**:
  - 文档标题和任务列表可读。
  - 已完成项和待完成项不混淆。
  - 文档不声称未验证内容已经完成。
- **Validation**:
  - `git diff -- docs`

### Task P2.2: Optional Demo Output Baseline Commit

- **Location**:
  - `output/material_correction.csv`
  - `output/schedule_result.csv`
  - `output/schedule_result.json`
- **Description**: 仅当这些文件用于演示、截图或测试基线时提交。
- **Dependencies**: P0.3
- **Acceptance Criteria**:
  - commit message 写明生成命令和数据口径。
  - 不和功能代码混在同一提交。
- **Validation**:
  - 重新运行生成命令后 diff 稳定。

## Final Verification Checklist

- `git status --short`
- `git diff --check`
- `python -m pytest`
- `cd web; npm run lint`
- `cd web; npm run build`
- `cd web; npm run e2e -- workbench.spec.js config-orders.spec.js config-policy.spec.js localization.spec.js smoke-routes.spec.js`

## Suggested Commit Order

1. `chore: ignore local runtime artifacts`
2. `feat: close schedule policy and rule runtime loop`
3. `feat: add order ingestion and screening flow`
4. `feat: complete config UI and localization checks`
5. `docs: add cleanup and workflow goal plans`
6. Optional: `chore: refresh scheduling demo outputs`

## Risks And Mitigations

- **Risk**: 文档乱码其实是终端显示问题，而不是文件损坏。
  **Mitigation**: 先用编辑器或 UTF-8 读取方式确认，不直接重写。

- **Risk**: `web/src/api/client.js` 同时被多个功能分组使用。
  **Mitigation**: 按实际 API export 所属功能拆 staging，必要时把 API client 放入先提交的后端/订单集成提交。

- **Risk**: `output/*` 是 tracked 文件，长期会持续污染状态。
  **Mitigation**: 明确是否作为演示基线；若不是，应后续讨论是否停止跟踪或迁移到 fixture。

- **Risk**: 后端 schema migration 目前通过运行时 `ALTER TABLE` 和 `db/init_schema.sql` 双轨维护。
  **Mitigation**: 提交前检查新增字段是否两边一致，并补一条 schema smoke 测试。

## Rollback Plan

- 单个功能提交出问题时，优先 revert 对应 commit。
- 生成产物提交若污染历史，单独 revert output commit。
- `.gitignore` 清理提交可保留，不影响业务运行。
