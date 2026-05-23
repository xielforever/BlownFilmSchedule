import { expect, test } from '@playwright/test';

const API_BASE_URL = process.env.APS_API_BASE_URL || 'http://localhost:8000';
const credentials = {
  username: process.env.APS_E2E_USERNAME || 'admin',
  password: process.env.APS_E2E_PASSWORD || 'admin123',
};

let token;
let createdOrderId;
let cleanupRunIds = [];

async function apiJson(request, method, path, options = {}) {
  return request[method](`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  });
}

async function login(request, page) {
  const response = await request.post(`${API_BASE_URL}/api/auth/login`, {
    form: credentials,
  });
  expect(response.ok()).toBeTruthy();
  token = (await response.json()).access_token;

  await page.goto('/login');
  await page.evaluate(value => localStorage.setItem('aps_token', value), token);
}

async function sampleOrder(request) {
  const response = await apiJson(request, 'get', '/api/orders', {
    params: { page: 1, size: 1 },
  });
  expect(response.ok()).toBeTruthy();
  const items = (await response.json()).items || [];
  expect(items.length).toBeGreaterThan(0);
  return items[0];
}

test.describe.serial('config order entry flow', () => {
  test.beforeEach(async ({ page, request }) => {
    createdOrderId = '';
    cleanupRunIds = [];
    await login(request, page);
  });

  test.afterEach(async ({ request }) => {
    for (const runId of cleanupRunIds) {
      await apiJson(request, 'post', `/api/schedule/preplans/${runId}/cancel`, {
        data: { reason: 'E2E cleanup' },
      });
    }
    if (!createdOrderId) return;
    await apiJson(request, 'patch', `/api/orders/${createdOrderId}`, {
      data: {
        status: 'CANCELLED',
        reason_code: 'E2E_CLEANUP',
        reason_text: 'E2E cleanup',
      },
    });
  });

  test('creates an order and requires revision reason before saving changes', async ({ page, request }) => {
    const sample = await sampleOrder(request);
    createdOrderId = `E2E${Date.now().toString().slice(-10)}`;

    await page.goto('/config?tab=orders');
    await page.getByTestId('config-create-order-open').click();
    await expect(page.getByTestId('config-order-create-customer')).toContainText('标准客户');
    await expect(page.getByTestId('config-order-create-cleanroom')).toContainText('十万级洁净');
    await page.getByTestId('config-order-create-id').fill(createdOrderId);
    await page.getByTestId('config-order-create-product').fill(sample.product_type);
    await page.getByTestId('config-order-create-customer').selectOption('STANDARD');
    await page.getByTestId('config-order-create-width').fill('520');
    await page.getByTestId('config-order-create-thickness').fill('35');
    await page.getByTestId('config-order-create-quantity').fill('1200');
    await page.getByTestId('config-order-create-cleanroom').selectOption('Class_100K');
    await page.getByTestId('config-order-create-class').selectOption('NORMAL');
    await page.getByTestId('config-order-create-due').fill('2026-06-01T08:00');
    await page.getByTestId('config-order-create-reason').fill('E2E 创建订单');
    await page.getByTestId('config-order-create-submit').click();

    await expect(page.getByText(`订单 ${createdOrderId} 已创建`)).toBeVisible();
    await page.getByPlaceholder('搜索订单、产品、机台').fill(createdOrderId);
    await expect(page.getByTestId(`config-order-item-${createdOrderId}`)).toBeVisible();
    await page.getByTestId(`config-order-item-${createdOrderId}`).click();

    await page.getByTestId('config-order-width').fill('530');
    await page.getByTestId('config-order-save').click();
    await expect(page.getByText('请填写订单修订原因')).toBeVisible();

    await page.getByTestId('config-order-reason-text').fill('E2E 修改幅宽');
    await page.getByTestId('config-order-save').click();
    await expect(page.getByTestId('config-order-revision-summary')).toContainText('修订 #');
    await expect(page.getByTestId('config-order-revision-summary')).toContainText('无受影响草案');

    await page.goto('/workbench');
    await expect(page.getByTestId('workbench-main-workspace')).toBeVisible();
    const poolToggle = page.getByTestId('workbench-order-pool-toggle');
    if (await poolToggle.isVisible().catch(() => false)) {
      const expanded = await poolToggle.getAttribute('aria-expanded');
      if (expanded === 'false') await poolToggle.click();
    }
    await page.getByTestId('workbench-search').fill(createdOrderId);
    await expect(page.getByTestId(`workbench-pending-order-${createdOrderId}`)).toBeVisible();
  });

  test('shows impacted draft and stale validation after revising a selected order', async ({ page, request }) => {
    const sample = await sampleOrder(request);
    createdOrderId = `E2E${Date.now().toString().slice(-10)}`;

    const created = await apiJson(request, 'post', '/api/orders', {
      data: {
        order_id: createdOrderId,
        product_type: sample.product_type,
        customer_class: 'STANDARD',
        target_width: 520,
        target_thickness: 35,
        total_quantity_kg: 1200,
        cleanroom_req: 'Class_100K',
        order_class: 'NORMAL',
        due_date: '2026-06-01T08:00:00',
        reason_code: 'E2E_SETUP',
        reason_text: 'E2E setup',
      },
    });
    expect(created.ok()).toBeTruthy();

    const draft = await apiJson(request, 'post', '/api/schedule/preplans', {
      data: { order_ids: [createdOrderId], mode: 'AUTO' },
      timeout: 60_000,
    });
    expect(draft.ok()).toBeTruthy();
    const draftDetail = await draft.json();
    cleanupRunIds.push(draftDetail.run.run_id);

    await page.goto(`/config?tab=orders&order=${createdOrderId}`);
    await expect(page.getByRole('heading', { name: createdOrderId })).toBeVisible();
    await page.getByTestId('config-order-width').fill('530');
    await page.getByTestId('config-order-reason-text').fill('E2E 修改已入草案订单幅宽');
    await page.getByTestId('config-order-save').click();
    await expect(page.getByTestId('config-order-revision-summary')).toContainText(`影响草案：#${draftDetail.run.run_id}`);

    await page.goto('/workbench');
    await expect(page.getByTestId('workbench-main-workspace')).toBeVisible();
    await page.getByTestId('workbench-version-drawer-toggle').click();
    await page.getByTestId(`workbench-version-run-${draftDetail.run.run_id}`).click();
    await expect(page.getByTestId('workbench-active-preplan-summary')).toContainText(`#${draftDetail.run.run_id}`);
    await expect(page.locator('.workbench-publish-hint')).toContainText('订单已修订，需要重新预排');
    await page.getByTestId('workbench-stage-validate_publish').click();
    await expect(page.getByTestId('workbench-confirm-preplan')).toBeDisabled();
  });
});
