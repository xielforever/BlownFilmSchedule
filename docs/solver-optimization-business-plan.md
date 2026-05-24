# Plan: Solver Optimization With Configurable Business Strategy

**Generated**: 2026-05-24
**Estimated Complexity**: High

## Overview

当前排程优化的方向应从“求解器给出一个可行排程”升级为“系统先治理订单池，再用可配置策略生成可发布、可解释、可复盘的车间计划”。

本计划补充两个硬原则：

1. **所有策略必须可配置，不能硬编码在求解器里。** 包括计划窗口、订单准入规则、交期权重、急单优先级、清场规则、弧裁剪、候选订单拒排惩罚、求解 profile、是否启用某类软约束等。但“可配置”不等于“可随意关闭”：安全、法规、机台物理能力类硬规则只能配置参数和适用范围，不能被普通排程 profile 绕过。
2. **订单入库后必须先做基础判断。** 明显超出全部机台能力、洁净等级不匹配、层数超限、原料晚于交期、关键字段缺失等订单，不能直接进入排程订单池。这类订单大概率是信息错误、订单工艺未维护、机台主数据缺失或商务交期不可承诺，应该进入“待处理/异常订单池”。

求解器的职责边界应更清晰：

- 求解器处理“业务上有资格排程”的订单。
- 订单池治理处理“数据错误、能力不匹配、业务未确认”的订单。
- 策略配置决定“哪些订单进入本轮、哪些进入候选、哪些延后、哪些阻断发布”。
- 诊断和 UI 负责把原因讲清楚，而不是让排程工人从失败结果里猜原因。

## Current Evidence From Codebase

- 当前已有策略开关基础，例如 `schedule_settings` 中有 material、cleanroom、machine capability、due date 等启用项。
- 当前已有订单初筛能力，`order_screening.py` 可以给出 `ready`、`risk`、`blocked`。
- 当前已有机台能力判断，`evaluate_machine_fit` 可以识别幅宽、厚度、洁净等级、层数等不匹配。
- 当前排程器仍会在 `run()` 内部再次过滤无可用机台订单，并可能返回 `PARTIAL`。
- 当前求解核心是 CP-SAT 两阶段优化：先加权延期，再换产优化。

结论：系统已经有基础能力，但缺少一个明确的“订单准入 -> 策略快照 -> 求解 -> 发布校验”的闭环。下一步应先把边界和配置体系补齐，再优化求解器模型。

## Design Principles

### Principle 1: Strategy-as-Configuration

所有会影响排程结果的规则都必须来自配置、规则表、策略快照或运行参数，不能散落在代码常量和模型构造逻辑里。

必须配置化的策略包括：

- 计划窗口：例如 1 天、3 天、7 天、按班次、按自然周。
- 订单准入规则：哪些 blocked 订单不得进入排程池。
- 订单桶规则：ready、risk、blocked、candidate、deferred、must_schedule。
- 客户和订单优先级：VIP、URGENT、SAMPLE、NORMAL 的权重。
- 交期目标：是否优化 due date、允许最大延期、延期惩罚函数。
- 72h 清场：连续运行上限、清场时长、适用机台、适用品类、enforcement mode。
- 维护窗口：是否启用、临时停机是否参与求解。
- 洁净等级保护：普通订单是否允许占用高洁净机台、保护阈值。
- 弧裁剪：是否启用、top-k、最大换产阈值、交期窗口裁剪范围。
- 候选订单接受策略：拒排惩罚、候选订单最大占用比例。
- 求解 profile：fast、standard、deep 的时间限制、gap、随机种子、多轮策略。
- 人工锁定策略：已开工必锁、已发布是否允许移动、移动审批要求。

配置必须分级治理：

| Strategy Type | 示例 | 允许普通配置 | 允许关闭 | 发布要求 |
| --- | --- | --- | --- | --- |
| 物理能力硬约束 | 幅宽、厚度、层数、可用机台 | 是，配置机台能力 | 否 | 违反即不可发布 |
| 合规/安全硬约束 | 72h 清场、维护窗口、洁净等级 | 是，配置阈值和适用范围 | 默认否 | 违反即不可发布 |
| 业务硬约束 | 已开工任务锁定、订单状态准入 | 是，配置策略 | 受限 | 需审计和权限 |
| 业务软约束 | 交期权重、换产惩罚、洁净机台保护 | 是 | 是 | 影响目标函数，不应破坏硬约束 |
| 性能策略 | 弧裁剪、求解时间、gap、多种子 | 是 | 是 | 必须输出求解质量和裁剪信息 |

