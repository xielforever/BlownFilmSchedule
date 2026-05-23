# Workbench Order Draft Version UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the confirmed workflow-driven `/workbench` redesign from `docs/superpowers/specs/2026-05-23-workbench-order-draft-version-ui-design.md`.

**Architecture:** Keep existing scheduling APIs and business logic unchanged. Add a small view-model helper module for derived UI state, then refactor `ScheduleWorkbench.jsx` into explicit workflow, command-bar, review-workspace, version-drawer, inspector, and queue areas while preserving existing test IDs.

**Tech Stack:** React 19, React Router, Vite, Playwright e2e, existing CSS in `web/src/index.css`, existing API client in `web/src/api/client.js`.

---

## File Structure

- Modify `web/src/pages/ScheduleWorkbench.jsx`
  - Owns the workbench page state, API loading, command handlers, and local component composition.
  - Adds `WorkflowStepper`, `ActiveDraftCommandBar`, `DraftVersionDrawer`, `DraftReviewWorkspace`, and `QueueWorkspacePanel` as internal components first.

- Create `web/src/pages/workbenchViewModel.js`
  - Pure derived-state helpers for `draftVersionState`, `workflowStep`, `primaryAction`, `reviewTabs`, and `queueSummary`.
  - No React imports, so the helpers stay easy to reason about and safe for future unit tests.

- Modify `web/src/index.css`
  - Adds layout styles for the workflow shell, command bar, review focus tab, version drawer, and queue workspace tab.
  - Preserves existing color tokens and workbench visual language.

- Modify `web/e2e/workbench.spec.js`
  - Extends current workbench closed-loop tests with assertions for the new workflow shell, current draft command bar, version drawer, queue tab, and stable inspector.
  - Preserves existing selectors such as `workbench-create-preplan`, `workbench-validate-preplan`, `workbench-confirm-preplan`, `workbench-inspector`, and `workbench-queue-panel`.

- Documentation update after implementation: `docs/superpowers/specs/2026-05-23-workbench-order-draft-version-ui-design.md`
  - Add a short implementation evidence section only after verification passes.

---

## Task 1: Add Failing E2E Coverage For The New Workbench Shell

**Files:**
- Modify: `web/e2e/workbench.spec.js`

- [ ] **Step 1: Add workflow shell assertions to the existing create/validate/cancel test**

Insert these expectations in `test('creates, validates, selects, and cancels a draft safely'...)` immediately after the existing line that waits for `workbench-active-preplan-summary`:

```js
    await expect(page.getByTestId('workbench-workflow-stepper')).toBeVisible();
    await expect(page.getByTestId('workbench-workflow-step-draft_review')).toHaveAttribute('aria-current', 'step');
    await expect(page.getByTestId('workbench-command-bar')).toContainText(`#${runId}`);
    await expect(page.getByTestId('workbench-command-bar')).toContainText('待复核');
    await expect(page.getByTestId('workbench-primary-action')).toContainText('校验方案');
    await expect(page.getByTestId('workbench-order-tab-needs-action')).toBeVisible();
    await expect(page.getByTestId('workbench-version-drawer-toggle')).toBeVisible();
```

- [ ] **Step 2: Add version drawer assertions**

Add this block before cancelling the draft in the same test:

```js
    await page.getByTestId('workbench-version-drawer-toggle').click();
    await expect(page.getByTestId('workbench-version-drawer')).toBeVisible();
    await expect(page.getByTestId('workbench-version-drawer')).toContainText(`#${runId}`);
    await expect(page.getByTestId('workbench-version-filter-active')).toBeVisible();
    await page.getByTestId('workbench-version-drawer-close').click();
    await expect(page.getByTestId('workbench-version-drawer')).toBeHidden();
```

- [ ] **Step 3: Add queue workspace assertions to the publish test**

In `test('publishes a valid draft and exposes the manufacturing queue'...)`, replace the direct expectation that the bottom queue panel is expanded with the workspace-tab flow:

```js
    await expect(page.getByTestId('workbench-primary-action')).toContainText('查看制造队列');
    await page.getByTestId('workbench-view-queue').click();
    await expect(page.getByTestId('workbench-queue-panel')).toHaveClass(/expanded/);
    await expect(page.getByTestId('workbench-queue-table')).toBeVisible();
```

- [ ] **Step 4: Run the target e2e test and confirm it fails for missing UI**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js
```

Expected now: FAIL because `workbench-workflow-stepper`, `workbench-command-bar`, `workbench-order-tab-needs-action`, `workbench-version-drawer-toggle`, and `workbench-view-queue` do not exist yet.

