# 订单流闭环目标计划

> **执行者说明**：本计划面向后续 agentic worker。执行编码时按任务顺序做 TDD，优先使用 `superpowers:executing-plans` 或 `superpowers:subagent-driven-development`，每个阶段完成后运行对应验证命令并记录结果。

**生成日期**：2026-05-22
**最近更新**：2026-05-23
**文档状态**：本轮编码闭环交接文档，开放问题留待后续产品决策
**当前基线**：截至 `codex/order-flow-sprint1` 当前提交，Sprint 1 到 Sprint 5 的订单入库、初筛、预排、修订、复核发布、制造队列推进和审计闭环已完成现阶段实现。
**目标**：让订单从入库、初筛、预排、修订、复核发布到制造队列推进，均可在前台 UI 中完成、解释、校验、追溯。

---

## 1. 产品口径

系统目标不是用自动排程完全替代人，而是替代“完全依靠经验人工排程”的低可追溯过程。前期必须保留计划员复核和人工调整能力：

1. 系统生成预排程草案。
2. 计划员复核草案，可查看无法排程、延期、可排但未落位订单的根因。
3. 计划员可人工调整草案，但必须记录操作者、原因、前后差异和校验结果。
4. 草案必须显式校验通过后，才能确认进入制造队列。
5. 发布后队列状态推进也要有原因和审计，不能只停留在“已排程”展示。

关键口径：如果计划员只是驳回草案，但不修改订单、规则、机台日历、约束或人工排程结果，那么再次求解很可能得到相同结果。系统应把“如何改变结果”的指导方向展示出来，例如修改订单交期、补齐物料、调整机台能力配置、修改约束开关，或通过人工调整记录明确覆盖系统建议。

## 2. 状态模型和不变量

| 对象 | 状态 | 口径 |
| --- | --- | --- |
| 订单 `production_orders.status` | `PENDING`, `SCHEDULED`, `IN_PRODUCTION`, `COMPLETED`, `CANCELLED` | `PENDING` 才能进入预排；只有发布成功后才变为 `SCHEDULED`。 |
| 草案 `schedule_runs.lifecycle_status` | `DRAFT`, `VALIDATED`, `CONFIRMED`, `SUPERSEDED`, `CANCELLED` | `DRAFT` 可复核/调整；`VALIDATED` 才允许在 review required 模式下发布；`CONFIRMED` 代表正式排程。 |
| 制造队列 `manufacturing_queue.queue_status` | `QUEUED`, `READY`, `IN_PRODUCTION`, `COMPLETED`, `ON_HOLD`, `CANCELLED` | 发布后写入 `QUEUED`；后续由执行侧推进。 |
| 初筛 | `ready`, `risk`, `blocked` | 第一阶段为 computed-only 结果，不新增订单生命周期状态。 |

必须长期保持的不变量：

- 创建预排草案不能改变订单状态，订单仍保持 `PENDING`。
- 只有发布成功才把已排任务对应订单改为 `SCHEDULED` 并写入制造队列。
- 订单创建、订单字段修订、人工调整、发布、撤销、队列状态推进都必须可追溯。
- 草案必须保存被选订单的版本快照或调度关键字段 hash。
- 调度关键字段变化后，旧草案必须在校验或发布时硬拦截。
- `review_required=true` 时，发布必须经过显式校验，不能直接从 `DRAFT` confirm。
- 手工调整是系统功能，不是绕过系统的后门。

## 3. 当前工作区基线

这部分用于替代旧文档里的“已确认缺口”。旧缺口中一部分已经在当前工作区实现，但尚未全部提交。

