# Plan: Workbench P1/P2 TODO and Closed-Loop Validation

**Generated**: 2026-05-21
**Estimated Complexity**: Medium

## Overview

This plan closes the current scheduling workbench gaps around preplan review, cancellation safety, settings feedback, and browser-test coverage. The target workflow remains:

1. Pending orders are selected in the workbench.
2. The backend creates an automatic preplan draft.
3. The planner reviews schedulable, scheduled, blocked, late, and validation-blocked orders.
4. The planner may manually adjust tasks with audit records.
5. The draft can be cancelled with an explicit reason or confirmed into the manufacturing queue.

The key implementation principle is that the UI must not infer business categories that the backend has not returned. The backend should return order-level buckets, and the frontend should render those buckets directly.

The layout redesign is also part of this plan. The workbench should move from a dense three-column page into a primary work area with a fixed review inspector, so order-level review, root cause analysis, adjustment, and audit remain visible in the same workflow.

## Progress Update - 2026-05-22

- Completed Task 1.1, Task 1.2, and Task 2.1.
- `GET /api/schedule/preplans/{run_id}` now returns backend-owned order buckets: `input_orders`, `scheduled_orders`, `schedulable_orders`, `unplaced_schedulable_orders`, `blocked_orders`, and `late_orders`.
- `/workbench` now renders `可排订单` from `activePlan.schedulable_orders`; it no longer aliases the scheduled task list. `可排未落位` is displayed when `unplaced_schedulable_orders` contains rows.
- Current draft #20 verification shows `input=232`, `scheduled=105`, `schedulable=105`, `unplaced=0`, `blocked=127`, and `late=55`. In this data set, `可排订单` and `已排订单` match because all schedulable orders are already placed.
- Validation completed with `python -m py_compile api\routers\schedule.py`, `python -m unittest tests.test_preplan_order_buckets tests.test_scheduler_validation tests.test_dashboard_summary`, `npm run lint`, `npm run build`, API contract smoke, and Playwright CLI DOM smoke for `/workbench`.

## Progress Update - 2026-05-22 Continued

- Completed Task 2.2 and Task 2.3.
- `废弃草案` now opens an inline second-confirmation panel instead of cancelling immediately.
- The confirmation panel shows draft id, scheduled count, blocked count, and the fact that no manufacturing queue will be created.
- Users can enter an optional cancellation reason; blank reasons fall back to `人工废弃草案`.
- After cancellation, the selected draft remains open as `已废弃`; confirmation, cancellation, and adjustment actions are disabled through the existing lifecycle guard.
- Cancelled draft history chips and active draft details now show `cancel_reason`, `cancelled_by`, and `cancelled_at` where available.
- Validation completed with `npm run lint`, `npm run build`, and Playwright CLI smoke using temporary draft #23. The API returned `lifecycle_status=CANCELLED` and `cancel_reason=UI二次确认验证`.

## Prerequisites

- Backend server can run on `http://localhost:8000`.
- Frontend Vite server can run on `http://localhost:3000`.
- PostgreSQL test/demo database is available with pending orders, machines, rules, maintenance windows, and auth user `admin`.
- Existing generated files under `output/` should not be included in this work unless explicitly regenerated as part of a verified scheduling run.

## Sprint 1: Backend Preplan Order Buckets

**Goal**: Make `GET /api/schedule/preplans/{run_id}` return authoritative order buckets so the frontend can distinguish scheduled orders from schedulable-but-unplaced orders.

**Demo/Validation**:
- Create or open a partial draft.
- Response contains `input_orders`, `scheduled_orders`, `schedulable_orders`, `unplaced_schedulable_orders`, `blocked_orders`, and `late_orders`.
- `schedulable_orders` is not just a copy of `tasks`; `unplaced_schedulable_orders` is explicitly derived and explainable.

### Task 1.1: Define Preplan Order Bucket Contract