---

## Task 2: Add Pure Workbench View-Model Helpers

**Files:**
- Create: `web/src/pages/workbenchViewModel.js`
- Modify: `web/src/pages/ScheduleWorkbench.jsx`

- [ ] **Step 1: Create `workbenchViewModel.js`**

Create this file:

```js
export const draftVersionLabels = {
  current: '当前策略，订单快照有效',
  policy_stale: '策略已变化，需要重新预排',
  order_stale: '订单已修订，需要重新预排',
  mixed_stale: '策略和订单均已变化',
  cancelled: '草案已废弃',
  confirmed: '已发布为制造队列',
};

export const draftVersionTones = {
  current: 'success',
  policy_stale: 'danger',
  order_stale: 'danger',
  mixed_stale: 'danger',
  cancelled: 'danger',
  confirmed: 'success',
};

export function deriveDraftVersionState(activePlan) {
  const lifecycle = activePlan?.run?.lifecycle_status;
  if (!activePlan) return 'none';
  if (lifecycle === 'CANCELLED') return 'cancelled';
  if (lifecycle === 'CONFIRMED') return 'confirmed';

  const items = activePlan?.validation?.items || [];
  const hasPolicyStale = items.some(item => item.code === 'policy_snapshot_stale');
  const hasOrderStale = items.some(item => item.code === 'order_snapshot_stale');
  if (hasPolicyStale && hasOrderStale) return 'mixed_stale';
  if (hasPolicyStale) return 'policy_stale';
  if (hasOrderStale) return 'order_stale';
  return 'current';
}

export function isDraftStale(versionState) {
  return ['policy_stale', 'order_stale', 'mixed_stale'].includes(versionState);
}

export function deriveWorkflowStep({ activePlan, queue = [], draftVersionState = 'none', hasHardErrors = false }) {
  if (!activePlan) return 'order_pool';
  const lifecycle = activePlan.run?.lifecycle_status;
  if (lifecycle === 'CONFIRMED' || queue.some(item => item.run_id === activePlan.run?.run_id)) return 'manufacturing_queue';
  if (lifecycle === 'VALIDATED' && !isDraftStale(draftVersionState) && !hasHardErrors) return 'validate_publish';
  return 'draft_review';
}

export function derivePrimaryAction({
  activePlan,
  selectedCount = 0,
  canConfirm = false,
  canEditDraft = false,
  hasHardErrors = false,
  publishBlockReason = '',
  reviewValidationPending = false,
  draftVersionState = 'none',
}) {
  if (!activePlan) {
    return {
      key: 'create',
      label: selectedCount ? `创建预排程 (${selectedCount})` : '选择订单后创建',
      disabled: selectedCount === 0,
      target: 'create',
    };
  }

  const lifecycle = activePlan.run?.lifecycle_status;
  if (isDraftStale(draftVersionState)) {
    return { key: 'replan', label: '重新预排', disabled: false, target: 'version' };
  }
  if (lifecycle === 'CONFIRMED') {
    return { key: 'queue', label: '查看制造队列', disabled: false, target: 'queue' };
  }
  if (lifecycle === 'CANCELLED') {
    return { key: 'select_orders', label: '重新选择订单', disabled: false, target: 'orders' };
  }
  if (canConfirm) {
    return { key: 'confirm', label: '确认进入制造队列', disabled: false, target: 'confirm' };
  }
  if (hasHardErrors) {
    return { key: 'blockers', label: '查看阻断', disabled: false, target: 'blockers' };
  }
  if (reviewValidationPending || canEditDraft) {
    return { key: 'validate', label: '校验方案', disabled: !canEditDraft, target: 'validate' };
  }
  return { key: 'blocked', label: publishBlockReason || '当前不可发布', disabled: true, target: 'none' };
}

export function deriveReviewTabs({ counts, hardErrorCount = 0, needsActionCount = 0 }) {
  return [
    { key: 'needs_action', label: '需处理', count: needsActionCount, tone: needsActionCount ? 'danger' : 'neutral' },
    { key: 'blockers', label: '草案阻断', count: hardErrorCount, tone: hardErrorCount ? 'danger' : 'neutral' },
    { key: 'blocked', label: '未排订单', count: counts.blocked, tone: counts.blocked ? 'danger' : 'neutral' },
    { key: 'late', label: '延期订单', count: counts.late, tone: counts.late ? 'warning' : 'neutral' },
    { key: 'schedulable', label: '可排订单', count: counts.schedulable, tone: 'success' },
    { key: 'scheduled', label: '已排订单', count: counts.scheduled, tone: 'success' },
    { key: 'input', label: '输入订单', count: counts.input, tone: 'neutral' },
  ];
}

export function summarizeQueue(queue = [], activeRunId = null) {
  const rows = activeRunId ? queue.filter(item => item.run_id === activeRunId) : queue;
  const counts = rows.reduce((acc, item) => {
    acc[item.queue_status] = (acc[item.queue_status] || 0) + 1;
    return acc;
  }, {});
  return {
    rows,
    total: rows.length,
    counts,
  };
}
```