| 流程 | 当前能力 | 主要文件 | 状态 |
| --- | --- | --- | --- |
| 订单入库 | 后端已有 `POST /api/orders`，批量导入已有 preview/commit；UI 已提供批量导入入口和单订单新建入口。 | `api/routers/orders.py`, `web/src/pages/ConfigPage.jsx`, `web/src/api/client.js`, `tests/test_order_import_flow.py`, `web/e2e/config-orders.spec.js` | 已完成 |
| 订单修订 | `PATCH /api/orders/{order_id}` 已写入 `order_revision_audit`，返回受影响草案；UI 已要求修订原因并展示 revision id 和 impacted draft ids。 | `api/routers/orders.py`, `db/init_schema.sql`, `src/database.py`, `tests/test_order_flow_sprint1.py`, `web/e2e/config-orders.spec.js` | 已完成 |
| 草案快照 | 创建草案时保存 `order_snapshots`，校验可产生 `order_snapshot_stale` 硬错误。 | `api/routers/schedule.py`, `src/database.py`, `tests/test_order_flow_sprint1.py` | 已完成 |
| 订单初筛 | 已有 computed-only 初筛服务、API、UI badge/filter 和细分 recommended action。 | `src/order_screening.py`, `api/routers/orders.py`, `web/src/pages/OrdersPage.jsx`, `web/src/pages/ScheduleWorkbench.jsx`, `tests/test_order_screening.py` | 已完成 |
| 导入闭环 | 已有导入预览和提交，MVP 策略为 `reject_duplicates`。 | `api/routers/orders.py`, `web/src/pages/ConfigPage.jsx`, `tests/test_order_import_flow.py` | 已完成 |
| 复核发布 | `review_required=true` 时后端已要求 `VALIDATED`；UI 发布前需要先校验。 | `api/routers/schedule.py`, `web/src/pages/ScheduleWorkbench.jsx`, `web/e2e/workbench.spec.js` | 已完成 |
| 发布审计 | `PUBLISH` 和 `CLEAR_ACTIVE` 审计已落表，Inspector 可展示最近发布审计。 | `api/routers/schedule.py`, `db/init_schema.sql`, `src/database.py`, `tests/test_publish_audit.py` | 已完成 |
| 校验摘要 | validate 会写入 `last_validated_at` 和 `last_validation_summary`；confirm 会校验当前任务签名、错误数、警告数和最近校验摘要一致。 | `api/routers/schedule.py`, `tests/test_publish_audit.py` | 已完成 |
| 队列推进 | 已有 `PATCH /api/schedule/manufacturing-queue/{id}`、`QUEUE_STATUS_CHANGE` 审计、订单状态同步和工作台行级操作。 | `api/routers/schedule.py`, `tests/test_queue_transitions.py`, `web/src/pages/ScheduleWorkbench.jsx`, `web/e2e/workbench.spec.js` | 已完成 |

## 4. 端到端流程设计

### 4.1 订单入库

目标用户动作：

- 在 UI 批量导入真实订单数据，先预览，再提交。
- 在 UI 单独创建一个订单，用于临时插单或小批量补录。
- 导入或创建失败时显示行级或字段级原因，不静默忽略。

当前已具备：

- `POST /api/orders`
- `POST /api/orders/import-preview`
- `POST /api/orders/import-commit`
- `order_ingestion_batches`
- `order_ingestion_rows`
- `order_revision_audit`

本轮执行状态：

- `createOrder()` API client 已补齐。
- `/config?tab=orders` 已提供单订单新建入口。
- 导入提交和单订单新建后已刷新订单池、初筛结果和工作台待排订单。

### 4.2 订单初筛

目标用户动作：

- 订单入库后，计划员不需要先创建草案，就能看到订单是否 ready、risk 或 blocked。
- 风险和阻断原因必须指向可行动建议，例如补齐配方、调整机台能力、确认物料到料时间、修改交期。

当前已具备：

- `src/order_screening.py`
- `POST /api/orders/screening`
- `GET /api/orders/{order_id}/screening`
- `/orders` 初筛 badge
- `/workbench` 初筛筛选

本轮执行状态：

- recommended action 已按订单状态、产品、配方、机台能力、物料和交期风险细分。
- 工作台订单池在创建草案前主动触发初筛，避免用户看到空 badge。
- 初筛结果本轮保持 computed-only；后续只有在需要规则版本追溯时再引入 `order_screening_results`。

### 4.3 订单预排程

目标用户动作：

- 选择待排订单创建 `DRAFT` 草案。
- 主区优先显示订单维度复核表，突出未排、延期、阻断、可排但未落位订单。
- 资源视图作为二级 Tab，不再挤压订单复核主流程。

当前已具备：

- `POST /api/schedule/preplans`
- `GET /api/schedule/preplans/{run_id}` 返回订单桶。
- `unplaced_schedulable_orders` 已和 `scheduled_orders` 分离。
- 草案保存订单快照，便于 stale 拦截。

本轮执行状态：

- 主区已优化为“订单复核优先，资源视图次级”的工作区结构。
- Inspector 中根因分析已针对当前选中订单展示，同时保留整草案阻断摘要。
- 旧草案或修订后 stale 场景会以硬拦截和中文提示引导重新校验/重新预排。

### 4.4 订单修订

目标用户动作：

- 编辑订单时必须填写修订原因。
- 修改交期、规格、数量、洁净等级、订单类型、物料到料时间等调度关键字段后，系统提示影响了哪些草案。
- 如果旧草案受影响，发布必须被 `order_snapshot_stale` 拦截。

