# 排程工人视角工作台 QA 修复与精简 Goal 计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking and are marked complete only after verification.

**Generated:** 2026-05-24  
**Estimated Complexity:** Medium  
**Target Surface:** `/workbench`, `/login`, schedule preplan APIs  
**Current Status:** verified as of 2026-06-08; see Completion Evidence and verification commands near the end of this document.
**Goal:** 修复浏览器实测发现的阻塞缺陷，并把排程工作台从“计划员/管理员混合页面”收敛成一线排程工人可以稳定使用的生产排程闭环。

---

## 1. 背景

2026-05-23 的浏览器 QA 从排程工人角度覆盖了：

- 登录、错误登录、进入 `/workbench`。
- 订单池搜索、筛选、选单、初筛根因查看。
- 创建草案、草案复核、资源视图、发布前校验、废弃草案。
- 高级维护入口可见性。
- 后端状态机、策略快照、订单初筛、HTTP contract、前端路由 smoke、生产 build。

主流程可用，但有三个必须处理的问题：

- **P1:** 人工调整交互可能让后端事务悬挂，导致后续接口等待数据库关系锁。
- **P2:** 登录错误响应为对象或数组时，前端把对象直接渲染为 React child，导致登录页崩溃。
- **P2:** 草案废弃后仍停留在草案复核语境，排程工人容易误以为还能继续处理该草案。

同时，当前工作台仍有计划员、管理员、配置、维护、版本审计等能力混在主流程里。一线排程工人的默认视图应更聚焦：今天该排哪些单、哪些单不能排、草案是否可发布、制造队列下一步是什么。

## 2. 非目标

- 不修改 OR-Tools 排程算法、换产规则、机台匹配规则。
- 不改变草案生命周期：`DRAFT -> VALIDATED -> CONFIRMED / CANCELLED`。
- 不默认执行正式发布、撤销正式排程、清理孤立订单。
- 不把配置中心、规则维护、订单录入完整搬进工作台。
- 不新增权限系统；只在现有角色能力上优化 UI 暴露方式。

## 3. 文件边界

- `api/routers/schedule.py`
  - 人工调整事务边界、异常回滚、schema ensure 执行策略。
  - 草案废弃后的返回契约如有必要可保持兼容扩展。

- `web/src/pages/LoginPage.jsx`
  - 登录错误详情规范化，避免对象渲染崩溃。

- `web/src/pages/ScheduleWorkbench.jsx`
  - 人工调整忙态恢复、废弃后路由/阶段归位、工人视角默认页面精简。

- `web/src/pages/workbenchViewModel.js`
  - 阶段主动作和工人视角可见能力派生逻辑。

- `web/src/index.css`
  - 工人视角密度、隐藏/折叠样式、异常提示样式。

- Tests:
  - `tests/test_queue_transitions.py`
  - `tests/test_policy_settings.py`
  - 新增或扩展 `tests/test_manual_adjustment_transaction.py`
  - `web/e2e/workbench.spec.js`
  - 新增或扩展 `web/e2e/login.spec.js`

## 4. Sprint 0: 复现保护和测试隔离

**Goal:** 在动代码前固定复现路径，避免再次把共享演示库锁住或误发布正式队列。

**Demo/Validation:**

- 可通过自动化或手工步骤稳定复现人工调整失败路径。
- 测试草案均能清理或废弃，订单状态保持 `PENDING`。
- 数据库锁等待能在测试后归零。

### Task 0.1: 写明人工调整复现脚本或测试夹具

- [ ] 记录复现路径：登录 -> 创建单订单草案 -> 选择已排订单 -> 发起人工调整 -> 提交非法或边界调整。
- [ ] 使用测试草案，不发布正式制造队列。
- [ ] 在测试后查询 `pg_stat_activity`，确认无 `wait_event_type='Lock'` 残留。

**Acceptance Criteria:**

- 复现失败不会要求人工去数据库杀会话。
- 如果测试触发异常，API 必须返回错误响应而不是长时间悬挂。

**Validation:**

```powershell
python -m pytest tests/test_manual_adjustment_transaction.py
```

### Task 0.2: 明确测试数据清理规则

- [ ] 所有 e2e 创建的草案使用独立 run，并在 `afterEach` 废弃。
- [ ] 发布成功路径必须立即 `clear-active` 或使用专门隔离数据库。
- [ ] 手工浏览器测试只走“校验到可发布”，默认不点“确认进入制造队列”。