- [ ] **Step 2: Import the helpers**

Add this import near the top of `ScheduleWorkbench.jsx`:

```js
import {
  deriveDraftVersionState,
  derivePrimaryAction,
  deriveReviewTabs,
  deriveWorkflowStep,
  draftVersionLabels,
  draftVersionTones,
  isDraftStale,
  summarizeQueue,
} from './workbenchViewModel';
```

- [ ] **Step 3: Run lint and confirm helper syntax**

Run:

```powershell
cd web
npm run lint
```

Expected after only import without usage: FAIL for unused imports. This is acceptable at this step because Task 3 consumes the helpers.

---

## Task 3: Implement Workflow Stepper And Current Draft Command Bar

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Add internal UI components above `export default function ScheduleWorkbench()`**

Add these components after `PolicySummary`:

```jsx
function WorkflowStepper({ currentStep }) {
  const steps = [
    ['order_pool', '订单池', '选择 PENDING 订单'],
    ['draft_review', '草案复核', '处理阻断、延期和调整'],
    ['validate_publish', '校验发布', '校验后进入制造队列'],
    ['manufacturing_queue', '制造队列', '推进开工和完工'],
  ];
  return (
    <div className="workbench-workflow-stepper" data-testid="workbench-workflow-stepper">
      {steps.map(([key, title, description], index) => (
        <div
          key={key}
          className={`workbench-workflow-step ${currentStep === key ? 'active' : ''}`}
          aria-current={currentStep === key ? 'step' : undefined}
          data-testid={`workbench-workflow-step-${key}`}
        >
          <span>{index + 1}</span>
          <div>
            <strong>{title}</strong>
            <small>{description}</small>
          </div>
        </div>
      ))}
    </div>
  );
}

function ActiveDraftCommandBar({
  activePlan,
  counts,
  versionState,
  publishBlockReason,
  primaryAction,
  onPrimaryAction,
  onOpenVersions,
  onCancel,
  onRefresh,
}) {
  const lifecycle = activePlan?.run?.lifecycle_status;
  return (
    <section className={`workbench-command-bar ${publishBlockReason ? 'blocked' : ''}`} data-testid="workbench-command-bar">
      <div className="workbench-command-main">
        <span className="workbench-command-eyebrow">当前草案</span>
        <h3>{activePlan ? `#${activePlan.run.run_id} · ${lifecycleLabels[lifecycle] || lifecycle}` : '尚未创建预排程草案'}</h3>
        <p>
          {activePlan
            ? (publishBlockReason || '当前草案可继续复核，发布前以校验结果为准。')
            : '选择待排订单后创建预排程草案。创建草案不会改变订单状态。'}
        </p>
      </div>
      <div className="workbench-command-metrics">
        <Badge tone="neutral">输入 {counts.input}</Badge>
        <Badge tone="success">已排 {counts.scheduled}</Badge>
        <Badge tone="success">可排 {counts.schedulable}</Badge>
        <Badge tone={counts.blocked ? 'danger' : 'neutral'}>未排 {counts.blocked}</Badge>
        <Badge tone={counts.late ? 'warning' : 'neutral'}>延期 {counts.late}</Badge>
        {activePlan && <Badge tone={draftVersionTones[versionState] || 'neutral'}>{draftVersionLabels[versionState] || '尚无草案'}</Badge>}
      </div>
      <div className="workbench-command-actions">
        <button
          type="button"
          className="btn btn-primary"
          data-testid="workbench-primary-action"
          disabled={primaryAction.disabled}
          onClick={onPrimaryAction}
        >
          {primaryAction.label}
        </button>
        <button type="button" className="btn btn-ghost btn-small" data-testid="workbench-version-drawer-toggle" onClick={onOpenVersions}>
          草案版本
        </button>
        {activePlan && ['DRAFT', 'VALIDATED'].includes(lifecycle) && (
          <button type="button" className="btn btn-danger btn-small" onClick={onCancel}>
            废弃草案
          </button>
        )}
        <button type="button" className="btn btn-ghost btn-small" onClick={onRefresh}>
          刷新
        </button>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Add derived state inside `ScheduleWorkbench`**