- **Location**: `api/routers/schedule.py`
- **Description**: Extend the preplan detail response returned by `get_preplan()` with normalized order buckets.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Existing fields `run`, `tasks`, `validation`, `adjustments`, `diagnostics`, and `blocked_orders` remain backwards compatible.
  - New fields use stable snake_case keys:
    - `input_orders`: all selected orders in the draft input.
    - `scheduled_orders`: orders with scheduled tasks in the draft.
    - `schedulable_orders`: orders that pass hard machine capability eligibility.
    - `unplaced_schedulable_orders`: orders eligible for at least one machine but absent from draft tasks.
    - `blocked_orders`: orders with hard eligibility diagnostics.
    - `late_orders`: scheduled orders whose task is late.
  - Each order row includes at least `order_id`, `product_type`, `target_width`, `target_thickness`, `total_quantity_kg`, `order_class`, `cleanroom_req`, `due_date`, `status`, `bucket_reason`, and, where relevant, `eligible_machine_count`.
- **Validation**:
  - Unit/API helper test asserts that `input = scheduled + unplaced_schedulable + blocked` when bucket definitions are mutually exclusive.
  - Existing dashboard summary tests continue to pass.

### Task 1.2: Persist or Reconstruct Schedulable-but-Unplaced Orders

- **Location**: `api/routers/schedule.py`, optionally `src/scheduler.py`
- **Description**: Decide the source of truth for “eligible but not placed.”
- **Recommended Approach**:
  - Short-term: reconstruct in `get_preplan()` from selected input orders, machine capability checks, `scheduled_tasks`, and persisted diagnostics.
  - Later: persist explicit solver-level rejected/omitted order details if the solver supports optional scheduling decisions.
- **Acceptance Criteria**:
  - If all hard-eligible orders are scheduled, `unplaced_schedulable_orders` is an empty list.
  - If a future solver result has eligible orders not placed, those orders appear with a reason such as `solver_not_selected`, `capacity_window_insufficient`, or `manual_removed`.
  - If current algorithm always schedules all eligible orders, the API should still return an empty list explicitly rather than making the frontend guess.
- **Validation**:
  - Add a focused backend test with a synthetic bucket fixture or mocked DB rows.
  - Verify the current #20-like partial draft reports blocked orders and zero unplaced schedulable orders if that matches the data.

### Task 1.3: Add Contract Tests for Preplan Detail

- **Location**: `tests/test_api.py` or a new `tests/test_preplan_contract.py`
- **Description**: Add HTTP contract coverage gated by `APS_RUN_HTTP_TESTS=1`.
- **Dependencies**: Task 1.1.
- **Acceptance Criteria**:
  - Test logs in, creates a preplan from a small pending-order set, fetches detail, and asserts new bucket keys exist.
  - Test asserts `schedulable_orders` is an array of order rows, not a derived count only.
  - Test asserts `blocked_orders` rows include actionable root cause text when diagnostics exist.
- **Validation**:
  - `python -m pytest tests/test_preplan_contract.py`
  - `APS_RUN_HTTP_TESTS=1 python -m pytest tests/test_api.py`

## Sprint 2: Frontend Order Buckets and Cancellation Safety

**Goal**: Make the workbench render backend order buckets directly and make draft cancellation deliberate and auditable.

**Demo/Validation**:
- In `/workbench`, `可排订单` no longer duplicates `已排订单`.
- `废弃草案` requires second confirmation and allows an optional reason.
- Cancellation reason appears in preplan history/detail after reload.

### Task 2.1: Stop Reusing Scheduled Rows for the Schedulable Tab

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`
- **Description**: Replace the current `schedulable: scheduled` mapping with backend-returned `activePlan.schedulable_orders`, and render `unplaced_schedulable_orders` separately when present.
- **Dependencies**: Sprint 1 response contract.
- **Acceptance Criteria**:
  - `可排订单` shows all hard-eligible input orders.
  - `已排订单` shows only orders with tasks.
  - If an order is hard-eligible but not placed, it is marked as `可排未落位`, with `bucket_reason`.
  - `未排订单` remains hard-ineligible or solver-blocked orders with root cause.
  - Empty states explain whether the bucket is truly empty or the backend does not support the field.
- **Validation**:
  - Browser check: switch between `可排订单` and `已排订单`; counts and row identities are allowed to match only when all schedulable orders are scheduled, not because the frontend reused the same array.
  - Add automated UI assertion around visible row counts and text.

### Task 2.2: Add Cancel Draft Confirmation State

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/src/index.css`
- **Description**: Add a local cancel confirmation state and optional reason input before calling `cancelPreplan()`.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - First click on `废弃草案` opens an inline confirmation area or compact modal.
  - Confirmation shows draft id, scheduled count, blocked count, and warning that manufacturing queue will not be created.
  - Optional reason defaults to empty or a clear default, but user can edit it.
  - `确认废弃` sends `{ reason }` to backend.
  - `取消` exits confirmation without API call.