合规/安全硬约束不提供普通 `enabled=false`。应使用 `enforcement_mode = hard | publish_blocker | experimental_disabled` 表达治理方式。`experimental_disabled` 只能由管理员启用，必须记录操作者、原因、有效期和策略版本；草案必须显示高风险标识；默认不得确认发布到制造队列，除非后续引入更高等级的二次审批机制。

### Principle 2: Policy And Input Snapshot For Every Preplan

每次创建预排草案时，都要保存当时的策略快照和输入快照。后续如果配置、订单、机台、维护日历、产品工艺或规则矩阵发生变化，旧草案必须提示快照已过期，不能静默沿用。

策略快照至少包含：

- 策略版本号。
- 启用/禁用的规则。
- 订单准入阈值。
- 求解 profile。
- 清场、维护、洁净、交期、换产、弧裁剪参数。
- 策略来源：数据库配置、默认配置、实验配置。

输入快照至少包含：

- 参与草案的订单 ID 列表、订单 revision/hash、关键字段摘要。
- 机台能力版本或 machine capability hash。
- 维护日历和临时停机版本。
- 换产矩阵、GMP 清场矩阵、材料切换矩阵版本。
- 产品工艺和材料序列版本。
- 创建草案时的 screening snapshot。

发布前校验应比较当前快照和草案快照。如果策略未变但订单交期、机台能力或维护窗口变了，也应提示 stale，并要求重新预排或重新验证。

版本/hash 来源必须先定义，不能在各调用点临时拼接。建议规则：

- 订单：使用 `updated_at`、关键字段和状态生成 order snapshot hash；后续可升级为显式 `revision`。
- 机台能力：使用 active machine rows 的能力字段、状态、更新时间生成 machine capability hash。
- 维护日历：使用机台日历事件类型、起止时间、状态、更新时间生成 calendar hash。
- 规则矩阵：使用 GMP 清场矩阵、材料切换矩阵、setup 规则的版本或内容 hash。
- 产品工艺：使用产品类型、材料序列、层数要求和更新时间生成 process hash。

这些 hash 的生成逻辑应集中在后端服务层，并被草案创建、草案详情、发布校验和测试共用。

### Principle 3: Solver Only Sees Eligible Work

明显不可排或疑似错误的订单，不应作为求解变量进入 CP-SAT。

这不是为了“隐藏问题”，而是为了把问题放在正确的处理流程：

- 信息错误：回订单维护。
- 主数据缺失：回工艺/机台配置。
- 商务不可承诺：回交期确认。
- 短期无法排：进入 deferred 或 next-cycle。
- 有资格排程：进入 solver。

### Principle 4: Backend Owns Bucket Semantics

订单桶、草案桶和发布阻断原因必须由后端统一计算并返回，前端只负责展示。UI 不应自行推断一个订单到底是 blocked、deferred、unplaced 还是 scheduled。

草案层面建议保持以下互斥不变量：

```text
selected_input_orders
  = scheduled_orders
  + deferred_orders
  + blocked_orders
  + unplaced_solver_failed_orders
```

其中：

- `scheduled_orders`：已被求解器落位到机台时间轴。
- `deferred_orders`：业务上可排，但按计划窗口或候选策略推迟到本轮之外。
- `blocked_orders`：数据、能力、合规或策略原因导致不得进入本轮求解。
- `unplaced_solver_failed_orders`：有资格进入求解，但求解器在当前时间、策略或锁定条件下未能落位。

`blocked` 和 `deferred` 不能混用。`blocked` 表示需要修数据、修规则、调整策略或业务确认；`deferred` 表示订单没有错误，只是本轮不排。

这个不变量只覆盖“已被选择进入当前草案输入”的订单。没有被选择的 `ready`、`risk` 或 `candidate` 订单仍留在订单池，不应在该草案中记为 `deferred` 或 `blocked`。

## Order Pool Governance

### Order Lifecycle Buckets

建议把订单入库后的排程相关状态分为以下桶。注意：这些桶可以是 computed status，不一定都要变成订单生命周期状态。