After `publishBlockReason`, add:

```jsx
  const draftVersionState = useMemo(
    () => deriveDraftVersionState(activePlan),
    [activePlan],
  );
  const activeQueueSummary = useMemo(
    () => summarizeQueue(queue, activePlan?.run?.run_id || null),
    [activePlan, queue],
  );
  const workflowStep = useMemo(
    () => deriveWorkflowStep({
      activePlan,
      queue: activeQueueSummary.rows,
      draftVersionState,
      hasHardErrors,
    }),
    [activePlan, activeQueueSummary.rows, draftVersionState, hasHardErrors],
  );
  const primaryAction = useMemo(
    () => derivePrimaryAction({
      activePlan,
      selectedCount: selected.length,
      canConfirm,
      canEditDraft,
      hasHardErrors,
      publishBlockReason,
      reviewValidationPending,
      draftVersionState,
    }),
    [activePlan, canConfirm, canEditDraft, draftVersionState, hasHardErrors, publishBlockReason, reviewValidationPending, selected.length],
  );
```

- [ ] **Step 3: Add the primary action handler**

Add this function near `selectWorkspaceView`:

```jsx
  const runPrimaryAction = () => {
    if (primaryAction.target === 'create') return handleCreatePreplan();
    if (primaryAction.target === 'validate') return handleValidate();
    if (primaryAction.target === 'confirm') return handleConfirm();
    if (primaryAction.target === 'queue') {
      setWorkspaceView('queue');
      setQueueExpanded(true);
      return null;
    }
    if (primaryAction.target === 'blockers') {
      setWorkspaceView('orders');
      setPlanOrderTab('needs_action');
      return null;
    }
    if (primaryAction.target === 'version') {
      setVersionDrawerOpen(true);
      return null;
    }
    if (primaryAction.target === 'orders') {
      setOrderPoolCollapsed(false);
      return null;
    }
    return null;
  };
```

- [ ] **Step 4: Render the new shell**

In JSX, render the stepper and command bar after `PolicySummary settings={settings}`:

```jsx
      <WorkflowStepper currentStep={workflowStep} />
      <ActiveDraftCommandBar
        activePlan={activePlan}
        counts={activePlan ? planOrderCounts : { input: selected.length, scheduled: 0, schedulable: 0, blocked: 0, late: 0 }}
        versionState={draftVersionState}
        publishBlockReason={publishBlockReason}
        primaryAction={primaryAction}
        onPrimaryAction={runPrimaryAction}
        onOpenVersions={() => setVersionDrawerOpen(true)}
        onCancel={openCancelConfirm}
        onRefresh={() => loadAll(Boolean(activePlan))}
      />
```

- [ ] **Step 5: Add CSS for the workflow shell**

Append to the Schedule Workbench section in `web/src/index.css`:

```css
.workbench-workflow-stepper {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.workbench-workflow-step {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 58px;
  padding: 10px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
}
.workbench-workflow-step > span {
  display: inline-grid;
  place-items: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.15);
  color: #bfdbfe;
  font-weight: 900;
}
.workbench-workflow-step strong,
.workbench-workflow-step small {
  display: block;
}
.workbench-workflow-step strong {
  color: #fff;
  font-size: 13px;
}
.workbench-workflow-step small {
  margin-top: 3px;
  font-size: 11px;
}
.workbench-workflow-step.active {
  border-color: rgba(59, 130, 246, 0.55);
  background: rgba(59, 130, 246, 0.14);
}
.workbench-command-bar {
  display: grid;
  grid-template-columns: minmax(240px, 0.9fr) minmax(0, 1.2fr) auto;
  gap: 14px;
  align-items: center;
  padding: 14px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
}
.workbench-command-bar.blocked {
  border-color: rgba(245, 158, 11, 0.34);
  background: rgba(245, 158, 11, 0.08);
}
.workbench-command-eyebrow {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 900;
}
.workbench-command-main h3 {
  margin: 3px 0 4px;
  color: #fff;
  font-size: 17px;
}
.workbench-command-main p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}
.workbench-command-metrics,
.workbench-command-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.workbench-command-actions {
  justify-content: flex-end;
}
```

- [ ] **Step 6: Run lint**

Run:

```powershell
cd web
npm run lint
```

Expected: PASS, or only fail for issues introduced by exact naming mismatches. Fix naming mismatches before proceeding.

---

## Task 4: Add The `需处理` Review Focus

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/e2e/workbench.spec.js`

- [ ] **Step 1: Add the new tab test id**

Update `planOrderTabTestIds`:

```js
const planOrderTabTestIds = {
  needs_action: 'workbench-order-tab-needs-action',
  input: 'workbench-order-tab-input',
  schedulable: 'workbench-order-tab-schedulable',
  scheduled: 'workbench-order-tab-scheduled',
  blocked: 'workbench-order-tab-blocked',
  late: 'workbench-order-tab-late',
  blockers: 'workbench-order-tab-blockers',
};
```

- [ ] **Step 2: Update preferred tab selection**

Replace `preferredPlanOrderTab` with:

```js
function preferredPlanOrderTab(detail) {
  const counts = planDetailCounts(detail);
  if (counts.hardErrors > 0 || counts.blocked > 0 || counts.late > 0) return 'needs_action';
  return 'scheduled';
}
```

- [ ] **Step 3: Add `needs_action` rows**

Inside the `planOrderRows` `useMemo`, add `needsAction` before the return:

```jsx
    const needsActionMap = new Map();
    [...hardValidationItems.map((item, index) => buildRow(item.order_id, {
      validationItem: item,
      bucket: 'blockers',
      key: `${item.code}-${item.order_id}-${index}`,
    })), ...blocked, ...late].forEach(row => {
      if (row?.order_id && !needsActionMap.has(row.order_id)) needsActionMap.set(row.order_id, row);
    });
    const needs_action = [...needsActionMap.values()].sort((a, b) => orderSortKey(a).localeCompare(orderSortKey(b)));
```

Then include it in the returned object:

```jsx
      needs_action,
```

- [ ] **Step 4: Replace `planOrderTabs` construction**

Replace the current `planOrderTabs` `useMemo` with:

```jsx
  const needsActionCount = planOrderRows.needs_action?.length || 0;
  const planOrderTabs = useMemo(
    () => deriveReviewTabs({
      counts: planOrderCounts,
      hardErrorCount: hardValidationItems.length,
      needsActionCount,
    }),
    [hardValidationItems.length, needsActionCount, planOrderCounts],
  );
```

- [ ] **Step 5: Update the table status text for stale rows**

In `buildRow`, ensure validation-driven rows show a direct risk string:

```js
risk: override.validationItem?.message || source?.root_cause || source?.bucket_reason || source?.risk || '-',
```

- [ ] **Step 6: Run the workbench e2e test**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js
```

Expected: The earlier missing `workbench-order-tab-needs-action` failure is resolved. Any remaining failures should point to version drawer or queue tab work that is handled in later tasks.

---

## Task 5: Implement Draft Version Drawer

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Add drawer state**

Inside `ScheduleWorkbench`, add:

```jsx
  const [versionDrawerOpen, setVersionDrawerOpen] = useState(false);
  const [versionFilter, setVersionFilter] = useState('active');
```

- [ ] **Step 2: Add the drawer component**

Add this internal component above `ScheduleWorkbench`:

```jsx
function DraftVersionDrawer({ open, filter, onFilterChange, activePlan, preplans, onOpenPlan, onClose }) {
  const filters = [
    ['active', '有效草案'],
    ['all', '全部'],
    ['DRAFT', '待复核'],
    ['VALIDATED', '已校验'],
    ['CONFIRMED', '已发布'],
    ['CANCELLED', '已废弃'],
  ];
  const rows = preplans.filter(plan => {
    if (filter === 'all') return true;
    if (filter === 'active') return ['DRAFT', 'VALIDATED'].includes(plan.lifecycle_status);
    return plan.lifecycle_status === filter;
  });
  return (
    <aside className={`workbench-version-drawer ${open ? 'open' : ''}`} data-testid="workbench-version-drawer" hidden={!open}>
      <div className="workbench-version-head">
        <div>
          <h3>草案版本</h3>
          <span>{rows.length} 个版本</span>
        </div>
        <button type="button" className="btn btn-ghost btn-small" data-testid="workbench-version-drawer-close" onClick={onClose}>
          关闭
        </button>
      </div>
      <div className="workbench-version-filters">
        {filters.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={filter === value ? 'active' : ''}
            data-testid={`workbench-version-filter-${String(value).toLowerCase()}`}
            onClick={() => onFilterChange(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="workbench-version-list">
        {rows.map(plan => {
          const counts = planCounts(plan);
          const isActive = activePlan?.run?.run_id === plan.run_id;
          return (
            <button
              key={plan.run_id}
              type="button"
              className={isActive ? 'active' : ''}
              data-testid={`workbench-version-run-${plan.run_id}`}
              onClick={() => onOpenPlan(plan.run_id)}
            >
              <strong>#{plan.run_id} · {lifecycleLabels[plan.lifecycle_status] || plan.lifecycle_status}</strong>
              <span>输入 {counts.input} · 已排 {counts.scheduled} · 未排 {counts.blocked}</span>
              {plan.cancel_reason && <small>废弃原因：{plan.cancel_reason}</small>}
            </button>
          );
        })}
        {!rows.length && <div className="config-empty">当前筛选下没有草案版本。</div>}
      </div>
    </aside>
  );
}
```