当前已具备：

- `PATCH /api/orders/{order_id}`
- `order_revision_audit`
- `impacted_draft_run_ids`
- `order_snapshot_stale`

本轮执行状态：

- UI 保存订单时已要求 `reason_text`，并随请求提交修订原因。
- UI 已展示 revision id 和受影响草案 ids。
- E2E 已覆盖“修订已选订单 -> 旧草案 stale 校验拦截”；重新预排和发布成功由工作台发布用例覆盖。

### 4.5 排程发布

目标用户动作：

- 计划员先校验草案，再确认进入制造队列。
- 发布成功后，能看到发布人、发布时间、订单数、警告数、队列行数。
- 发布失败时，错误信息必须是中文且能指导下一步动作。

当前已具备：

- `POST /api/schedule/preplans/{run_id}/validate`
- `POST /api/schedule/preplans/{run_id}/confirm`
- `review_required=true` 后端门禁
- `schedule_publish_audit`
- Inspector 最近发布审计
- 校验摘要持久化在 `schedule_runs.solver_params.last_validation_summary`

本轮执行状态：

- 发布拦截错误已在 UI 中按阻断、警告、stale 中文校验项分类展示；发布按钮会根据硬错误和警告发布策略禁用。

### 4.6 制造队列推进

目标用户动作：

- 发布后，制造队列不只是展示 `QUEUED`，还可以推进到 `READY`、`IN_PRODUCTION`、`COMPLETED`。
- `ON_HOLD` 和 `CANCELLED` 必须填写原因。
- 状态推进同步更新订单状态，并写入审计。

当前已具备：

- 队列状态迁移规则 helper。
- `tests/test_queue_transitions.py` 覆盖合法、非法、终态和原因必填。
- `PATCH /api/schedule/manufacturing-queue/{id}` 可推进 active confirmed 队列项。
- `QUEUE_STATUS_CHANGE` 写入 `schedule_publish_audit`。
- 工作台制造队列行可执行备料完成、开工、完工、暂停、取消。

后续范围：

- 队列操作权限、真实车间反馈和返工/异常完工仍属于后续生产适配范围。

## 5. 当前优先级

### P0：补齐产品闭环硬缺口

- [x] **Task A：持久化校验摘要**
  - 修改：`api/routers/schedule.py`
  - 测试：新增或扩展 `tests/test_publish_audit.py`
  - 验收：validate 写入 `solver_params.last_validated_at`、hard error count、warning count、validator version；人工调整或 stale 使摘要失效；confirm 校验摘要仍匹配当前任务集。

- [x] **Task B：队列状态迁移 API**
  - 修改：`api/routers/schedule.py`
  - 测试：扩展 `tests/test_queue_transitions.py`
  - 验收：`QUEUED -> READY -> IN_PRODUCTION -> COMPLETED` 可执行；非法迁移返回中文 400；`ON_HOLD/CANCELLED` 必须有原因；终态不可回退。

- [x] **Task C：队列状态审计和订单状态同步**
  - 修改：`api/routers/schedule.py`，复用既有 `schedule_publish_audit`
  - 测试：扩展 `tests/test_queue_transitions.py`
  - 验收：写入 `QUEUE_STATUS_CHANGE`；`IN_PRODUCTION` 同步订单为 `IN_PRODUCTION`；`COMPLETED` 同步订单为 `COMPLETED`；可取消的未开工项回到 `PENDING`。

- [x] **Task D：队列推进 UI**
  - 修改：`web/src/api/client.js`, `web/src/pages/ScheduleWorkbench.jsx`
  - 测试：扩展 `web/e2e/workbench.spec.js`
  - 验收：active confirmed 队列行显示可用动作；暂停/取消时要求原因；操作后刷新队列、订单状态和审计。

### P1：补齐 UI 语义和演示可解释性

- [x] **Task E：单订单新建 UI**
  - 修改：`web/src/api/client.js`, `web/src/pages/ConfigPage.jsx` 或 `web/src/pages/OrdersPage.jsx`
  - 验收：用户可在前台创建合法订单；重复订单显示冲突；新订单能立即出现在工作台待排池。
  - 本轮验证：`web/e2e/config-orders.spec.js` 覆盖新建订单、修订后保存、进入工作台待排池。

- [x] **Task F：订单修订原因和影响范围提示**
  - 修改：`web/src/pages/ConfigPage.jsx`
  - 验收：保存调度关键字段变更时要求原因；保存成功展示 revision id 和 impacted draft ids。
  - 本轮验证：`web/e2e/config-orders.spec.js` 覆盖无修订原因拦截、展示修订号、展示受影响草案，以及旧草案 stale 校验拦截。