| Bucket | 含义 | 是否进入求解器 | 排程工人动作 |
| --- | --- | --- | --- |
| `ready` | 数据完整且至少有一台机台可做 | 是 | 可直接选择进入本轮 |
| `risk` | 可做但交期、原料、洁净资源或换产风险高 | 可配置 | 复核后进入本轮或候选 |
| `candidate` | 远期可排订单 | 可配置 | 通常进入候选，不抢本轮产能 |
| `blocked_data_error` | 字段缺失、非法值、疑似录入错误 | 否 | 修正订单数据 |
| `blocked_machine_capability` | 全部机台能力不满足 | 否 | 核对幅宽、厚度、层数、机台主数据 |
| `blocked_cleanroom` | 洁净要求无机台满足 | 否 | 核对洁净要求或机台等级 |
| `blocked_material` | 原料到料晚于交期、到料未知或关键物料缺失 | 否 | 修改到料时间、确认替代物料或调整交期 |
| `blocked_policy` | 被当前策略禁止进入本轮 | 否 | 调整策略或手动豁免 |
| `deferred` | 本周期不排，但不是错误订单 | 否或候选 | 进入下周期或候选池 |

### Override Policy

人工豁免必须有明确边界，不能把明显不可制造订单送入正式求解。

| Bucket | 默认是否允许豁免进入正式排程 | 说明 |
| --- | --- | --- |
| `risk` | 是 | 需要记录原因，草案显示风险标识 |
| `candidate` | 是 | 由计划窗口策略或排程工人选择 |
| `blocked_policy` | 受限允许 | 需要权限、原因和策略快照 |
| `blocked_material` | 受限允许 | 仅适用于到料时间不确定、替代物料已确认或业务同步调整交期的情况 |
| `blocked_data_error` | 否 | 必须修正数据后重新筛选 |
| `blocked_machine_capability` | 否 | 必须修正订单、拆单、外协或补充机台主数据 |
| `blocked_cleanroom` | 否 | 必须修正洁净要求、补充洁净机台或调整生产方案 |

实验模式可以允许更宽的豁免用于算法验证，但实验草案不得进入正式制造队列。

### Basic Checks After Order Insert

订单入库后应立即执行基础判断，不等到创建草案时才发现。

必做判断：

- `order_id`、产品类型、数量、目标宽度、厚度、交期、订单类型、洁净要求是否完整。
- 宽度、厚度是否落在任一 active 机台能力范围内。
- 配方层数是否超过所有 active 机台层数能力。
- Class_10K 等高洁净订单是否存在可用洁净机台。
- 原料到料时间是否晚于交期。
- 订单状态是否允许进入预排，例如仅 `PENDING` 可进入。
- 产品工艺、材料序列、换产规则是否缺失或降级。

这些判断结果应写入订单筛选结果或诊断表，并在订单池 UI 中可见。

筛选结果建议分两层保存：

- 最新筛选缓存：用于订单列表、订单池和异常订单视图，随订单、机台、规则或策略变化重新计算。
- 草案筛选快照：创建预排草案时固化，保证后续复核、导出和审计能还原当时为什么某个订单进入或未进入求解。

缓存失效必须覆盖所有筛选依赖，不只覆盖订单本身。订单关键字段、机台能力、机台状态、洁净等级、产品工艺、材料序列、维护日历、规则矩阵和策略版本变化时，相关订单的最新筛选缓存都应标记 stale 或触发重算。

### Handling Obviously Impossible Orders

明显超出机台限制的订单不应进入排程订单池，建议流程如下：

1. 入库成功，但标记为 `blocked_machine_capability`。
2. 不出现在默认“可排订单池”中。
3. 出现在“需处理订单”或“异常订单”视图。
4. 给出结构化原因，例如“目标幅宽 9999 超出所有 active 机台最大幅宽”。
5. 提供推荐动作：修正订单、补充机台能力、拆单、外协、调整商务交期、取消预排。
6. 只有修正后重新筛选为 `ready` 或 `risk`，才能进入排程池。

这个机制比让 solver 返回 `PARTIAL` 更适合实际业务，因为排程工人可以在创建草案前就处理异常。

## Business Scenarios

### Scenario 1: 每日早会排程

早会前，排程工人只应看到经过准入治理后的订单池。

关键要求：

- 默认只选择 `ready` 和经确认的 `risk` 订单。
- `blocked_*` 订单不参与求解，独立展示为需处理事项。
- 本周期窗口、候选订单范围和急单权重来自配置。
- 生成草案时保存 policy snapshot。

