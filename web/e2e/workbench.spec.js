import { expect, test } from '@playwright/test';

const API_BASE_URL = process.env.APS_API_BASE_URL || 'http://localhost:8000';
const credentials = {
  username: process.env.APS_E2E_USERNAME || 'admin',
  password: process.env.APS_E2E_PASSWORD || 'admin123',
};

let token;
let originalSettings;
let cleanupRunIds = [];
let cleanupOrderIds = [];

function testIdPart(value) {
  return String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '_');
}

async function apiJson(request, method, path, options = {}) {
  const response = await request[method](`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  });
  return response;
}

async function login(request, page) {
  const response = await request.post(`${API_BASE_URL}/api/auth/login`, {
    form: credentials,
  });
  expect(response.ok()).toBeTruthy();
  token = (await response.json()).access_token;

  await page.goto('/login');
  await page.evaluate(value => localStorage.setItem('aps_token', value), token);
  await page.goto('/workbench');
  await expect(page.getByTestId('workbench-main-workspace')).toBeVisible();
}

async function configureWorkbenchSettings(request) {
  const settings = await apiJson(request, 'get', '/api/schedule/settings');
  expect(settings.ok()).toBeTruthy();
  originalSettings = await settings.json();

  const updated = await apiJson(request, 'patch', '/api/schedule/settings', {
    data: {
      review_required: true,
      auto_release_enabled: false,
      manual_adjust_enabled: true,
      manual_adjust_reason_required: false,
      publish_with_warnings_allowed: true,
      machine_capability_constraint_enabled: true,
      change_reason: 'E2E workbench setup',
    },
  });
  expect(updated.ok()).toBeTruthy();
}

async function restoreWorkbenchSettings(request) {
  if (!originalSettings) return;
  await apiJson(request, 'patch', '/api/schedule/settings', {
    data: {
      review_required: originalSettings.review_required,
      auto_release_enabled: originalSettings.auto_release_enabled,
      manual_adjust_enabled: originalSettings.manual_adjust_enabled,
      manual_adjust_reason_required: originalSettings.manual_adjust_reason_required,
      publish_with_warnings_allowed: originalSettings.publish_with_warnings_allowed,
      material_constraint_enabled: originalSettings.material_constraint_enabled,
      maintenance_constraint_enabled: originalSettings.maintenance_constraint_enabled,
      setup_rules_enabled: originalSettings.setup_rules_enabled,
      cleanroom_constraint_enabled: originalSettings.cleanroom_constraint_enabled,
      machine_capability_constraint_enabled: originalSettings.machine_capability_constraint_enabled,
      due_date_optimization_enabled: originalSettings.due_date_optimization_enabled,
      change_reason: 'E2E workbench restore',
    },
  });
}

async function pendingOrders(request, limit = 60) {
  const response = await apiJson(request, 'get', '/api/orders', {
    params: { status: 'PENDING', page: 1, size: limit },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).items || [];
}

async function createPendingOrderFromSample(request, sample, orderId) {
  const response = await apiJson(request, 'post', '/api/orders', {
    data: {
      order_id: orderId,
      product_type: sample.product_type,
      customer_class: sample.customer_class || 'STANDARD',
      target_width: sample.target_width,
      target_thickness: sample.target_thickness,
      total_quantity_kg: sample.total_quantity_kg || 1200,
      cleanroom_req: sample.cleanroom_req,
      order_class: sample.order_class || 'NORMAL',
      due_date: sample.due_date || '2026-06-01T08:00:00',
      reason_code: 'E2E_SETUP',
      reason_text: 'E2E setup for workbench pagination',
    },
  });
  expect(response.ok()).toBeTruthy();
  cleanupOrderIds.push(orderId);
}

async function createPreplan(request, orderIds) {
  const response = await apiJson(request, 'post', '/api/schedule/preplans', {
    data: { order_ids: orderIds, mode: 'AUTO' },
    timeout: 60_000,
  });
  expect(response.ok()).toBeTruthy();
  const detail = await response.json();
  cleanupRunIds.push(detail.run.run_id);
  return detail;
}

async function cancelPreplan(request, runId, reason = 'E2E cleanup') {
  await apiJson(request, 'post', `/api/schedule/preplans/${runId}/cancel`, {
    data: { reason },
  });
}

async function detailForRun(request, runId) {
  const response = await apiJson(request, 'get', `/api/schedule/preplans/${runId}`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function openWorkbench(page) {
  await page.goto('/workbench');
  await expect(page.getByTestId('workbench-main-workspace')).toBeVisible();
  await expect(page.getByTestId('workbench-main-workspace')).toHaveAttribute('data-loading', 'false');
}

async function openOrderPoolIfCollapsed(page) {
  const toggle = page.getByTestId('workbench-order-pool-toggle');
  if (await toggle.isVisible().catch(() => false)) {
    const expanded = await toggle.getAttribute('aria-expanded');
    if (expanded === 'false') await toggle.click();
  }
}

async function ensureManualAdjustmentEnabled(page) {
  await expect(page.getByTestId('workbench-policy-summary')).toContainText('人工调整开');
}

async function currentRunId(page) {
  const text = await page.getByTestId('workbench-active-preplan-summary').innerText();
  const match = text.match(/#(\d+)/);
  expect(match).toBeTruthy();
  return Number(match[1]);
}

async function visibleButtonTextCounts(page) {
  const texts = await page.locator('button:visible').evaluateAll(buttons =>
    buttons.map(button => (button.innerText || button.textContent || '').trim()).filter(Boolean),
  );
  return texts.reduce((acc, text) => {
    acc[text] = (acc[text] || 0) + 1;
    return acc;
  }, {});
}

async function expectVisibleButtonCount(page, text, expectedCount) {
  const counts = await visibleButtonTextCounts(page);
  expect(counts[text] || 0).toBe(expectedCount);
}

async function expectNoHorizontalScroll(page) {
  const hasHorizontalScroll = await page.evaluate(() =>
    document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  expect(hasHorizontalScroll).toBeFalsy();
}

async function activeDraftSummaries(request) {
  const response = await apiJson(request, 'get', '/api/schedule/preplans');
  expect(response.ok()).toBeTruthy();
  return (await response.json()).filter(plan => ['DRAFT', 'VALIDATED'].includes(plan.lifecycle_status));
}

async function openDraftVersion(page, runId) {
  const summary = await page.getByTestId('workbench-active-preplan-summary').innerText();
  if (summary.includes(`#${runId}`)) return;
  await page.getByTestId('workbench-version-drawer-toggle').click();
  await expect(page.getByTestId(`workbench-version-run-${runId}`)).toBeVisible();
  await page.getByTestId(`workbench-version-run-${runId}`).click();
  await expect(page.getByTestId('workbench-active-preplan-summary')).toContainText(`#${runId}`);
}

async function findDraft(request, predicate, chunkSize = 10) {
  const orders = await pendingOrders(request, 80);
  for (let index = 0; index < orders.length; index += chunkSize) {
    const chunk = orders.slice(index, index + chunkSize);
    if (!chunk.length) break;
    const detail = await createPreplan(request, chunk.map(order => order.order_id));
    if (predicate(detail)) return detail;
    await cancelPreplan(request, detail.run.run_id, 'E2E non-matching setup cleanup');
  }
  return null;
}

test.describe.serial('schedule workbench closed loop', () => {
  test.beforeEach(async ({ page, request }) => {
    cleanupRunIds = [];
    cleanupOrderIds = [];
    await login(request, page);
    await configureWorkbenchSettings(request);
    await openWorkbench(page);
  });

  test.afterEach(async ({ request }) => {
    for (const runId of cleanupRunIds) {
      await cancelPreplan(request, runId);
    }
    for (const orderId of cleanupOrderIds) {
      await apiJson(request, 'patch', `/api/orders/${orderId}`, {
        data: {
          status: 'CANCELLED',
          reason_code: 'E2E_CLEANUP',
          reason_text: 'E2E cleanup',
        },
      });
    }
    await restoreWorkbenchSettings(request);
    originalSettings = null;
  });

  test('searches, filters, and keeps the order pool reversible', async ({ page, request }) => {
    const orders = await pendingOrders(request, 20);
    test.skip(!orders.length, 'no pending orders available for workbench e2e');
    const sample = orders[0];

    await openOrderPoolIfCollapsed(page);
    await page.getByTestId('workbench-search').fill(sample.order_id);
    await expect(page.getByTestId(`workbench-pending-order-${testIdPart(sample.order_id)}`)).toBeVisible();

    await page.getByTestId('workbench-search').fill('');
    await page.getByTestId('workbench-filter-order-class').selectOption(sample.order_class);
    await expect(page.getByTestId(`workbench-pending-order-${testIdPart(sample.order_id)}`)).toBeVisible();

    await page.getByTestId('workbench-filter-cleanroom').selectOption(sample.cleanroom_req);
    await expect(page.getByTestId(`workbench-pending-order-${testIdPart(sample.order_id)}`)).toBeVisible();

    await page.getByTestId('workbench-filter-order-class').selectOption('');
    await page.getByTestId('workbench-filter-cleanroom').selectOption('');
    await page.getByTestId('workbench-search').fill(sample.order_id);
    await expect(page.getByTestId(`workbench-pending-order-${testIdPart(sample.order_id)}`)).toBeVisible();
    await page.getByTestId(`workbench-pending-order-${testIdPart(sample.order_id)}`).click();
    await expect(page.getByTestId('workbench-inspector-drawer')).toBeVisible();
    await expect(page.getByTestId('workbench-order-pool-inspector')).toContainText(sample.order_id);
    await page.getByTestId('workbench-inspector-close').click();
    await expect(page.getByTestId('workbench-create-preplan')).toContainText('(1)');
  });

  test('keeps the no-draft workbench entry points singular and contextual', async ({ page, request }) => {
    const activeDrafts = await activeDraftSummaries(request);
    test.skip(activeDrafts.length > 0, 'requires no active draft in the demo database');

    await openWorkbench(page);

    await expectVisibleButtonCount(page, '刷新', 1);
    await expectVisibleButtonCount(page, '选择订单后创建', 0);
    await expectVisibleButtonCount(page, '先选择订单', 1);
    await expectVisibleButtonCount(page, '校验方案', 0);
    await expectVisibleButtonCount(page, '确认进入制造队列', 0);
    await expectVisibleButtonCount(page, '废弃草案', 0);
    await expect(page.getByTestId('workbench-stage-order_pool')).toHaveAttribute('aria-current', 'step');
    await expect(page.getByTestId('workbench-stage-draft_review')).toBeDisabled();
    await expect(page.getByTestId('workbench-stage-draft_review-lock-reason')).toContainText('请先从订单池创建预排程草案');
    await expect(page.getByTestId('workbench-stage-validate_publish')).toBeDisabled();
    await expect(page.getByTestId('workbench-stage-manufacturing_queue')).toBeDisabled();
    await expect(page.getByTestId('workbench-stage-next')).toBeDisabled();
    await expect(page.getByTestId('workbench-draft-state-card')).toBeHidden();
    await expect(page.getByTestId('workbench-maintenance-panel')).toBeHidden();
    await expect(page.getByText('清理孤立已排订单')).toBeHidden();
    await expect(page.getByText('撤销当前排程')).toBeHidden();

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
      { width: 1024, height: 768 },
    ]) {
      await page.setViewportSize(viewport);
      await expect(page.getByTestId('workbench-main-workspace')).toBeVisible();
      await expectNoHorizontalScroll(page);
    }
  });

  test('shows screening recommended actions in the pending order pool', async ({ page, request }) => {
    const sample = (await pendingOrders(request, 1))[0];
    test.skip(!sample, 'no sample product available for screening action setup');
    const orderId = `E2EACTION${Date.now().toString().slice(-8)}`;
    const created = await apiJson(request, 'post', '/api/orders', {
      data: {
        order_id: orderId,
        product_type: sample.product_type,
        customer_class: 'STANDARD',
        target_width: 9999,
        target_thickness: 35,
        total_quantity_kg: 1200,
        cleanroom_req: 'Class_100K',
        order_class: 'NORMAL',
        due_date: '2026-06-01T08:00:00',
        reason_code: 'E2E_SETUP',
        reason_text: 'E2E setup for screening action',
      },
    });
    expect(created.ok()).toBeTruthy();
    cleanupOrderIds.push(orderId);

    await openWorkbench(page);
    await openOrderPoolIfCollapsed(page);
    await page.getByTestId('workbench-search').fill(orderId);
    await expect(page.getByTestId(`workbench-pending-order-${testIdPart(orderId)}`)).toBeVisible();
    await expect(page.getByTestId(`workbench-screening-action-${testIdPart(orderId)}-expand_machine_capability`)).toContainText('调整机台规格能力');
    await expect(page.getByTestId(`workbench-screening-override-${testIdPart(orderId)}`)).toContainText('\u7981\u6b62\u8c41\u514d');
  });

  test('paginates long order pools and draft order reviews', async ({ page, request }) => {
    const sample = (await pendingOrders(request, 1))[0];
    test.skip(!sample, 'no sample product available for pagination setup');
    const prefix = `E2EPAGE${Date.now().toString().slice(-7)}`;
    const orderIds = Array.from({ length: 13 }, (_, index) => `${prefix}${String(index + 1).padStart(2, '0')}`);
    for (const orderId of orderIds) {
      await createPendingOrderFromSample(request, sample, orderId);
    }

    await openWorkbench(page);
    await page.getByTestId('workbench-search').fill(prefix);
    await expect(page.getByTestId('workbench-order-pool-pagination')).toBeVisible();
    await expect(page.getByTestId('workbench-order-pool-page-info')).toContainText('1 / 2');
    await expect(page.locator(`[data-testid^="workbench-pending-order-${testIdPart(prefix)}"]`)).toHaveCount(10);
    await page.getByTestId('workbench-order-pool-next').click();
    await expect(page.getByTestId('workbench-order-pool-page-info')).toContainText('2 / 2');
    await expect(page.locator(`[data-testid^="workbench-pending-order-${testIdPart(prefix)}"]`)).toHaveCount(3);

    const draft = await createPreplan(request, orderIds);
    await openWorkbench(page);
    await openDraftVersion(page, draft.run.run_id);
    await page.getByTestId('workbench-order-tab-input').click();
    await expect(page.getByTestId('workbench-draft-orders-pagination')).toBeVisible();
    await expect(page.getByTestId('workbench-draft-orders-page-info')).toContainText('1 / 2');
    await expect(page.locator(`[data-testid^="workbench-plan-order-${testIdPart(prefix)}"]`)).toHaveCount(10);
    await page.getByTestId('workbench-draft-orders-next').click();
    await expect(page.getByTestId('workbench-draft-orders-page-info')).toContainText('2 / 2');
    await expect(page.locator(`[data-testid^="workbench-plan-order-${testIdPart(prefix)}"]`)).toHaveCount(3);
  });

  test('creates, validates, selects, and cancels a draft safely', async ({ page, request }) => {
    const orders = await pendingOrders(request, 8);
    test.skip(!orders.length, 'no pending orders available for draft creation');

    await openOrderPoolIfCollapsed(page);
    await page.getByTestId('workbench-search').fill(orders[0].order_id);
    await page.getByTestId(`workbench-pending-order-${testIdPart(orders[0].order_id)}`).click();
    await page.getByTestId('workbench-create-preplan').click();
    await expect(page.getByTestId('workbench-status')).toContainText('已创建预排程草案', { timeout: 60_000 });
    await expect(page.getByTestId('workbench-active-preplan-summary')).toContainText('#');
    const runId = await currentRunId(page);
    cleanupRunIds.push(runId);

    await expect(page.getByTestId('workbench-workflow-stepper')).toBeVisible();
    await expect(page.getByTestId('workbench-stage-draft_review')).toHaveAttribute('aria-current', 'step');
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('草案复核');
    await expect(page.getByTestId('workbench-draft-review-stage')).toBeVisible();
    await expectVisibleButtonCount(page, '刷新', 1);
    await expectVisibleButtonCount(page, '校验方案', 1);
    await expectVisibleButtonCount(page, '废弃草案', 1);
    await expect(page.getByTestId('workbench-command-bar')).toContainText(`#${runId}`);
    await expect(page.getByTestId('workbench-command-bar')).toContainText('待复核');
    await expect(page.getByTestId('workbench-primary-action')).toContainText('校验方案');
    await expect(page.getByTestId('workbench-order-tab-needs-action')).toBeVisible();
    await expect(page.getByTestId('workbench-version-drawer-toggle')).toBeVisible();

    await page.getByTestId('workbench-stage-order_pool').click();
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('订单池');
    await expect(page.getByTestId('workbench-order-pool-stage')).toBeVisible();
    await expect(page.getByTestId('workbench-order-pool-browser')).toBeVisible();
    await expect(page.getByTestId('workbench-search')).toBeVisible();

    await page.getByTestId('workbench-stage-validate_publish').click();
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('校验发布');
    await expect(page.getByTestId('workbench-validate-publish-stage')).toBeVisible();
    await expect(page.getByTestId('workbench-publish-checklist')).toBeVisible();

    await expect(page.getByTestId('workbench-stage-manufacturing_queue')).toBeDisabled();
    await expect(page.getByTestId('workbench-stage-manufacturing_queue')).toContainText('草案尚未发布');
    await expect(page.getByTestId('workbench-queue-toggle')).toBeHidden();
    await expect(page.getByTestId('workbench-queue-table')).toBeHidden();

    await page.getByTestId('workbench-stage-draft_review').click();
    await expect(page.getByTestId('workbench-draft-review-stage')).toBeVisible();

    await page.setViewportSize({ width: 1265, height: 720 });
    const layout = await page.evaluate(() => {
      const plan = document.querySelector('[data-testid="workbench-main-workspace"]')?.getBoundingClientRect();
      const orderPool = document.querySelector('[data-testid="workbench-order-pool"]')?.getBoundingClientRect();
      const inspector = document.querySelector('[data-testid="workbench-inspector-drawer"]')?.getBoundingClientRect();
      return {
        planWide: Boolean(plan && plan.width > window.innerWidth * 0.74),
        orderPoolVisible: Boolean(orderPool && orderPool.width > 0 && orderPool.height > 0),
        inspectorVisible: Boolean(inspector && inspector.width > 0 && inspector.height > 0),
        pageHasHorizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    expect(layout.planWide).toBeTruthy();
    expect(layout.orderPoolVisible).toBeFalsy();
    expect(layout.inspectorVisible).toBeFalsy();
    expect(layout.pageHasHorizontalScroll).toBeFalsy();

    await page.getByTestId('workbench-validate-preplan').click();
    await expect(page.getByTestId('workbench-status')).toContainText(/校验完成|阻断错误/);
    await page.getByTestId('workbench-stage-draft_review').click();
    await expect(page.getByTestId('workbench-draft-review-stage')).toBeVisible();
    await expect(page.getByTestId('workbench-order-tab-input')).toBeVisible();
    await page.getByTestId('workbench-order-tab-input').click();
    const firstPlanOrder = page.locator('[data-testid^="workbench-plan-order-"]').first();
    const selectedOrderId = (await firstPlanOrder.getAttribute('data-testid')).replace('workbench-plan-order-', '');
    await firstPlanOrder.click();
    await expect(page.getByTestId('workbench-inspector-drawer')).toBeVisible();
    await expect(page.getByTestId('workbench-selected-order-review')).toContainText(selectedOrderId);
    await page.getByTestId('workbench-inspector-close').click();
    await expect(page.getByTestId('workbench-inspector-drawer')).toBeHidden();

    await page.getByTestId('workbench-stage-draft_review').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeHidden();
    await page.getByTestId('workbench-draft-view-resource').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeVisible();
    await page.getByTestId('workbench-draft-view-orders').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeHidden();
    await page.getByTestId('workbench-version-drawer-toggle').click();
    await expect(page.getByTestId('workbench-version-drawer')).toBeVisible();
    await expect(page.getByTestId('workbench-version-drawer')).toContainText(`#${runId}`);
    await expect(page.getByTestId('workbench-version-filter-active')).toBeVisible();
    await expect(page.getByTestId('workbench-version-filter-active')).toHaveAttribute('aria-current', 'true');
    await expect(page.getByTestId(`workbench-version-run-${runId}`)).toHaveAttribute('aria-current', 'true');
    await page.getByTestId('workbench-version-drawer-close').click();
    await expect(page.getByTestId('workbench-version-drawer')).toBeHidden();
    await page.getByTestId('workbench-cancel-preplan').click();
    await expect(page.getByTestId('workbench-cancel-confirm-panel')).toBeVisible();
    expect((await detailForRun(request, runId)).run.lifecycle_status).not.toBe('CANCELLED');

    await page.getByTestId('workbench-cancel-reason').fill('E2E two-step cancellation');
    await page.getByTestId('workbench-cancel-confirm').click();
    await expect(page.getByTestId('workbench-status')).toContainText(`草案 #${runId} 已废弃`);
    const cancelled = await detailForRun(request, runId);
    expect(cancelled.run.lifecycle_status).toBe('CANCELLED');
    expect(cancelled.run.cancel_reason).toBe('E2E two-step cancellation');
  });

  test('keeps maintenance actions behind the advanced maintenance panel', async ({ page }) => {
    await openWorkbench(page);

    await expect(page.getByText('清理孤立已排订单')).toBeHidden();
    await expect(page.getByText('撤销当前排程')).toBeHidden();

    await page.getByTestId('workbench-maintenance-toggle').click();
    await expect(page.getByTestId('workbench-maintenance-panel')).toBeVisible();
    await expect(page.getByText('清理孤立已排订单')).toBeVisible();
    await expect(page.getByText('撤销当前排程')).toBeVisible();
  });

  test('opens manual adjustment explicitly and handles invalid adjustment feedback', async ({ page, request }) => {
    const detail = await findDraft(request, item => (item.scheduled_orders || []).length > 0, 8);
    test.skip(!detail, 'no pending order subset produced scheduled tasks');

    await openWorkbench(page);
    await expect(page.getByTestId('workbench-active-preplan-summary')).toContainText(`#${detail.run.run_id}`);
    await ensureManualAdjustmentEnabled(page);
    await page.getByTestId('workbench-order-tab-scheduled').click();
    const scheduledOrderId = detail.scheduled_orders[0].order_id;
    const scheduledRow = page.getByTestId(`workbench-plan-order-${testIdPart(scheduledOrderId)}`);
    await expect(scheduledRow).toBeVisible();
    await scheduledRow.click();
    await expect(page.getByTestId('workbench-selected-order-review')).toContainText(scheduledOrderId);
    await expect(page.getByTestId('workbench-adjustment-machine')).toBeHidden();
    await expect(page.getByTestId('workbench-start-adjustment')).toBeVisible();
    await page.getByTestId('workbench-start-adjustment').click();
    await expect(page.getByTestId('workbench-adjustment-machine')).toBeVisible();

    const start = await page.getByTestId('workbench-adjustment-start').inputValue();
    await page.getByTestId('workbench-adjustment-end').fill(start);
    await page.getByTestId('workbench-adjustment-reason-text').fill('E2E invalid adjustment check');
    await page.getByTestId('workbench-submit-adjustment').click();
    await expect(page.getByTestId('workbench-status')).toBeVisible();
  });

  test('blocks publishing invalid drafts in UI and API', async ({ page, request }) => {
    const draft = await findDraft(
      request,
      item => item.tasks.length > 0 && (item.validation?.hard_error_count || 0) === 0,
      1,
    );
    test.skip(!draft, 'no pending order subset produced a draft for stale-policy publish interception');
    const runId = draft.run.run_id;
    const staleSettings = await apiJson(request, 'patch', '/api/schedule/settings', {
      data: {
        machine_capability_constraint_enabled: false,
        change_reason: 'E2E make active draft policy snapshot stale',
      },
    });
    expect(staleSettings.ok()).toBeTruthy();
    const queueBefore = await apiJson(request, 'get', '/api/schedule/manufacturing-queue');
    expect(queueBefore.ok()).toBeTruthy();
    const queueBeforeCount = (await queueBefore.json()).length;

    await openWorkbench(page);
    await openDraftVersion(page, runId);
    await page.getByTestId('workbench-stage-validate_publish').click();
    await expect(page.getByTestId('workbench-confirm-preplan')).toBeDisabled();
    await expect(page.getByTestId('workbench-validate-publish-stage')).toContainText('发布受阻');
    const firstValidation = page.locator('[data-testid^="workbench-validation-item-"]').first();
    await expect(firstValidation).toBeVisible();
    await firstValidation.click();
    await expect(page.getByTestId('workbench-inspector-drawer')).toBeVisible();
    await expect(page.getByTestId('workbench-validation-inspector')).toContainText('全局策略已变化');
    await page.getByTestId('workbench-inspector-close').click();

    const directConfirm = await apiJson(request, 'post', `/api/schedule/preplans/${runId}/confirm`);
    expect(directConfirm.status()).toBe(400);
    const queueAfter = await apiJson(request, 'get', '/api/schedule/manufacturing-queue');
    expect(queueAfter.ok()).toBeTruthy();
    expect((await queueAfter.json()).length).toBe(queueBeforeCount);
  });

  test('publishes a valid draft and exposes the manufacturing queue', async ({ page, request }) => {
    const draft = await findDraft(
      request,
      item => item.tasks.length > 0 && (item.validation?.hard_error_count || 0) === 0,
      1,
    );
    test.skip(!draft, 'no single pending order produced a publishable draft');
    const runId = draft.run.run_id;

    await openWorkbench(page);
    await page.getByTestId('workbench-validate-preplan').click();
    await expect(page.getByTestId('workbench-confirm-preplan')).toBeEnabled();
    await page.getByTestId('workbench-confirm-preplan').click();
    await expect(page.getByTestId('workbench-status')).toContainText('已确认进入制造队列');
    await expect(page.getByTestId('workbench-primary-action')).toContainText('查看制造队列');
    await expect(page.getByTestId('workbench-stage-manufacturing_queue')).toHaveAttribute('aria-current', 'step');
    await expect(page.getByTestId('workbench-stage-canvas')).toContainText('制造队列');
    await expect(page.getByTestId('workbench-manufacturing-queue-stage')).toBeVisible();
    await expect(page.getByTestId('workbench-queue-panel')).toHaveClass(/expanded/);
    await expect(page.getByTestId('workbench-queue-table')).toBeVisible();

    const detail = await detailForRun(request, runId);
    expect(detail.run.lifecycle_status).toBe('CONFIRMED');
    const queue = await apiJson(request, 'get', '/api/schedule/manufacturing-queue');
    expect(queue.ok()).toBeTruthy();
    const queueItems = await queue.json();
    const queueItem = queueItems.find(item => item.run_id === runId);
    expect(queueItem).toBeTruthy();

    await page.getByTestId(`workbench-queue-row-${queueItem.id}`).locator('td').first().click();
    await expect(page.getByTestId('workbench-inspector-drawer')).toBeVisible();
    await expect(page.getByTestId('workbench-queue-item-inspector')).toContainText(queueItem.order_id);
    await page.getByTestId('workbench-inspector-close').click();

    await page.getByTestId(`workbench-queue-action-${queueItem.id}-READY`).click();
    await expect(page.getByTestId('workbench-status')).toContainText('已更新为可开工');
    const queueAfterReady = await apiJson(request, 'get', '/api/schedule/manufacturing-queue');
    expect(queueAfterReady.ok()).toBeTruthy();
    expect((await queueAfterReady.json()).some(item => item.id === queueItem.id && item.queue_status === 'READY')).toBeTruthy();

    const clear = await apiJson(request, 'post', '/api/schedule/clear-active');
    expect(clear.ok()).toBeTruthy();
  });
});