- **Validation**:
  - Browser check: first click does not cancel the draft.
  - Browser check: second confirm cancels the draft and history shows `已废弃`.
  - HTTP check: `cancel_reason` is returned by `GET /api/schedule/preplans/{run_id}`.

### Task 2.3: Preserve Cancellation Reason in History UI

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`
- **Description**: Surface `cancel_reason`, `cancelled_by`, and `cancelled_at` in the active plan header or history detail when the selected draft is cancelled.
- **Dependencies**: Task 2.2.
- **Acceptance Criteria**:
  - Cancelled drafts are not visually indistinguishable from normal history rows.
  - The reason is visible after refresh.
  - Cancelled history rows cannot be confirmed or adjusted.
- **Validation**:
  - Browser check after reload.
  - Confirm and adjust buttons remain disabled for cancelled draft.

## Sprint 3: Workbench Layout Redesign

**Goal**: Rebuild `/workbench` around a primary order-review workspace plus a fixed right-side inspector. The page should prioritize unresolved scheduling decisions: blocked, late, and validation-failed orders.

**Demo/Validation**:
- At desktop width, selecting an order in the main table immediately updates the inspector without requiring page scroll.
- The order pool is prominent before draft creation and collapsible after a draft is active.
- Resource view is a secondary tab beside order review, not a long section below it.
- Manufacturing queue is collapsed by default and expands only when relevant.

### Task 3.1: Convert Workbench Shell to Main Workspace plus Inspector

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/src/index.css`
- **Description**: Replace the current three-column layout with a layout composed of a collapsible order drawer, central workspace, and sticky inspector.
- **Dependencies**: Sprint 2 can be done in parallel, but final rendering should consume the Sprint 1 bucket contract.
- **Acceptance Criteria**:
  - Desktop layout keeps the active order table and inspector visible together.
  - Inspector has `position: sticky` or equivalent behavior within the workbench viewport.
  - At widths around `1265px`, inspector does not fall below the plan board.
  - Existing order selection, validation, adjustment, cancellation, and confirmation actions still work.
- **Validation**:
  - Browser check at `1440x900`, `1280x720`, and `1024x768`.
  - Screenshot or DOM metric confirms selected-order inspector is visible after selecting a row.

### Task 3.2: Make Left Order Pool Collapsible after Draft Activation

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/src/index.css`
- **Description**: Keep the order pool as the pre-draft input surface, then collapse it into a drawer or compact rail once `activePlan` exists.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Before draft creation, pending order search/filter/select remains first-class.
  - After draft creation, central review area gets more width.
  - User can reopen the order pool to create another draft or inspect pending inputs.
  - Collapse state is visible and reversible.
- **Validation**:
  - Browser check: create/open a draft, collapse and reopen order pool, selection state remains stable.

### Task 3.3: Prioritize Order Review and Root Cause Analysis in Main Area

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/src/index.css`
- **Description**: Make the default central view an order-dimension review table that emphasizes blocked, late, and validation-blocked rows.
- **Dependencies**: Sprint 1, Task 2.1.
- **Acceptance Criteria**:
  - Default tab after opening a partial or failed draft should guide users to unresolved work, for example `草案阻断` or `未排订单` when hard errors exist.
  - `根因/提示` content is visible without mandatory horizontal scrolling for common desktop widths.
  - Long root cause text can expand into row details or inspector details instead of widening the table.
  - KPI cards and bucket tabs are not duplicated as two competing filter systems.
- **Validation**:
  - Browser check on a partial draft: unresolved counts are visible above the table, and row selection updates the inspector.
  - E2E asserts default active tab for blocked draft.