- [ ] **Step 3: Render the drawer**

Render this just inside the root `.workbench-page` after `ActiveDraftCommandBar`:

```jsx
      <DraftVersionDrawer
        open={versionDrawerOpen}
        filter={versionFilter}
        onFilterChange={setVersionFilter}
        activePlan={activePlan}
        preplans={preplans}
        onOpenPlan={openPlan}
        onClose={() => setVersionDrawerOpen(false)}
      />
```

- [ ] **Step 4: Remove the always-visible history strip from the main board**

Delete the `<div className="workbench-plan-history">...</div>` block. Keep `visiblePreplans` if another piece still uses it; otherwise delete the `visiblePreplans` `useMemo` after lint confirms it is unused.

- [ ] **Step 5: Add CSS**

Append:

```css
.workbench-version-drawer {
  display: grid;
  gap: 0;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.workbench-version-drawer[hidden] {
  display: none;
}
.workbench-version-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.workbench-version-head h3 {
  margin: 0;
  color: #fff;
  font-size: 15px;
}
.workbench-version-head span {
  color: var(--text-secondary);
  font-size: 12px;
}
.workbench-version-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}
.workbench-version-filters button,
.workbench-version-list button {
  color: var(--text-secondary);
  background: rgba(15, 23, 42, 0.42);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
}
.workbench-version-filters button {
  min-height: 30px;
  padding: 6px 10px;
  font-size: 12px;
  font-weight: 800;
}
.workbench-version-filters button.active,
.workbench-version-list button.active {
  color: #fff;
  border-color: rgba(59, 130, 246, 0.55);
  background: rgba(59, 130, 246, 0.16);
}
.workbench-version-list {
  display: grid;
  gap: 8px;
  max-height: 280px;
  overflow: auto;
  padding: 12px 16px;
}
.workbench-version-list button {
  display: grid;
  gap: 4px;
  padding: 10px;
  text-align: left;
}
.workbench-version-list strong {
  color: #fff;
}
.workbench-version-list span,
.workbench-version-list small {
  font-size: 12px;
}
.workbench-version-list small {
  color: #fecaca;
}
```

- [ ] **Step 6: Run lint and e2e**

Run:

```powershell
cd web
npm run lint
npm run e2e -- workbench.spec.js
```

Expected: version drawer assertions pass. If `visiblePreplans` is unused, remove it.

---

## Task 6: Move Manufacturing Queue Into The Main Workspace Tab

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`
- Modify: `web/e2e/workbench.spec.js`

- [ ] **Step 1: Add the queue tab button**

In `.workbench-view-tabs`, add:

```jsx
                  <button type="button" className={workspaceView === 'queue' ? 'active' : ''} data-testid="workbench-view-queue" onClick={() => selectWorkspaceView('queue')}>
                    制造队列
                  </button>
```

- [ ] **Step 2: Update workspace heading text**

Replace the current heading expression with:

```jsx
                <span>
                  {workspaceView === 'orders' && `当前分类：${activePlanOrderTab.label}`}
                  {workspaceView === 'resource' && '按吹膜机查看已落位任务'}
                  {workspaceView === 'queue' && `当前草案队列：${activeQueueSummary.total} 项`}
                </span>
```

- [ ] **Step 3: Convert the queue section into an internal render block**

Move the existing `<section className={...queue-panel...}>...</section>` from the bottom of the page into the active-plan workspace branch. Keep the root element and `data-testid="workbench-queue-panel"` unchanged.

The workspace branch should become:

```jsx
              {workspaceView === 'orders' && (
                <div className="workbench-order-review">
                  ...
                </div>
              )}
              {workspaceView === 'resource' && (
                <div className="workbench-machines" data-testid="workbench-resource-view">
                  ...
                </div>
              )}
              {workspaceView === 'queue' && (
                <section className={`workbench-panel queue-panel ${queueExpanded ? 'expanded' : 'collapsed'}`} data-testid="workbench-queue-panel">
                  ...
                </section>
              )}