### Scenario 2: 急单插入

急单插入不应靠代码里固定的权重实现。

关键要求：

- VIP、URGENT、SAMPLE 的权重可配置。
- 是否允许急单挤占普通订单可配置。
- 被挤出的订单进入 `deferred`，并说明原因。
- 已开工、已锁定、已发布任务的移动策略可配置。

### Scenario 3: 原料未齐套

原料晚到不一定是 blocked，需要按策略区分。

关键要求：

- 原料晚于交期：默认 blocked；必须调整交期、确认替代物料或业务确认后重新筛选，不能直接进入正式排程。
- 原料晚于计划窗口开始但仍可按期完成：risk。
- 原料到料时间不确定：risk 或 blocked，由策略决定，可在有权限审批后进入候选。
- solver 使用 material availability 作为硬下界。

### Scenario 4: 洁净等级保护

高洁净机台是稀缺资源，应有保护策略。

关键要求：

- 普通订单是否允许使用高洁净机台可配置。
- 高洁净机台普通订单占用比例可配置。
- 高洁净订单不足时是否释放机台给普通订单可配置。
- 诊断显示高洁净产能被哪些订单占用。

### Scenario 5: 72h 连续运行清场

72h 清场必须配置化，但不能变成随意关闭的安全漏洞。

关键要求：

- 连续运行上限、清场时长、适用机台、适用品类可配置。
- 默认作为硬约束或发布阻断。
- fast/standard/deep profile 可以影响求解时间，不能绕过清场合规。
- 若策略允许实验性关闭，必须在草案和发布审计中突出显示。

### Scenario 6: 维护窗口和临时停机

维护、清洁、试机、品质等待都应统一为机台日历约束。

关键要求：

- 日历事件类型可配置。
- 是否参与求解可配置。
- 临时停机影响已发布任务时，支持局部重排。
- 诊断说明维护窗口造成的延期和瓶颈。

## Implementation Sprints

## Sprint 0: Strategy Configuration Foundation

**Goal**: 建立排程策略配置中心，禁止新增硬编码业务策略。

**Demo/Validation**:

- 管理端可以看到当前策略。
- 新建草案保存策略快照。
- 修改策略后，旧草案提示 stale。

### Task 0A.1: Define minimal strategy schema

- **Location**: `src/config.py`, `src/database.py`, `src/models.py`, tests
- **Description**: 先定义求解器和订单筛选必须消费的最小策略 schema，覆盖订单准入、计划窗口、权重、清场、弧裁剪、求解 profile、锁定策略。
- **Dependencies**: None
- **Acceptance Criteria**:
  - 所有策略字段有默认值、说明、类型校验。
  - 没有新增业务阈值直接写死在 solver 中。
  - 策略支持版本号。
  - 每个字段标注 rule class：hard、soft、performance、experimental。
- **Validation**:
  - 策略 schema 单元测试。
  - 默认策略快照测试。

### Task 0A.2: Persist minimal strategy and snapshot

- **Location**: `src/database.py`, API routes, tests
- **Description**: 扩展现有 schedule settings，先保存最小策略配置，并在草案创建时写入策略快照。
- **Dependencies**: Task 0A.1
- **Acceptance Criteria**:
  - 每次修改产生新版本。
  - 草案引用创建时的策略版本。
  - 草案详情能返回 policy snapshot。
- **Validation**:
  - API 测试覆盖读取、修改、版本递增。
  - `tests/test_preplan_contract.py` 增加快照断言。

### Task 0A.3: Define snapshot hash sources

- **Location**: preplan creation path, `src/database.py`, tests
- **Description**: 定义订单、机台能力、维护日历、规则矩阵、产品工艺和筛选结果的 revision/hash 生成规则。
- **Dependencies**: Task 0A.2
- **Acceptance Criteria**:
  - hash 生成逻辑集中复用，不在接口、UI 或测试里重复拼接。
  - 同一输入生成稳定 hash，关键字段变化会改变 hash。
  - tests 覆盖订单、机台、维护日历和规则矩阵变化。
- **Validation**:
  - 修改订单交期、机台能力或维护窗口后，对应 hash 变化。

### Task 0A.4: Add input snapshot to preplan creation

