# Workbench Stage-Driven Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the confirmed stage-driven `/workbench` layout from `docs/superpowers/specs/2026-05-23-workbench-stage-driven-workspace-design.md`.

**Architecture:** Keep existing scheduling APIs and algorithm behavior unchanged. Add a stage state model on top of the existing workbench, make the Stepper clickable, route the main workspace through a `StageCanvas`, and add a dedicated validate/publish stage while keeping resource view inside draft review.

**Tech Stack:** React 19, Vite, Playwright e2e, existing CSS in `web/src/index.css`, existing API client in `web/src/api/client.js`.

---

## File Structure

- Modify `web/e2e/workbench.spec.js`
  - Add red tests for clickable stages and stage-specific main content.
  - Preserve existing closed-loop tests for search, draft creation, validation, cancellation, publishing, queue actions, and adjustment.

- Modify `web/src/pages/workbenchViewModel.js`
  - Add stage constants and `derivePublishChecklist` as pure helpers.
  - Keep existing draft/version/queue helpers stable.

- Modify `web/src/pages/ScheduleWorkbench.jsx`
  - Add `stageOverride`, `recommendedStage`, and `activeStage`.
  - Make `WorkflowStepper` clickable and able to show recommended vs current view.
  - Add `StageCanvas`, `OrderPoolStage`, `DraftReviewStage`, `ValidatePublishStage`, and `ManufacturingQueueStage` as internal components.
  - Keep existing API handlers and business gates unchanged.

- Modify `web/src/index.css`
  - Add stage header, stage notice, checklist, and validate/publish styles.
  - Keep existing responsive behavior and avoid horizontal overflow.

- Modify `docs/superpowers/specs/2026-05-23-workbench-stage-driven-workspace-design.md`
  - Append implementation evidence only after verification passes.

---

## Task 1: Add Failing E2E Coverage For Stage-Driven Workspace

**Files:**
- Modify: `web/e2e/workbench.spec.js`

- [ ] **Step 1: Update existing selector expectations to the new stage IDs**

In the draft creation test, after `workbench-workflow-stepper` is visible, assert both the new stage button and stage canvas:

```js
    await expect(page.getByTestId('workbench-stage-draft_review')).toHaveAttribute('aria-current', 'step');
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('草案复核');
    await expect(page.getByTestId('workbench-draft-review-stage')).toBeVisible();
```

- [ ] **Step 2: Add stage switching assertions**

In the same test, after the first draft is created, exercise all stage buttons:

```js
    await page.getByTestId('workbench-stage-order_pool').click();
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('订单池');
    await expect(page.getByTestId('workbench-order-pool-stage')).toBeVisible();

    await page.getByTestId('workbench-stage-validate_publish').click();
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('校验发布');
    await expect(page.getByTestId('workbench-validate-publish-stage')).toBeVisible();
    await expect(page.getByTestId('workbench-publish-checklist')).toBeVisible();

    await page.getByTestId('workbench-stage-manufacturing_queue').click();
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('制造队列');
    await expect(page.getByTestId('workbench-manufacturing-queue-stage')).toBeVisible();

    await page.getByTestId('workbench-stage-draft_review').click();
    await expect(page.getByTestId('workbench-draft-review-stage')).toBeVisible();
```

- [ ] **Step 3: Move resource view assertions under draft review**

Replace the global resource tab interaction with draft-stage resource buttons:

```js
    await page.getByTestId('workbench-stage-draft_review').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeHidden();
    await page.getByTestId('workbench-draft-view-resource').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeVisible();
    await page.getByTestId('workbench-draft-view-orders').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeHidden();
```

- [ ] **Step 4: Update publish test for stage-driven queue**

In the publish test, after successful publish, assert the manufacturing stage instead of clicking the old global queue tab:

```js
    await expect(page.getByTestId('workbench-stage-manufacturing_queue')).toHaveAttribute('aria-current', 'step');
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('制造队列');
    await expect(page.getByTestId('workbench-manufacturing-queue-stage')).toBeVisible();
    await expect(page.getByTestId('workbench-queue-panel')).toHaveClass(/expanded/);
    await expect(page.getByTestId('workbench-queue-table')).toBeVisible();
```