```

- [ ] **Step 4: Scope queue rows to the active run**

Inside the queue table, use `activeQueueSummary.rows.slice(0, 20).map(...)` instead of `queue.slice(0, 20).map(...)`.

Update the empty state:

```jsx
            {!activeQueueSummary.rows.length && <div className="config-empty">当前草案尚未进入制造队列。</div>}
```

- [ ] **Step 5: Auto-expand queue on successful publish**

Keep existing `setQueueExpanded(true)` in `handleConfirm`, and add:

```jsx
      setWorkspaceView('queue');
```

after the queue refresh in `handleConfirm`.

- [ ] **Step 6: Run e2e**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js
```

Expected: publish test opens the queue tab and queue row actions still work.

---

## Task 7: Refine Inspector To Show Draft State First

**Files:**
- Modify: `web/src/pages/ScheduleWorkbench.jsx`
- Modify: `web/src/index.css`

- [ ] **Step 1: Add a draft status card at the top of Inspector**

Inside `<aside className="workbench-panel review-panel"...>`, immediately after the panel head, add:

```jsx
          <div className="selected-order-review" data-testid="workbench-draft-state-card">
            <h4>当前草案状态</h4>
            {activePlan ? (
              <div className="selected-order-card">
                <div>
                  <strong>#{activePlan.run.run_id}</strong>
                  <Badge tone={publishBlockReason ? 'warning' : 'success'}>
                    {publishBlockReason ? '发布受阻' : lifecycleLabels[activePlan.run.lifecycle_status] || activePlan.run.lifecycle_status}
                  </Badge>
                </div>
                <span>{draftVersionLabels[draftVersionState] || '尚无版本状态'}</span>
                <small>{publishBlockReason || '发布前仍以最近一次校验结果为准。'}</small>
              </div>
            ) : (
              <div className="config-empty">选择订单并创建草案后显示复核状态。</div>
            )}
          </div>
```

- [ ] **Step 2: Make selected-order guidance more action-oriented**

Where `selectedOrderGuidance` is rendered, ensure the card labels it as guidance:

```jsx
                {selectedOrderGuidance && (
                  <div className="blocked-item">
                    <strong>处理建议：{selectedDiagnostic?.display_title || selectedDiagnostic?.entity_id || selectedPlanOrderId}</strong>
                    <span>{selectedOrderGuidance}</span>
                    {diagnosticEvidence(selectedDiagnostic) && <small>{diagnosticEvidence(selectedDiagnostic)}</small>}
                  </div>
                )}
```

- [ ] **Step 3: Add adjustment revalidation note**

In the adjustment form, after the reason textarea, add:

```jsx
              <div className="workbench-context-note">
                人工调整提交后，草案需要重新校验后才能发布。
              </div>
```