### Task 3.4: Move Resource View into a Secondary Workspace Tab

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/src/index.css`
- **Description**: Replace the resource view section under the order table with top-level workspace view tabs such as `订单复核` and `资源视图`.
- **Dependencies**: Task 3.1.
- **Acceptance Criteria**:
  - `订单复核` is the default view.
  - `资源视图` preserves machine lanes and drag-to-adjust behavior.
  - Switching views does not clear selected order or open adjustment form unexpectedly.
  - Resource lanes no longer create a very long below-the-fold page section.
- **Validation**:
  - Browser check: select order in order-review view, switch to resource view, selected task remains highlighted if present.
  - E2E covers view switching.

### Task 3.5: Make Manufacturing Queue Collapsible and Contextual

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/src/index.css`
- **Description**: Collapse the manufacturing queue by default and surface a compact queue summary near the publish action.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Queue panel is not a full-width always-visible section at the bottom.
  - If queue is empty, show only a compact empty state or hide behind a toggle.
  - After successful publish, queue summary becomes prominent and can expand to row details.
  - Queue expansion does not push the active inspector out of view.
- **Validation**:
  - Browser check with empty queue and non-empty queue.
  - E2E successful publish path verifies queue summary count.

### Task 3.6: Add Layout-Specific Test IDs and Visual Checks

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`, `web/e2e/`
- **Description**: Add test IDs and browser assertions for layout behavior.
- **Dependencies**: Tasks 3.1-3.5.
- **Acceptance Criteria**:
  - Add IDs for:
    - `workbench-order-pool-toggle`
    - `workbench-order-pool`
    - `workbench-main-workspace`
    - `workbench-view-order-review`
    - `workbench-view-resource`
    - `workbench-inspector`
    - `workbench-queue-toggle`
    - `workbench-queue-panel`
  - E2E asserts inspector visibility after selecting an order.
  - E2E asserts resource view is hidden until selected.
  - E2E asserts queue panel collapsed state before publish and expanded/available state after publish.
- **Validation**:
  - `cd web && npm run e2e`

## Sprint 4: Settings Feedback and Test Hooks

**Goal**: Improve operator confidence and make the workbench reliably testable.

**Demo/Validation**:
- Toggling any workbench switch produces a small success or failure message.
- Key controls have stable `data-testid` attributes.
- Automated tests can target workflows without brittle Chinese text matching.

### Task 4.1: Add Lightweight Settings Save Feedback

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`
- **Description**: Update `updateSetting()` to show save-in-progress, saved, and rollback-on-error states.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - On toggle, show `保存中...` or disable only the toggled switch while saving.
  - On success, show `系统开关已保存`.
  - On failure, restore previous value and show backend error.
  - Feedback is lightweight and does not push main layout significantly.
- **Validation**:
  - Browser check: toggle `允许人工调整`; success message appears.
  - Simulated API failure test or mocked e2e asserts rollback behavior.

### Task 4.2: Add Stable `data-testid` Attributes

- **Location**: `web/src/pages/ScheduleWorkbench.jsx`
- **Description**: Add test IDs to controls and sections used in e2e.
- **Dependencies**: None.
- **Acceptance Criteria**:
  - Add IDs for:
    - `workbench-refresh`
    - `workbench-search`
    - `workbench-filter-order-class`
    - `workbench-filter-cleanroom`
    - `workbench-select-filtered`
    - `workbench-clear-selected`
    - `workbench-create-preplan`
    - `workbench-validate-preplan`
    - `workbench-confirm-preplan`
    - `workbench-cancel-preplan`
    - `workbench-cancel-confirm`
    - `workbench-cancel-reason`
    - `workbench-order-tab-input`
    - `workbench-order-tab-schedulable`
    - `workbench-order-tab-scheduled`
    - `workbench-order-tab-blocked`
    - `workbench-order-tab-late`
    - `workbench-order-table`
    - `workbench-selected-order-review`
    - `workbench-start-adjustment`
    - `workbench-adjustment-machine`
    - `workbench-adjustment-start`
    - `workbench-adjustment-end`
    - `workbench-adjustment-reason-code`
    - `workbench-adjustment-reason-text`
    - `workbench-submit-adjustment`
    - `workbench-status`
    - Layout IDs from Sprint 3.
  - Dynamic order rows use `data-testid="workbench-plan-order-{order_id}"`.
  - Dynamic draft history rows use `data-testid="workbench-preplan-{run_id}"`.