- **Location**: preplan creation path, `src/database.py`, tests
- **Description**: 创建草案时保存订单、机台、规则、维护日历和筛选结果快照。
- **Dependencies**: Task 0A.3
- **Acceptance Criteria**:
  - 草案详情能返回 input snapshot 摘要。
  - 当前策略或输入主数据变更后，旧草案显示 stale。
  - 发布前校验策略快照和输入快照是否仍可接受。
- **Validation**:
  - 修改订单交期、机台能力或维护窗口后，旧草案 validation 出现 stale 阻断项。

### Task 0B.1: Expose strategy management UI

- **Location**: workbench/admin UI, API routes
- **Description**: 在管理端展示和修改策略。首版只开放安全的软策略和求解 profile；硬规则参数修改需要 admin 权限。
- **Dependencies**: Task 0A.2
- **Acceptance Criteria**:
  - 策略可在管理界面查看和修改。
  - 硬规则字段显示风险说明和权限要求。
  - 修改后展示新策略版本。
- **Validation**:
  - API 和浏览器测试覆盖策略查看、修改、版本更新。

### Task 0C.1: Add strategy audit and permission gates

- **Location**: audit table, API routes, admin UI
- **Description**: 对硬规则、实验模式、人工豁免、发布阻断降级等高风险操作增加审计和权限。
- **Dependencies**: Task 0B.1
- **Acceptance Criteria**:
  - 高风险策略修改必须记录 actor、reason、before、after、version。
  - 普通 planner 无法关闭或降级硬约束。
  - 实验模式草案默认不可正式发布。
- **Validation**:
  - 权限测试和审计测试。

## Sprint 1: Order Intake Screening And Pool Governance

**Goal**: 订单入库后立即完成基础判断，把明显异常订单挡在排程池外。

**Demo/Validation**:

- 导入一个超宽订单，入库成功但不进入可排订单池。
- 订单池默认只展示 `ready`、可选 `risk`。
- 异常订单有原因和处理建议。

### Task 1.1: Run screening after order insert/import

- **Location**: order creation/import path, `src/order_screening.py`, `src/database.py`
- **Description**: 订单新增或导入后立即运行基础筛选，保存 computed screening result。
- **Dependencies**: Sprint 0 strategy schema
- **Acceptance Criteria**:
  - 新订单有 screening status。
  - 修改订单关键字段后自动重新筛选。
  - screening 使用当前策略配置。
  - 草案创建时保存 screening snapshot。
- **Validation**:
  - 创建订单、导入订单、修改订单的测试均验证 screening result。
  - 草案详情验证 screening snapshot 可追溯。

### Task 1.1B: Invalidate screening cache on dependency changes

- **Location**: `src/order_screening.py`, `src/database.py`, API routes, tests
- **Description**: 当机台能力、机台状态、洁净等级、产品工艺、材料序列、维护日历、规则矩阵或策略版本变化时，标记相关订单筛选缓存 stale 或批量重算。
- **Dependencies**: Task 1.1, Task 0A.3
- **Acceptance Criteria**:
  - 订单字段变化会重算该订单筛选。
  - 机台能力或洁净等级变化会影响相关 ready/blocked 判断。
  - 策略版本变化后订单池提示筛选结果需刷新。
- **Validation**:
  - 修改机台最大幅宽后，原 `blocked_machine_capability` 订单可重新筛选为 `ready` 或 `risk`。

### Task 1.2: Split order pool from exception pool

- **Location**: workbench API/UI, order list UI
- **Description**: 默认排程订单池排除 blocked 订单，异常订单进入需处理视图。
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - `blocked_machine_capability` 不出现在默认可排池。
  - 排程工人可以打开异常视图处理。
  - 每个异常订单有 root cause 和 recommendation。
- **Validation**:
  - API contract test 覆盖 ready/risk/blocked 返回。
  - 浏览器测试覆盖订单池和异常池。

### Task 1.3: Add manual override workflow

- **Location**: workbench/admin UI, audit table, API
- **Description**: 对 risk 或特定 blocked 订单提供有权限的人工豁免，但必须记录原因。
- **Dependencies**: Task 1.2
- **Acceptance Criteria**:
  - `risk`、`candidate`、受限 `blocked_policy` 可豁免。
  - `blocked_data_error`、`blocked_machine_capability`、`blocked_cleanroom` 默认不可豁免进入正式排程。
  - 实验模式豁免不得正式发布。
  - 豁免必须记录操作者、原因、时间、策略版本。
  - 被豁免订单在草案中显示风险标识。
