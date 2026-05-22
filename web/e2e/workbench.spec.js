import { expect, test } from '@playwright/test';

const API_BASE_URL = process.env.APS_API_BASE_URL || 'http://localhost:8000';
const credentials = {
  username: process.env.APS_E2E_USERNAME || 'admin',
  password: process.env.APS_E2E_PASSWORD || 'admin123',
};

let token;
let originalSettings;
let cleanupRunIds = [];

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
  const toggle = page.getByTestId('workbench-setting-manual-adjust');
  await expect(toggle).toBeVisible();
  if ((await toggle.getAttribute('aria-pressed')) !== 'true') {
    await toggle.click();
    await expect(page.getByTestId('workbench-status')).toContainText('系统开关已保存');
  }
}

async function currentRunId(page) {
  const text = await page.getByTestId('workbench-active-preplan-summary').innerText();
  const match = text.match(/#(\d+)/);
  expect(match).toBeTruthy();
  return Number(match[1]);
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
    await login(request, page);
    await configureWorkbenchSettings(request);
    await openWorkbench(page);
  });

  test.afterEach(async ({ request }) => {
    for (const runId of cleanupRunIds) {
      await cancelPreplan(request, runId);
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
    await expect(page.getByTestId('workbench-create-preplan')).toContainText('(1)');
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

    await expect(page.getByTestId('workbench-order-pool-toggle')).toHaveAttribute('aria-expanded', 'false');
    await page.setViewportSize({ width: 1265, height: 720 });
    const layout = await page.evaluate(() => {
      const plan = document.querySelector('[data-testid="workbench-main-workspace"]')?.getBoundingClientRect();
      const inspector = document.querySelector('[data-testid="workbench-inspector"]')?.getBoundingClientRect();
      return {
        sameRow: Boolean(plan && inspector && Math.abs(plan.top - inspector.top) < 4 && inspector.left > plan.left),
        inspectorVisible: Boolean(inspector && inspector.top >= 0 && inspector.top < window.innerHeight),
        pageHasHorizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      };
    });
    expect(layout.sameRow).toBeTruthy();
    expect(layout.inspectorVisible).toBeTruthy();
    expect(layout.pageHasHorizontalScroll).toBeFalsy();

    await page.getByTestId('workbench-order-pool-toggle').click();
    await expect(page.getByTestId('workbench-search')).toBeVisible();

    await page.getByTestId('workbench-validate-preplan').click();
    await expect(page.getByTestId('workbench-status')).toBeVisible();
    await expect(page.getByTestId('workbench-order-tab-input')).toBeVisible();
    await page.getByTestId('workbench-order-tab-input').click();
    const firstPlanOrder = page.locator('[data-testid^="workbench-plan-order-"]').first();
    const selectedOrderId = (await firstPlanOrder.getAttribute('data-testid')).replace('workbench-plan-order-', '');
    await firstPlanOrder.click();
    await expect(page.getByTestId('workbench-selected-order-review')).toContainText(selectedOrderId);

    await expect(page.getByTestId('workbench-resource-view')).toBeHidden();
    await page.getByTestId('workbench-view-resource').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeVisible();
    await page.getByTestId('workbench-view-order-review').click();
    await expect(page.getByTestId('workbench-resource-view')).toBeHidden();
    await expect(page.getByTestId('workbench-queue-panel')).toHaveClass(/collapsed/);
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
      item => (item.validation?.hard_error_count || 0) > 0,
      12,
    );
    test.skip(!draft, 'no invalid pending-order subset available for publish interception');
    const runId = draft.run.run_id;
    const queueBefore = await apiJson(request, 'get', '/api/schedule/manufacturing-queue');
    expect(queueBefore.ok()).toBeTruthy();
    const queueBeforeCount = (await queueBefore.json()).length;

    await openWorkbench(page);
    await expect(page.getByTestId('workbench-confirm-preplan')).toBeDisabled();
    await expect(page.getByText('发布受阻')).toBeVisible();

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
    await expect(page.getByTestId('workbench-confirm-preplan')).toBeEnabled();
    await page.getByTestId('workbench-confirm-preplan').click();
    await expect(page.getByTestId('workbench-status')).toContainText('已确认进入制造队列');
    await expect(page.getByTestId('workbench-queue-panel')).toHaveClass(/expanded/);

    const detail = await detailForRun(request, runId);
    expect(detail.run.lifecycle_status).toBe('CONFIRMED');
    const queue = await apiJson(request, 'get', '/api/schedule/manufacturing-queue');
    expect(queue.ok()).toBeTruthy();
    expect((await queue.json()).some(item => item.run_id === runId)).toBeTruthy();

    const clear = await apiJson(request, 'post', '/api/schedule/clear-active');
    expect(clear.ok()).toBeTruthy();
  });
});