- [x] **Task G：工作台主区复核体验**
  - 修改：`web/src/pages/ScheduleWorkbench.jsx`
  - 验收：默认显示订单维度复核表；资源视图改为主区二级 Tab；Inspector 固定展示当前草案状态、当前订单根因、调整入口和审计。
  - 本轮验证：`web/e2e/workbench.spec.js` 覆盖订单复核主视图、资源视图二级 Tab、固定 Inspector 布局、当前订单复核和发布审计中文化。

- [x] **Task H：中文化清理**
  - 修改：`web/src/pages/*.jsx`, `web/src/api/client.js` 的可见错误兜底文案
  - 验收：订单类型、状态、按钮、错误原因、空状态和表头不再暴露非必要英文；接口返回 code 可保留，但 UI 必须有中文解释。
  - 本轮验证：`web/e2e/localization.spec.js` 覆盖甘特图关键标题；`workbench.spec.js` 覆盖发布审计不暴露 `PUBLISH`；配置页补充客户等级、洁净等级、初筛和导入状态中文显示。

### P2：增强真实生产适配

- [x] **Task I：初筛 recommended action 细分**
  - 修改：`src/order_screening.py`, `web/src/pages/ScheduleWorkbench.jsx`
  - 验收：每个阻断或风险原因至少给出一个明确动作入口或处理建议。
  - 本轮验证：`tests/test_order_screening.py` 覆盖状态、产品、配方、机台能力、物料和交期风险的动作分类；`web/e2e/workbench.spec.js` 覆盖工作台待排订单池展示推荐动作入口。

- [x] **Task J：持久化初筛结果评估**
  - 只有当演示需要规则版本追溯时再做。
  - 验收：引入 `order_screening_results` 前，需要先确认规则版本、机台能力快照和过期策略。
  - 本轮评估：当前演示仍以工作台实时 computed screening 为准，不新增持久化表；原因是规则版本、机台能力快照和过期策略尚未产品化，提前落表会制造“历史初筛结果可信度”的误导。后续若要做规则版本追溯，再单独设计 `order_screening_results`。

## 6. 闭环验收矩阵

| 流程 | 验收用例 | 期望结果 | 优先级 | 当前状态 |
| --- | --- | --- | --- | --- |
| 订单入库 | 批量导入包含合法、重复、非法行 | 预览显示 new/conflict/rejected，提交只写入 accepted rows | P0 | 已完成 |
| 订单入库 | UI 创建单个合法订单 | 订单为 `PENDING`，写入创建审计，可在订单列表和工作台看到 | P1 | 已完成 |
| 订单初筛 | 对待排订单运行初筛 | 返回 ready/risk/blocked，展示 evidence 和 recommended action | P0 | 已完成 |
| 订单预排 | 选择 ready 订单创建草案 | 生成 `DRAFT`，订单仍为 `PENDING`，草案含订单快照 | P0 | 已完成 |
| 订单预排 | 存在可排但未落位订单 | 在订单维度复核表显示 `unplaced_schedulable_orders`，不误归为已排 | P0 | 已完成 |
| 订单修订 | 修订已被草案选中的订单交期或规格 | 写入修订审计，返回 impacted draft ids | P0 | 已完成 |
| 草案失效 | 修订后尝试发布旧草案 | `order_snapshot_stale` 硬拦截，UI 指导重新预排 | P0 | 已完成 |
| 人工调整 | 对草案移动或插入任务 | 写入调整审计，已校验草案回退为 `DRAFT` | P1 | 已完成 |
| 显式复核 | `review_required=true` 时直接 confirm `DRAFT` | 后端 400，UI 禁用发布 | P0 | 已完成 |
| 排程发布 | 校验通过后发布 | run 变为 `CONFIRMED`，订单变 `SCHEDULED`，队列写入 `QUEUED` | P0 | 已完成 |
| 发布审计 | 发布成功后查看 Inspector | 展示发布人、发布时间、订单数、警告数、队列行数 | P1 | 已完成 |
| 校验摘要 | validate 后调整草案再 confirm | 摘要失效，要求重新校验 | P0 | 已完成 |
| 队列推进 | 将队列项从 `QUEUED` 推进到 `READY` | 状态更新，审计记录可见 | P0 | 已完成 |
| 队列推进 | 将队列项推进到 `IN_PRODUCTION` 和 `COMPLETED` | 订单状态同步更新 | P0 | 已完成 |

## 7. 验证策略