**Acceptance Criteria:**

- `git status --short` 不受测试输出污染。
- 演示库订单池不会因为 QA 残留而持续减少。

## 5. Sprint 1: P1 人工调整事务与锁等待修复

**Goal:** 人工调整无论成功、校验失败、SQL 异常、客户端中断，都不能让事务悬挂或阻塞后续工作台接口。

**Demo/Validation:**

- 非法人工调整快速返回错误。
- 合法人工调整能记录审计并让草案回到需重新校验状态。
- 并发刷新 `/api/schedule/preplans`、`/api/schedule/settings` 不被调整事务锁住。

### Task 1.1: 收紧 `apply_manual_adjustment` 事务边界

- [ ] 用 `try/except` 包住 `api/routers/schedule.py` 的人工调整 DB 写路径。
- [ ] 对所有非预期异常执行 `db.rollback()` 后再抛出。
- [ ] 对校验失败路径明确 `commit` 或 `rollback` 策略，避免游离事务。
- [ ] 确认 `_get_schedule_settings()` 和 `_ensure_planning_schema()` 不在高频请求中持有不必要 DDL 锁。

**Acceptance Criteria:**

- 人工调整 API 不会留下 `idle in transaction`。
- lock wait 复测为 `0`。
- 失败响应中保留人能看懂的原因。

**Validation:**

```powershell
python -m pytest tests/test_manual_adjustment_transaction.py tests/test_policy_settings.py
```

### Task 1.2: 前端人工调整忙态兜底

- [ ] `submitAdjustment()` 在所有失败分支都恢复 `busy=false`。
- [ ] 提交按钮禁用态只绑定当前请求，不影响刷新、废弃、切换版本等无关按钮。
- [ ] 错误提示显示具体原因，而不是保留上一次“草案已创建”成功提示。

**Acceptance Criteria:**

- 提交非法调整后，按钮恢复可操作。
- 页面不需要刷新即可继续关闭表单或返回草案复核。

**Validation:**

```powershell
cd web
npm run e2e -- workbench.spec.js -g "manual adjustment"
```

### Task 1.3: 并发回归测试

- [ ] 在后端测试中模拟人工调整失败后立即调用 `get_preplans` / `get_schedule_settings`。
- [ ] 在 e2e 中提交非法调整后点击刷新或切换阶段。

**Acceptance Criteria:**

- 后续接口正常返回。
- UI 无长期 loading 或全局按钮持续 disabled。

## 6. Sprint 2: P2 登录错误和失败反馈修复

**Goal:** 登录失败、认证失败、接口校验失败都必须显示稳定中文错误，不允许 React runtime error。

**Demo/Validation:**

- 错误密码显示“用户名或密码错误”或后端明确错误。
- Pydantic/FastAPI 数组型 detail 被格式化为短文本。
- console 无 React child object 错误。

### Task 2.1: 统一登录错误格式化

- [ ] 在 `LoginPage.jsx` 增加本地 `formatLoginError()`，支持 string、array、object。
- [ ] 优先显示 `detail.message`、`detail[0].msg`，否则回退到 `登录失败`。
- [ ] 不直接把 `err.response.data.detail` 塞进 JSX。

**Acceptance Criteria:**

- 错误账号不会崩溃。
- 错误提示为字符串。

**Validation:**

```powershell
cd web
npm run e2e -- login.spec.js
```

### Task 2.2: 复用错误格式化策略

- [ ] 对比 `ScheduleWorkbench.jsx` 现有 `formatError()`。
- [ ] 如有重复逻辑，抽到轻量 helper 或保持页面内一致实现。
- [ ] 确认人工调整、发布、废弃、队列推进失败不会渲染对象。

**Acceptance Criteria:**

- 主要用户动作的失败提示都为字符串。
- 控制台无相关 React runtime error。

**Validation:**

```powershell
cd web
npm run e2e -- workbench.spec.js smoke-routes.spec.js
```

## 7. Sprint 3: 草案废弃后流程归位

**Goal:** 草案废弃后，排程工人明确回到“重新选择订单”或只读历史，而不是继续留在可处理的草案复核语境。

**Demo/Validation:**