- **Validation**:
  - 权限和审计测试。

## Sprint 2: Publishable Hard Constraints

**Goal**: 发布出来的计划不违反硬规则。

**Demo/Validation**:

- 72h 清场、维护窗口、换产间隔、锁定任务冲突都会阻断发布。
- solver profile 不能关闭硬约束。

### Task 2.1: Define publishable solver contract

- **Location**: `src/scheduler.py`, `src/models.py`, `src/diagnostics.py`
- **Description**: 明确哪些诊断会阻止发布，哪些只是 warning。
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - `OPTIMAL`/`FEASIBLE` 不自动等于 publishable。
  - 结果能表达 `publishable=false` 和阻断原因。
  - 发布接口校验 publishable。
  - 诊断级别固定为 `info`、`warning`、`publish_blocker`、`invalid`。
  - 72h 清场违规、维护跨越、换产间隔缺失、锁定冲突、策略/input stale 默认属于 `publish_blocker` 或 `invalid`。
  - 级别映射到现有 validation summary：`invalid` 和 `publish_blocker` 计入 hard error 或 publish blocker count；`warning` 计入 warning count；`info` 仅展示。
- **Validation**:
  - 单元测试和 API 发布测试。

### Task 2.1B: Map diagnostics to validation and publish API

- **Location**: validation helpers, publish API, workbench UI, tests
- **Description**: 定义 `info/warning/publish_blocker/invalid` 与现有 hard error、warning、publish confirmation 的映射关系。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - `invalid` 一定阻断发布，并标记结果不可用。
  - `publish_blocker` 阻断发布，但允许用户修复后重新验证。
  - `warning` 是否允许发布由 `publish_with_warnings_allowed` 或新策略决定。
  - UI 显示阻断数量和警告数量时不重复计数。
- **Validation**:
  - validation summary、confirm API、workbench publish button 测试一致。

### Task 2.2: Configure and enforce 72h cleaning

- **Location**: `src/scheduler.py`, strategy schema, tests
- **Description**: 将连续运行清场规则从后验诊断升级为可配置硬约束或发布阻断。
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - 连续运行上限、清场时长来自策略。
  - 默认 `enforcement_mode=hard` 或 `publish_blocker`，不可被普通 profile 绕过。
  - `experimental_disabled` 草案默认不可正式发布。
  - 不能满足时给出不可发布诊断。
- **Validation**:
  - 长订单连续运行测试。
  - 清场导致急单延期的诊断测试。

### Task 2.3: Keep post-solve validation as guardrail

- **Location**: `src/scheduler.py`
- **Description**: 后验校验继续保留，但作为安全网。
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - 后验发现硬规则违例时状态变为 `INVALID` 或 `UNPUBLISHABLE`。
  - 诊断包含机台、订单、时间段、修复动作。
- **Validation**:
  - 手工构造非法 `ScheduleResult` 测试。

## Sprint 3: Solver Quality And Observability

**Goal**: 让排程工人知道这次方案是最优、可行但未证明最优，还是受时间限制影响。

**Demo/Validation**:

- 每次求解记录 phase、objective、bound、gap、branches、conflicts、wall time。
- 阶段二不会盲目锁死未证明最优的阶段一延期。

### Task 3.1: Record solver metrics

- **Location**: `src/scheduler.py`, `src/models.py`, `src/output_formatter.py`
- **Description**: 将 CP-SAT 运行指标写入结果、导出和诊断。
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - phase 1 和 phase 2 均有质量指标。
  - UI 显示 `FEASIBLE` 的证明程度。
- **Validation**:
  - 单元测试和手工排程输出检查。

### Task 3.2: Make phase 2 gap-aware

- **Location**: `src/scheduler.py`
- **Description**: 只有 phase 1 为 `OPTIMAL` 时严格锁定延期；`FEASIBLE` 时使用配置化容忍边界。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - 容忍边界来自策略配置。
  - 结果说明延期质量证明程度。
- **Validation**:
  - 短时间限制用例验证。

### Task 3.3: Add configurable solver profiles

- **Location**: strategy schema, `src/scheduler.py`
- **Description**: `fast`、`standard`、`deep` profile 都由配置驱动。
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - profile 只影响求解时间、gap、多种子、日志等求解行为。
  - profile 不允许关闭硬约束。
- **Validation**:
  - 同一订单集对比 profile 输出。