- **Validation**:
  - Run frontend lint.
  - Run e2e locator smoke against the live page.

### Task 4.3: Introduce Frontend E2E Harness

- **Location**: `web/package.json`, `web/e2e/`, optionally `web/playwright.config.js`
- **Description**: Add Playwright-based e2e scripts if the project does not already have a browser-test framework.
- **Dependencies**: Task 4.2.
- **Acceptance Criteria**:
  - `npm run e2e` runs against `http://localhost:3000` by default.
  - Tests can reuse an auth helper that logs in as admin.
  - Tests do not depend on generated visual screenshots as assertions unless needed for layout.
- **Validation**:
  - `cd web && npm run e2e`

## Sprint 5: Workbench E2E Closed Loop

**Goal**: Cover the complete UI workflow requested by the user: search, filter, create, validate, adjust, cancel, and publish interception.

**Demo/Validation**:
- One automated suite exercises the workbench in a running app.
- Manual browser smoke follows the same checklist.

### Task 5.1: E2E Search and Filter

- **Location**: `web/e2e/workbench.spec.ts` or equivalent
- **Description**: Verify order-pool search and dropdown filters.
- **Dependencies**: Task 4.2, Task 4.3.
- **Acceptance Criteria**:
  - Search by known order id narrows the list.
  - Order-class filter changes the list and selected count.
  - Cleanroom filter changes the list and selected count.
  - Clearing filters restores visible pending orders.
- **Validation**:
  - `npm run e2e -- workbench`

### Task 5.2: E2E Create and Validate Preplan

- **Location**: `web/e2e/workbench.spec.ts`
- **Description**: Select orders, create draft, validate draft.
- **Dependencies**: Sprint 1, Task 4.3.
- **Acceptance Criteria**:
  - Select at least one pending order using stable row selectors.
  - Create preplan and capture run id from UI or API.
  - Verify active plan header shows draft status.
  - Click validate and assert validation panel updates.
  - Assert order bucket tabs exist and at least one row can be selected.
- **Validation**:
  - UI state plus backend `GET /api/schedule/preplans/{run_id}` confirms lifecycle remains `DRAFT` or becomes `VALIDATED` depending on validation result.

### Task 5.3: E2E Manual Adjustment

- **Location**: `web/e2e/workbench.spec.ts`
- **Description**: Start an adjustment on a scheduled order and submit a valid or intentionally invalid adjustment based on current fixture.
- **Dependencies**: Task 5.2.
- **Acceptance Criteria**:
  - Selecting a scheduled order does not open the form automatically.
  - Clicking `发起人工调整` opens the form.
  - Required reason behavior follows `manual_adjust_reason_required`.
  - Submit records an audit row when valid or shows structured validation errors when invalid.
- **Validation**:
  - UI audit list updates.
  - Backend detail shows `adjustments.length` increased for valid adjustment or failed audit entry exists for invalid attempt.

### Task 5.4: E2E Cancel Draft Safety

- **Location**: `web/e2e/workbench.spec.ts`
- **Description**: Verify two-step cancellation and reason persistence.
- **Dependencies**: Task 2.2, Task 4.3.
- **Acceptance Criteria**:
  - First `废弃草案` click opens confirmation and does not change lifecycle.
  - Enter reason and confirm.
  - Active draft clears or selected draft shows `已废弃`.
  - Pending order pool is not reduced by cancellation.
  - Manufacturing queue is not changed.
- **Validation**:
  - Backend detail returns `lifecycle_status=CANCELLED` and matching `cancel_reason`.

### Task 5.5: E2E Publish Interception

- **Location**: `web/e2e/workbench.spec.ts`
- **Description**: Verify that invalid drafts cannot publish from UI and backend.
- **Dependencies**: Task 5.2.
- **Acceptance Criteria**:
  - When validation has hard errors, `确认进入制造队列` is disabled.
  - Direct backend call to confirm the same run returns `400`.
  - Manufacturing queue count remains unchanged.