### 7.1 已知最近验证

当前工作区已完成以下验证：

```powershell
python -m pytest
cd web
npm run lint
npm run build
```

2026-05-23 结果：

- `python -m pytest tests/test_order_flow_sprint1.py tests/test_order_screening.py tests/test_order_import_flow.py tests/test_publish_audit.py tests/test_queue_transitions.py`：29 passed。
- `python -m pytest`：81 passed, 8 skipped。
- `cd web; npm run lint`：passed。
- `cd web; npm run build`：passed，仍有既有 large chunk warning。
- `APS_RUN_HTTP_TESTS=1` 下 `tests/test_api.py tests/test_preplan_contract.py`：8 passed。
- `cd web; npm run e2e -- workbench.spec.js`：5 passed，覆盖发布后制造队列 `QUEUED -> READY` UI 操作。
- `cd web; npm run e2e -- config-orders.spec.js`：2 passed，覆盖单订单 UI 新建、修订原因、受影响草案和 stale 校验提示。
- `cd web; npm run e2e -- localization.spec.js`：1 passed，覆盖甘特图导航和页面关键中文标题。
- `cd web; npm run e2e -- workbench.spec.js -g "publishes a valid draft"`：1 passed，覆盖发布审计事件中文显示且不暴露 `PUBLISH`。
- 本轮最终回归：`python -m pytest`：82 passed, 8 skipped；`cd web; npm run lint`：passed；`cd web; npm run build`：passed，仍有既有 large chunk warning；`APS_RUN_HTTP_TESTS=1` 下 `tests/test_api.py tests/test_preplan_contract.py`：8 passed；`cd web; npm run e2e`：10 passed。
- 主路由 smoke：`cd web; npm run e2e -- smoke-routes.spec.js`：1 passed，覆盖 `/orders`、`/config?tab=orders`、`/workbench`、`/gantt`、`/dashboard` 渲染非空、中文关键内容、无前端错误覆盖和无运行时 console/page error。
- P2 初筛动作验证：`python -m pytest tests/test_order_screening.py -k specific_action`：1 passed；`cd web; npm run e2e -- workbench.spec.js -g "screening recommended actions"`：1 passed。

### 7.2 后续变更必须验证

后续继续改动订单流、工作台或算法约束后必须至少运行：

```powershell
python -m pytest tests/test_order_flow_sprint1.py tests/test_order_screening.py tests/test_order_import_flow.py tests/test_publish_audit.py tests/test_queue_transitions.py
python -m pytest
cd web
npm run lint
npm run build
```

如果 8000 和 3000 服务可用，再运行：

```powershell
$env:APS_API_BASE_URL='http://127.0.0.1:8000'
$env:APS_WEB_BASE_URL='http://127.0.0.1:3000'
cd web
npm run e2e
```

### 7.3 Browser smoke

P0/P1 完成后至少检查：

- `/orders`
- `/config?tab=orders`
- `/workbench`
- `/gantt`
- `/dashboard`

检查重点：

- 页面是否出现英文状态泄露。
- 工作台主区是否优先解释订单复核。
- Inspector 是否能解释当前订单根因和操作审计。
- 制造队列是否能推进状态且刷新正确。
- 发布失败、stale、队列非法迁移是否显示中文原因。

## 8. 回滚和降级策略

- 单订单新建 UI 可用功能开关隐藏，不影响批量导入和已有订单编辑。
- stale validation 不应在最终演示中降级为 warning；只允许开发期间临时降级用于定位问题。
- 初筛保持 computed-only，可在 UI 关闭，不改变订单状态。
- 导入提交短期只支持 `reject_duplicates`，覆盖策略留到真实业务确认后再做。
- review gate 只在 `review_required=true` 下强制启用。
- 队列迁移第一阶段只服务演示和计划交接，不接入真实车间反馈。

## 9. 开放问题

- 后续是否允许导入覆盖已有 `PENDING` 订单，还是长期坚持 `reject_duplicates` + 人工修订。
- 何时把 computed screening 升级为持久化 `order_screening_results`。
- `MANUAL` 模式是否近期开放，还是先固定为 `AUTO/HYBRID`。
- 制造队列状态推进是否只服务演示，还是要接入真实车间执行反馈和权限模型。
- 初筛 recommended action 是否只给配置入口，还是允许直接发起订单修订或规则修订流程。
- 发布后发现订单字段错误时，是撤销 active schedule 后重新预排，还是允许对未开工队列项做局部变更。
- 队列暂停、取消、返工是否需要独立权限，还是沿用 planner/admin。