## Sprint 4: Planning Window And Candidate Acceptance

**Goal**: 从“所有可排订单都必须排”升级为“本周期优先，远期订单可配置进入候选”。

**Demo/Validation**:

- 本周期订单必须排或说明不可排。
- 远期订单不会挤占急单。
- 被推迟订单有清晰原因。

### Task 4.1: Define configurable planning buckets

- **Location**: `src/order_screening.py`, strategy schema, workbench API/UI
- **Description**: 按策略将订单分为 must schedule、candidate、deferred、blocked。
- **Dependencies**: Sprint 1
- **Acceptance Criteria**:
  - bucket 依据 due date、material availability、order class、customer class、machine scarcity。
  - 所有阈值来自配置。
  - 草案详情满足 `selected_input_orders = scheduled + deferred + blocked + unplaced_solver_failed`。
  - 各 bucket 语义互斥，前端不自行推断 bucket。
  - 未选择进入草案的订单不计入 deferred 或 blocked。
- **Validation**:
  - 订单桶单元测试。
  - preplan contract test 验证 bucket 不变量。

### Task 4.2: Add optional acceptance for candidate orders

- **Location**: `src/scheduler.py`
- **Description**: 候选订单使用 optional acceptance，本周期必排保持强制分配。
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - 候选订单可以不进入本轮计划。
  - 拒排惩罚来自策略。
  - 输出区分 scheduled 和 deferred。
  - must_schedule 订单永不 optional。
  - candidate 策略支持最低接受率、最大 deferred 数或订单类别拒排惩罚下限，防止模型为了减少换产而大量不排。
- **Validation**:
  - 产能不足场景优先排急单和本周期订单。
  - benchmark 验证 scheduled/deferred 比例不低于策略门槛。

### Task 4.2B: Redefine result validation for optional candidates

- **Location**: `src/scheduler.py`, `src/models.py`, `src/output_formatter.py`, publish API, tests
- **Description**: 引入 candidate optional 后，结果校验不能再简单要求所有输入订单都落位。必须区分 must-schedule expected count、scheduled count、deferred count 和 unplaced solver-failed count。
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - must_schedule 未落位会产生 `publish_blocker` 或 `invalid`。
  - candidate 未落位进入 `deferred_orders`，不导致结果 invalid。
  - 导出和发布统计区分 scheduled、deferred、blocked、unplaced_solver_failed。
- **Validation**:
  - 单元测试覆盖 must_schedule 未排、candidate deferred、solver failed 三种情况。

### Task 4.3: Explain deferred orders

- **Location**: `src/diagnostics.py`, `src/output_formatter.py`, workbench UI
- **Description**: 为未进入本轮计划的订单生成原因。
- **Dependencies**: Task 4.2
- **Acceptance Criteria**:
  - 每个 deferred 订单都有结构化原因。
  - 排程工人可以按原因筛选。
- **Validation**:
  - API/导出测试。

## Sprint 5: Scale, Arc Pruning, And Benchmarking

**Goal**: 让 100-300 单规模下的排程可控、可解释、可调参。

**Demo/Validation**:

- 输出模型规模 telemetry。
- 弧裁剪策略可配置、可关闭、可对比。
- 50/100/200 单压测报告稳定生成。

### Task 5.0: Establish current solver baseline

- **Location**: `tests/`, `examples/`, `scripts/`
- **Description**: 在引入弧裁剪、optional candidate 和新 profile 之前，先用当前模型跑 50/100/200 单基线。
- **Dependencies**: None
- **Acceptance Criteria**:
  - 记录当前 wall time、status、late count、weighted tardiness、setup time、machine load、gap。
  - 后续 pass/fail 阈值基于基线和业务目标设定。
- **Validation**:
  - baseline summary 可重复生成。

### Task 5.1: Add model size telemetry

- **Location**: `src/scheduler.py`
- **Description**: 记录订单数、候选分派数、每台机候选订单数、弧数量、setup cache 大小。
- **Dependencies**: Sprint 0
- **Acceptance Criteria**:
  - 求解前即可看到模型规模。
  - 日志定位变量爆炸来自哪台机。
- **Validation**:
  - telemetry 测试或 smoke run。

### Task 5.2: Introduce configurable business arc pruning