- 废弃草案后订单仍为 `PENDING`。
- 页面主阶段回到订单池，或废弃草案只读展示且主按钮为“重新选择订单”。
- 不再展示可误点的校验、发布、人工调整入口。

### Task 3.1: 定义废弃后默认行为

- [ ] 推荐默认：废弃成功后自动切到 `order_pool`。
- [ ] 当前草案摘要可显示“#id 已废弃”，但主工作区回到订单池。
- [ ] 版本抽屉仍可打开废弃草案作为历史只读。

**Acceptance Criteria:**

- 废弃后不会停留在“已排订单 1”的复核表作为主任务。
- `重新选择订单` 是唯一主动作。

**Validation:**

```powershell
cd web
npm run e2e -- workbench.spec.js -g "cancels a draft safely"
```

### Task 3.2: 只读历史状态保护

- [ ] 如果用户从版本抽屉打开 `CANCELLED` 草案，禁用校验、发布、调整。
- [ ] Inspector 和阶段文案明确“历史草案，只读”。
- [ ] 队列阶段保持锁定。

**Acceptance Criteria:**

- 废弃草案不能触发任何写操作。
- 原废弃原因、废弃人、废弃时间可见。

## 8. Sprint 4: 排程工人视角 UI 精简

**Goal:** 默认工作台只保留一线排程工人高频动作，把管理员/计划员/审计能力折叠或迁移。

**Demo/Validation:**

- 首屏只回答：待排多少、风险多少、阻断多少、当前草案状态、下一步动作。
- 配置、维护、历史版本不抢主流程视觉权重。
- 主要按钮数量减少且无重复。

### Task 4.1: 精简首屏策略摘要

- [ ] `全局排程策略` 默认折叠为单行摘要。
- [ ] 仅保留影响当前草案的关键异常，例如“策略已变化”。
- [ ] “配置策略”仍链接到 `/config?tab=policy`，但不在工人主流程里展开所有 chip。

**Acceptance Criteria:**

- 首屏不会被 9 个策略 chip 占据主视觉。
- 工人无需理解每个系统开关即可继续排程。

### Task 4.2: 降级高级维护

- [ ] `高级维护` 默认只对管理员显示，或移入配置/管理页。
- [ ] 如果仍保留在工作台，默认折叠并增加强二次确认。
- [ ] 一线工人默认工作流不显示“撤销当前排程”“清理孤立已排订单”。

**Acceptance Criteria:**

- 普通排程工人首屏看不到危险维护按钮。
- 管理员仍能找到维护入口。

### Task 4.3: 合并复核标签

- [ ] 默认只显示三个工人视角标签：`需处理`、`已排`、`全部输入`。
- [ ] `草案阻断 / 未排订单 / 延期订单 / 可排订单` 作为“需处理”内二级筛选或高级筛选。
- [ ] 保留后端 bucket 语义，不丢失测试覆盖。

**Acceptance Criteria:**

- 标签数量从 7 个降到 3 个主标签。
- 阻断、未排、延期仍可定位。

### Task 4.4: 去重顶部导航动作

- [ ] 评估顶部“设置”和侧边栏“配置”的重复。
- [ ] “告警”无真实告警页前隐藏或改为真实入口。
- [ ] 保留一个清晰配置入口。

**Acceptance Criteria:**

- 顶部右侧不显示无功能或重复入口。
- 导航层级更符合工人巡检习惯。

## 9. Sprint 5: 完整验证与交付

**Goal:** 用自动化、浏览器、业务数据三层证明修复有效。

### Required Commands

```powershell
python -m pytest tests/test_manual_adjustment_transaction.py tests/test_queue_transitions.py tests/test_policy_settings.py tests/test_order_screening.py
$env:APS_RUN_HTTP_TESTS='1'; python -m pytest tests/test_api.py tests/test_preplan_contract.py
cd web
npm run lint
npm run build
npm run e2e -- login.spec.js workbench.spec.js smoke-routes.spec.js localization.spec.js
```

### Browser Acceptance Checklist

- [ ] 错误密码登录显示错误，不崩溃。
- [ ] 进入 `/workbench` 无 framework overlay。
- [ ] 首屏主动作唯一，无重复“刷新/校验/发布/废弃”。
- [ ] 搜索 `ORD-029`、筛选样品/万级洁净/可排后只显示目标订单。
- [ ] 创建草案、校验草案、废弃草案均有状态反馈。
- [ ] 废弃后自动回到订单池或只读历史，不可继续发布。
- [ ] 人工调整非法提交快速失败，按钮恢复，数据库无 lock wait。
- [ ] 1440x900、1280x720、1024x768 无横向滚动和按钮文字溢出。