- **Validation**:
  - UI disabled state and HTTP response both checked.

### Task 5.6: E2E Successful Publish Path

- **Location**: `web/e2e/workbench.spec.ts`
- **Description**: Add a separate fixture or selected-order subset that can publish successfully.
- **Dependencies**: Task 4.3, stable test data.
- **Acceptance Criteria**:
  - Valid draft can be confirmed.
  - Confirmed run becomes active.
  - Scheduled orders move from `PENDING` to `SCHEDULED`.
  - Manufacturing queue gains rows for scheduled tasks.
  - Confirmed draft cannot be adjusted or cancelled.
- **Validation**:
  - Backend queue and order status checked after publish.

## Sprint 6: Final Closed-Loop Verification

**Goal**: Prove the work is ready for demo and safe to commit.

### Required Commands

- Backend unit tests:
  - `python -m pytest tests/test_scheduler_validation.py tests/test_dashboard_summary.py`
- Backend/API contract tests:
  - `python -m pytest tests/test_preplan_contract.py`
  - `APS_RUN_HTTP_TESTS=1 python -m pytest tests/test_api.py`
- Frontend static checks:
  - `cd web && npm run lint`
  - `cd web && npm run build`
- Frontend e2e:
  - `cd web && npm run e2e`

### Manual Browser Smoke

1. Open `http://localhost:3000/workbench`.
2. Confirm pending order count is visible.
3. Search a known order id.
4. Apply order type and cleanroom filters.
5. Select filtered orders and create a preplan.
6. Confirm the order pool can collapse and reopen after a draft is active.
7. Verify tabs: 输入订单, 可排订单, 已排订单, 未排订单, 延期订单, 草案阻断.
8. Select an order row and confirm the fixed inspector updates without page scroll.
9. Validate the draft.
10. Switch from 订单复核 to 资源视图 and back; selected order context remains stable.
11. Confirm manufacturing queue is collapsed before publish.
12. Attempt publish on a blocked draft and confirm it is intercepted.
13. Start a manual adjustment and verify audit behavior.
14. Cancel a draft using a custom reason and reload.
15. Verify cancelled reason persists and queue did not change.
16. Create or select a clean publishable draft and confirm manufacturing queue creation.

### Demo Acceptance Criteria

- The workbench can explain a draft at order level, not only machine level.
- The layout keeps order review and inspector visible together on desktop and common laptop widths.
- The left order pool is collapsible after a draft exists.
- Resource view is a secondary workspace tab, not a long section under the order table.
- Manufacturing queue is collapsed by default and becomes prominent after publish.
- “可排订单” has a backend-backed meaning.
- “已排订单” and “可排订单” are not frontend aliases.
- “未排订单” and “延期订单” show direct reasons or route users to the selected-order review.
- Draft cancellation cannot happen by a single accidental click.
- System switches provide visible save feedback.
- The core workbench workflow is covered by e2e tests using stable selectors.
- A blocked publish is prevented both by UI and API.
- A successful publish creates manufacturing queue rows and updates order status.

## Potential Risks and Gotchas

- The current scheduler may not have a real “eligible but unplaced” state because all hard-eligible orders are normally scheduled. The contract should still include `unplaced_schedulable_orders: []` so the UI remains correct when optional scheduling or capacity-window pruning is introduced.
- Some source files display Chinese as mojibake in PowerShell output. Verify file content with UTF-8-aware editor or browser-rendered UI before assuming text is broken.
- E2E tests need stable demo data. If tests mutate the shared database, add setup/cleanup steps or isolate them behind a test database.
- Publish success and publish interception should be separate tests. Mixing them in one run makes failure diagnosis difficult.
- Manual adjustment tests should not rely on drag-and-drop first. Start with the explicit `发起人工调整` button, then add a drag/drop case later if needed.

## Rollback Plan

- Backend response additions are additive and can be rolled back by removing new bucket fields while keeping existing fields.
- Frontend rendering can fall back to existing `tasks`, `diagnostics`, and `blocked_orders` if new fields are absent.
- E2E additions can be disabled by removing the `npm run e2e` script without affecting runtime behavior.