- [ ] **Step 4: Run focused e2e**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js -g "creates, validates, selects, and cancels"
```

Expected: PASS and Inspector contains `当前草案状态`.

---

## Task 8: Finish Responsive Layout And Text Fit

**Files:**
- Modify: `web/src/index.css`

- [ ] **Step 1: Add responsive rules**

Append:

```css
@media (max-width: 1280px) {
  .workbench-command-bar {
    grid-template-columns: 1fr;
  }
  .workbench-command-actions {
    justify-content: flex-start;
  }
  .workbench-grid.order-pool-collapsed {
    grid-template-columns: minmax(66px, 78px) minmax(0, 1.55fr) minmax(280px, 0.86fr);
  }
  .workbench-workflow-stepper {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1024px) {
  .workbench-workflow-stepper,
  .workbench-grid,
  .workbench-grid.order-pool-collapsed {
    grid-template-columns: 1fr;
  }
  .review-panel {
    position: static;
    max-height: none;
  }
  .order-pool.collapsed .workbench-panel-head,
  .order-pool.collapsed .workbench-order-pool-rail {
    justify-items: start;
    text-align: left;
  }
  .order-pool.collapsed .workbench-order-pool-rail span {
    writing-mode: horizontal-tb;
  }
}
```

- [ ] **Step 2: Confirm root-cause text wraps**

Ensure `.plan-col-risk` keeps:

```css
word-break: break-word;
overflow-wrap: anywhere;
white-space: normal;
```

- [ ] **Step 3: Run browser-sized Playwright checks**

Run:

```powershell
cd web
npm run e2e -- workbench.spec.js
```

Then manually inspect or automate screenshots at:

- `1440x900`
- `1280x720`
- `1024x768`

Expected: Inspector is beside the main workspace at desktop widths and below the main workspace at `1024px` without overlapping text.

---

## Task 9: Full Verification And Evidence Update

**Files:**
- Modify: `docs/superpowers/specs/2026-05-23-workbench-order-draft-version-ui-design.md`

- [ ] **Step 1: Run backend tests that protect the workbench data contract**

Run:

```powershell
python -m pytest tests/test_order_flow_sprint1.py tests/test_order_screening.py tests/test_order_import_flow.py tests/test_publish_audit.py tests/test_queue_transitions.py tests/test_rule_enablement.py tests/test_policy_settings.py tests/test_setup_time.py -q
```

Expected: PASS. If a listed file is absent in a clean checkout, run the subset that exists and record the exact skipped file.

- [ ] **Step 2: Run frontend build and e2e**

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
- build passes with only the existing chunk-size warning if it appears.
- workbench e2e passes.
- smoke routes pass.

- [ ] **Step 3: Add implementation evidence to the design doc**

Append this section to `docs/superpowers/specs/2026-05-23-workbench-order-draft-version-ui-design.md` with the actual command results:

```markdown
## 14. 实施验证记录

完成日期：2026-05-23

- `python -m pytest ... -q`：填写实际通过数量。
- `cd web; npm run lint`：通过。
- `cd web; npm run build`：通过，若存在 chunk-size warning 则注明为既有告警。
- `cd web; npm run e2e -- workbench.spec.js`：通过。
- `cd web; npm run e2e -- smoke-routes.spec.js`：通过。

已验证 UI：

- 顶部流程 Stepper 可见，并随草案状态切换当前步骤。
- 当前草案控制条展示草案编号、生命周期、发布状态、版本状态和主操作。
- 订单池创建前展开，创建后折叠为抽屉。
- 主工作区默认聚焦需处理订单。
- 草案版本通过抽屉查看，不再常驻挤压主区。
- 制造队列在主工作区 Tab 内展示和推进。
- Inspector 固定展示当前草案状态、当前订单根因、换产说明、人工调整入口和审计摘要。
```

- [ ] **Step 4: Commit only the implementation files**

Run:

```powershell
git status --short
git add -- web/src/pages/ScheduleWorkbench.jsx web/src/pages/workbenchViewModel.js web/src/index.css web/e2e/workbench.spec.js docs/superpowers/specs/2026-05-23-workbench-order-draft-version-ui-design.md
git commit -m "feat: redesign schedule workbench flow"
```

Expected: commit includes only the workbench UI implementation, helper, test, and evidence doc. Do not stage `.superpowers/`, output files, or unrelated backend changes unless the user explicitly asks.

---

## Self-Review

Spec coverage:

- Workflow Stepper: Task 3.
- Current draft command bar: Task 3.
- Order pool drawer behavior: preserved from current implementation, validated in Task 1 and Task 8.
- Main workspace review focus: Task 4.
- Resource view as secondary tab: already present, protected in Task 6 and existing e2e.
- Manufacturing queue as workspace Tab: Task 6.
- Fixed Inspector with draft state first: Task 7.
- Draft version drawer: Task 5.
- Derived state objects: Task 2.
- P0/P1/P2 verification: Task 9.

Placeholder scan:

- The plan has no unfinished marker text or unspecified placeholder steps.
- Every task names exact files, commands, expected results, and concrete code snippets for the main changes.

Type and selector consistency:

- New selectors: `workbench-workflow-stepper`, `workbench-workflow-step-draft_review`, `workbench-command-bar`, `workbench-primary-action`, `workbench-order-tab-needs-action`, `workbench-version-drawer-toggle`, `workbench-version-drawer`, `workbench-version-filter-active`, `workbench-version-drawer-close`, `workbench-view-queue`, `workbench-draft-state-card`.
- Existing selectors preserved: `workbench-main-workspace`, `workbench-active-preplan-summary`, `workbench-order-pool-toggle`, `workbench-create-preplan`, `workbench-validate-preplan`, `workbench-confirm-preplan`, `workbench-cancel-preplan`, `workbench-resource-view`, `workbench-queue-panel`, `workbench-queue-table`, `workbench-inspector`.