- [ ] **Step 5: Run the focused e2e and confirm RED**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js -g "creates, validates, selects, and cancels"
```

Expected: FAIL because `workbench-stage-*`, `workbench-stage-canvas`, and the stage-specific panels do not exist yet.

---

## Task 2: Add Stage View-Model Helpers

**Files:**
- Modify: `web/src/pages/workbenchViewModel.js`

- [ ] **Step 1: Add stage labels**

Append:

```js
export const workbenchStages = [
  { key: 'order_pool', label: '订单池', description: '选择 PENDING 订单' },
  { key: 'draft_review', label: '草案复核', description: '处理阻断、延期和调整' },
  { key: 'validate_publish', label: '校验发布', description: '校验后进入制造队列' },
  { key: 'manufacturing_queue', label: '制造队列', description: '推进开工和完工' },
];

export const workbenchStageLabels = Object.fromEntries(
  workbenchStages.map(stage => [stage.key, stage.label]),
);
```

- [ ] **Step 2: Add publish checklist helper**

Append:

```js
export function derivePublishChecklist({
  activePlan,
  counts,
  validation,
  draftVersionLabel = '尚无草案',
  publishBlockReason = '',
  canConfirm = false,
  queueCount = 0,
}) {
  if (!activePlan) {
    return [
      { key: 'draft', label: '预排程草案', status: 'waiting', detail: '尚未创建草案' },
      { key: 'orders', label: '订单选择', status: 'waiting', detail: '请选择待排订单' },
    ];
  }

  const hardErrors = Number(validation?.hard_error_count || 0);
  const warnings = Number(validation?.warning_count || 0);
  return [
    { key: 'draft', label: '草案生命周期', status: 'ready', detail: activePlan.run?.lifecycle_status || '-' },
    { key: 'snapshot', label: '快照状态', status: publishBlockReason.includes('快照') || publishBlockReason.includes('变化') ? 'blocked' : 'ready', detail: draftVersionLabel },
    { key: 'validation', label: '校验状态', status: hardErrors ? 'blocked' : validation ? 'ready' : 'waiting', detail: validation ? `阻断 ${hardErrors} · 警告 ${warnings}` : '尚未校验' },
    { key: 'scheduled', label: '已排订单', status: counts.scheduled > 0 ? 'ready' : 'blocked', detail: `${counts.scheduled} 单` },
    { key: 'blocked', label: '未排订单', status: counts.blocked > 0 ? 'warning' : 'ready', detail: `${counts.blocked} 单` },
    { key: 'queue', label: '发布后队列', status: canConfirm || queueCount > 0 ? 'ready' : 'waiting', detail: queueCount > 0 ? `${queueCount} 项` : `${counts.scheduled} 单将进入队列` },
  ];
}
```

- [ ] **Step 3: Run lint for helper syntax**

Run:

```powershell
cd web
npm run lint
```

Expected: PASS if helpers are unused but exported cleanly.

---

## Task 3: Implement Stage State And Clickable Stepper

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Import new helpers**

Extend the existing `workbenchViewModel` import:

```js
  derivePublishChecklist,
  workbenchStageLabels,
  workbenchStages,