- **Location**: `src/scheduler.py`, strategy schema, `src/setup_matrices.py`
- **Description**: 按换产时间、材料族、洁净等级、交期窗口保留 top-k 弧。
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - 裁剪开关、top-k、阈值均来自配置。
  - 可关闭裁剪做对照。
  - 报告显示裁剪掉的弧数量和策略。
- **Validation**:
  - 对比裁剪前后 objective、late count、setup time、wall time。

### Task 5.3: Add benchmark datasets and reports

- **Location**: `tests/`, `examples/`, `scripts/`
- **Description**: 建立 50/100/200 单压测样例和自动报告。
- **Dependencies**: Task 5.1, Task 5.2
- **Acceptance Criteria**:
  - 每次优化能看到性能是否退化。
  - 报告包含迟交、换产、清场、机台负载、gap。
  - 定义 profile 级别的验收门槛，例如 standard profile 在 100 单内必须在配置时间内返回 `FEASIBLE` 或明确不可行诊断。
  - 弧裁剪启用后，迟交数、加权延期、总换产不得超过配置化劣化阈值，除非报告明确标记为实验结果。
- **Validation**:
  - benchmark 命令生成 summary。
  - benchmark summary 包含 pass/fail 判定。

## Sprint 6: Manual Locking And Local Re-Optimization

**Goal**: 支持排程工人保留已发布或已开工任务，只优化剩余部分。

**Demo/Validation**:

- 锁定任务后重新排程，锁定任务位置不变。
- 急单插入只影响未锁定任务。
- 结果说明哪些任务被移动、哪些被保护。

### Task 6.1: Model locked tasks

- **Location**: `src/models.py`, `src/scheduler.py`, database/API
- **Description**: 增加 locked schedule input，固定 machine、start/end 或占用 interval。
- **Dependencies**: Sprint 2
- **Acceptance Criteria**:
  - 已开工任务不可移动。
  - 已发布未开工任务是否可动由策略决定。
  - 锁定任务参与 NoOverlap、清场、换产。
- **Validation**:
  - 锁定任务不移动测试。

### Task 6.2: Re-optimize remaining tasks

- **Location**: `src/scheduler.py`
- **Description**: 在锁定任务形成的机台时间轴空隙中安排未锁定订单。
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - 不覆盖锁定窗口。
  - 新任务仍满足维护、清场、换产、原料约束。
- **Validation**:
  - 锁定早班任务后重排测试。

### Task 6.3: Show impact analysis

- **Location**: workbench UI, `src/diagnostics.py`
- **Description**: 人工锁单或拖动后，显示延期变化、换产变化、受影响订单。
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - 排程工人能看到调整代价。
  - 管理者能追溯人工调整原因。
- **Validation**:
  - 浏览器测试覆盖锁定、重排、影响提示。

## Testing Strategy

- 订单准入测试：超宽、超厚、层数超限、洁净不匹配、原料晚于交期、字段缺失。
- 策略配置测试：默认策略、修改策略、版本递增、草案策略快照、旧草案 stale。
- 求解器测试：清场、维护、换产间隔、tardiness、candidate acceptance、locked tasks。
- 集成测试：订单导入、筛选、创建草案、求解、诊断、导出、发布。
- 压测：50/100/200 单，记录 wall time、gap、迟交、换产、清场、机台负载。
- 浏览器验收：订单池、异常订单池、策略总览、草案详情、不可发布原因、deferred 订单。

## Potential Risks & Gotchas

- 策略配置过多会让用户困惑。需要提供默认策略、说明文本和变更审计。
- blocked 订单不进排程池，可能被误解为“系统漏单”。UI 必须有异常订单入口和数量提示。
- 人工豁免会绕过治理边界，必须有权限、审计和发布风险提示。
- 如果只保存 policy snapshot 而不保存 input snapshot，旧草案会漏判订单、机台、维护日历变化造成的 stale 风险。
- 弧裁剪可能错过全局最优，必须能关闭并做对照。
- fast profile 可以降低最优性要求，但不能关闭硬约束。
- 72h 清场配置化不代表可以随意关闭。若关闭，应标记为实验或违规风险。

## Rollback Plan

- 所有新增策略先以默认值兼容当前行为。
- 订单池治理先只做提示，再切换为默认拦截。
- 72h 清场保留独立 enforcement mode，不提供普通关闭开关；candidate acceptance、arc pruning、locked tasks 保留独立开关。
- 若新求解策略不稳定，可回退到当前两阶段模型，但保留订单准入、策略快照和诊断。