## 10. 验收矩阵

| Priority | Scenario | Expected |
| --- | --- | --- |
| P1 | 人工调整异常 | API 快速返回，事务回滚，无 lock wait |
| P1 | 人工调整 UI | 忙态恢复，可关闭表单，可继续操作 |
| P2 | 错误登录 | 显示字符串错误，console 无 React child object 错误 |
| P2 | 废弃草案 | 订单仍 PENDING，页面回到订单池或只读历史 |
| P2 | 废弃历史 | 不允许校验、发布、人工调整 |
| P3 | 策略摘要 | 默认折叠，异常才突出 |
| P3 | 高级维护 | 默认不进入工人主流程 |
| P3 | 复核标签 | 主标签降噪，问题仍可定位 |
| P3 | 导航 | 无无效“告警”或重复配置入口 |
| P3 | 响应式 | 主要视口无横向滚动、无遮挡 |

## 11. Rollback Plan

- Sprint 1 可独立回滚，但必须保留防锁测试；如果修复失败，先禁用人工调整入口作为临时保护。
- Sprint 2 可独立回滚到原登录 UI，但必须避免对象渲染崩溃。
- Sprint 3 可回滚为废弃后保留草案详情，但必须强制只读。
- Sprint 4 UI 精简可按任务逐项回滚，不影响核心排程 API。

## 12. Definition of Done

- [x] 人工调整不再造成数据库事务悬挂或 schema DDL 锁等待。
- [x] 登录错误和主要 API 错误均稳定展示字符串提示。
- [x] 废弃草案后工人不会误判为可继续处理。
- [x] 工作台默认视角适合排程工人，而不是管理员配置台。
- [x] 自动化测试和浏览器 checklist 全部通过。
- [x] `git status --short` 清晰，只包含本计划实施相关文件。

## 13. Completion Evidence

**Completed:** 2026-05-24

- Backend: `apply_manual_adjustment` now has a route-level rollback guard for HTTP and unexpected exceptions, and planning schema initialization is cached per database target to avoid repeated high-frequency DDL.
- Login: `LoginPage.jsx` formats string, object, and array error details before rendering.
- Workbench flow: cancelled drafts now route the recommended worker stage back to `order_pool`; validation, confirm, and cancel actions are hidden after cancellation.
- Worker UI reduction: review tabs are reduced to `需处理 / 已排 / 全部输入`; policy chips are collapsed behind a one-line `策略摘要`; topbar duplicate `设置/告警` is removed; configuration and machine admin links are no longer primary worker navigation; advanced maintenance is hidden for planner workers and remains available to admin users.
- Responsive UI: the fixed sidebar collapses into a top navigation on narrow screens; 280x720 no longer has document-level horizontal scroll.

**Verification commands run:**

```powershell
python -m pytest tests/test_manual_adjustment_transaction.py tests/test_policy_settings.py -q
python -m pytest tests/test_manual_adjustment_transaction.py tests/test_queue_transitions.py tests/test_policy_settings.py tests/test_order_screening.py -q
$env:APS_RUN_HTTP_TESTS='1'; python -m pytest tests/test_api.py tests/test_preplan_contract.py -q
python -m pytest tests -q
cd web
npm run lint
npm run build
npm run e2e -- login.spec.js smoke-routes.spec.js localization.spec.js config-policy.spec.js
npm run e2e -- workbench.spec.js
```

**Manual/browser checks:**

- In-app browser opened `/login` and `/workbench` against local services.
- Planner worker view shows only worker primary navigation: `仪表盘 / 排程工作台 / 订单 / 甘特图`.
- Planner worker view hides advanced maintenance and duplicate topbar `设置/告警`.
- Policy summary and draft version drawer respond to click interactions.
- 1440x900 and 280x720 screenshots render without framework overlay.
- 280x720 check: `scrollWidth=280`, `clientWidth=280`, no horizontal scroll.
- PostgreSQL lock wait check: `pg_stat_activity wait_event_type='Lock'` count is `0`.