```

- [ ] **Step 2: Replace `WorkflowStepper` props**

Change `WorkflowStepper({ currentStep })` to:

```jsx
function WorkflowStepper({ activeStage, recommendedStage, onStageChange }) {
```

Use `workbenchStages.map(...)`, render each item as a `button`, and set:

```jsx
className={`workbench-workflow-step ${activeStage === key ? 'active' : ''} ${recommendedStage === key ? 'recommended' : ''}`}
aria-current={activeStage === key ? 'step' : undefined}
data-testid={`workbench-stage-${key}`}
onClick={() => onStageChange(key)}
```

- [ ] **Step 3: Add stage state in `ScheduleWorkbench`**

Near other state declarations:

```jsx
  const [stageOverride, setStageOverride] = useState(null);
```

After `workflowStep`:

```jsx
  const recommendedStage = workflowStep;
  const activeStage = stageOverride || recommendedStage;
```

- [ ] **Step 4: Add stage transition helpers**

Add:

```jsx
  const resetStageOverride = () => setStageOverride(null);

  const selectStage = (stage) => {
    setStageOverride(stage);
    setCancelConfirming(false);
    if (stage === 'order_pool') {
      setOrderPoolCollapsed(false);
      return;
    }
    if (stage === 'draft_review') {
      setWorkspaceView('orders');
      setQueueExpanded(false);
      return;
    }
    if (stage === 'manufacturing_queue') {
      setQueueExpanded(true);
      return;
    }
  };
```

- [ ] **Step 5: Reset stage override on context changes**

Call `resetStageOverride()` after creating, opening, validating, confirming, cancelling, clearing, and loading a new active draft.

- [ ] **Step 6: Render the clickable Stepper**

Replace:

```jsx
<WorkflowStepper currentStep={workflowStep} />
```

with:

```jsx
<WorkflowStepper activeStage={activeStage} recommendedStage={recommendedStage} onStageChange={selectStage} />
```

- [ ] **Step 7: Update primary action routing**

When primary action targets queue, blockers, orders, or validate, set `stageOverride` to the matching stage:

```jsx
setStageOverride('manufacturing_queue');
setStageOverride('draft_review');
setStageOverride('order_pool');
setStageOverride('validate_publish');
```

- [ ] **Step 8: Add CSS for button Stepper**

Add:

```css
.workbench-workflow-step {
  text-align: left;
  cursor: pointer;
}
.workbench-workflow-step.recommended:not(.active) {
  border-color: rgba(96, 165, 250, 0.32);
}
.workbench-workflow-step:focus-visible {
  outline: 2px solid rgba(96, 165, 250, 0.78);
  outline-offset: 2px;
}
```

- [ ] **Step 9: Run the RED e2e again**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js -g "creates, validates, selects, and cancels"
```

Expected: still FAIL because `StageCanvas` and stage panels do not exist yet.

---

## Task 4: Add StageCanvas And Move Existing Main Content

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Wrap main content in `workbench-stage-canvas`**

Inside the existing `plan-board`, replace the global workspace header and conditional `workspaceView` render with a `StageCanvas` block:

```jsx
<div className="workbench-stage-canvas" data-testid="workbench-stage-canvas">
  ...
</div>
```

- [ ] **Step 2: Order pool stage**

When `activeStage === 'order_pool'`, render a stage panel with `data-testid="workbench-order-pool-stage"` containing:

```jsx
<h3>订单池</h3>
<p>选择待排订单后创建预排程草案。创建草案不会改变订单状态。</p>
```

Include the current selected count, current filtered count, screening summary, and create button.

- [ ] **Step 3: Draft review stage**

When `activeStage === 'draft_review'`, render `data-testid="workbench-draft-review-stage"` and move the current order review/resource content inside it. Rename the view buttons test ids to:

```jsx
data-testid="workbench-draft-view-orders"
data-testid="workbench-draft-view-resource"
```

Keep the existing `workbench-view-order-review` and `workbench-view-resource` ids as compatibility aliases only if feasible by wrapping text is not duplicated.

- [ ] **Step 4: Validate publish stage**

When `activeStage === 'validate_publish'`, render `data-testid="workbench-validate-publish-stage"` with:

```jsx
<div className="workbench-publish-checklist" data-testid="workbench-publish-checklist">
  {publishChecklist.map(item => (...))}
</div>
```

Show publish block reason, validation items, and confirm/validate buttons using the existing handlers.

- [ ] **Step 5: Manufacturing queue stage**

When `activeStage === 'manufacturing_queue'`, render `data-testid="workbench-manufacturing-queue-stage"` and move the current queue panel into it.

- [ ] **Step 6: Add stage CSS**

Add stage header, notice, and checklist styles:

```css
.workbench-stage-canvas { display: grid; gap: 0; }
.workbench-stage-head { display: flex; justify-content: space-between; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.workbench-stage-head h3 { margin: 0; color: #fff; font-size: 16px; }
.workbench-stage-head p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; line-height: 1.45; }
.workbench-stage-notice { margin: 12px 16px; padding: 10px 12px; color: #bfdbfe; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.22); border-radius: 8px; font-size: 12px; }
.workbench-publish-checklist { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 12px 16px; }
.workbench-check-item { display: grid; gap: 4px; padding: 10px 12px; background: rgba(15, 23, 42, 0.42); border: 1px solid var(--border); border-radius: 8px; }
```

- [ ] **Step 7: Run focused e2e and fix until GREEN**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js -g "creates, validates, selects, and cancels"
```

Expected: PASS.

---

## Task 5: Stage-Aware Inspector And Publish Checklist Refinement

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Add active stage label to Inspector**

Update Inspector heading:

```jsx
<h3>{workbenchStageLabels[activeStage] || '草案校验与复核'}</h3>
```

- [ ] **Step 2: Add order-pool inspector state**

If `activeStage === 'order_pool'`, show selected pending order count and screening summary before the current draft state card.

- [ ] **Step 3: Add validate-publish inspector state**

If `activeStage === 'validate_publish'`, emphasize validation summary and publish block reason before order-specific review.

- [ ] **Step 4: Add manufacturing queue inspector state**

If `activeStage === 'manufacturing_queue'`, show active queue summary and last queue transition reason when available.

- [ ] **Step 5: Run lint**

Run:

```powershell
cd web
npm run lint
```

Expected: PASS.

---

## Task 6: Full Verification And Commit

**Files:**
- Modify: `docs/superpowers/specs/2026-05-23-workbench-stage-driven-workspace-design.md`
- Commit all files touched by this plan only.

- [ ] **Step 1: Run frontend verification**

Run:

```powershell
cd web
npm run lint
npm run build
npm run e2e -- workbench.spec.js
npm run e2e -- smoke-routes.spec.js
```

Expected:

- lint passes.
- build passes with only existing chunk-size warning if it appears.
- workbench e2e passes.
- smoke routes pass.

- [ ] **Step 2: Run backend contract subset if available**

Run:

```powershell
python -m pytest tests/test_order_flow_sprint1.py tests/test_publish_audit.py tests/test_queue_transitions.py tests/test_policy_settings.py -q
```

Expected: PASS. If backend state has pre-existing failures unrelated to touched files, record exact output.

- [ ] **Step 3: Append implementation evidence**

Append a section to the spec:

```markdown
## 16. 实施验证记录

完成日期：2026-05-23

- `cd web; npm run lint`：填写结果。
- `cd web; npm run build`：填写结果。
- `cd web; npm run e2e -- workbench.spec.js`：填写结果。
- `cd web; npm run e2e -- smoke-routes.spec.js`：填写结果。
- `python -m pytest ... -q`：填写结果。

已落地：
- Stepper 支持点击并切换阶段主内容区。
- 主区按订单池、草案复核、校验发布、制造队列渲染不同内容。
- 资源视图保留在草案复核阶段。
- 制造队列作为第四阶段主内容展示。
- Inspector 根据当前阶段突出对应上下文。
```

- [ ] **Step 4: Commit only plan-related files**

Run:

```powershell
git status --short
git add -- web/e2e/workbench.spec.js web/src/pages/workbenchViewModel.js web/src/pages/ScheduleWorkbench.jsx web/src/index.css docs/superpowers/specs/2026-05-23-workbench-stage-driven-workspace-design.md docs/superpowers/plans/2026-05-23-workbench-stage-driven-workspace.md
git diff --cached --check
git commit -m "feat: implement stage-driven workbench workspace"
```

Expected: commit includes only the stage-driven workbench implementation and evidence docs.

---

## Self-Review

Spec coverage:

- 4 stage-driven main content: Tasks 3 and 4.
- Automatic recommendation plus manual stage switching: Task 3.
- One global primary action: Task 3 keeps existing `derivePrimaryAction`.
- Resource view under draft review: Task 4.
- Validate/publish main stage: Task 4.
- Manufacturing queue as stage: Task 4.
- Stage-aware Inspector: Task 5.
- E2E and responsive verification: Task 1 and Task 6.

Placeholder scan:

- No `TBD`, `TODO`, or unresolved placeholders are intentionally left in this plan.
- Each task names exact files, commands, expected outcomes, and selectors.

Type consistency:

- Stage keys are `order_pool`, `draft_review`, `validate_publish`, `manufacturing_queue`.
- New test ids use `workbench-stage-*`, `workbench-stage-canvas`, `workbench-order-pool-stage`, `workbench-draft-review-stage`, `workbench-validate-publish-stage`, and `workbench-manufacturing-queue-stage`.
