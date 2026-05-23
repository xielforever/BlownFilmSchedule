import { expect, test } from '@playwright/test';

const API_BASE_URL = process.env.APS_API_BASE_URL || 'http://localhost:8000';
const credentials = {
  username: process.env.APS_E2E_USERNAME || 'admin',
  password: process.env.APS_E2E_PASSWORD || 'admin123',
};

async function login(request, page) {
  const response = await request.post(`${API_BASE_URL}/api/auth/login`, {
    form: credentials,
  });
  expect(response.ok()).toBeTruthy();
  const token = (await response.json()).access_token;

  await page.goto('/login');
  await page.evaluate(value => localStorage.setItem('aps_token', value), token);
}

test('shows global policy center and read-only workbench policy summary', async ({ page, request }) => {
  await login(request, page);

  await page.goto('/config?tab=policy');
  await expect(page.getByTestId('config-policy-page')).toBeVisible();
  await expect(page.getByTestId('config-audit-panel')).toBeVisible();
  await expect(page.getByTestId('config-audit-panel')).toContainText('配置审计');
  await expect(page.getByTestId('config-policy-review_required')).toBeVisible();
  await expect(page.getByTestId('config-policy-maintenance_constraint_enabled')).toBeVisible();
  await page.getByTestId('config-policy-machine_capability_constraint_enabled').click();
  await expect(page.getByTestId('config-policy-risk-confirm')).toContainText('关闭关键排程约束');
  await page.getByTestId('config-policy-save').click();
  await expect(page.locator('.config-status')).toContainText('关闭关键约束前请先确认');
  await page.getByRole('button', { name: '取消' }).click();
  await page.getByTestId('config-policy-save').click();
  await expect(page.locator('.config-status')).toContainText('变更原因');

  await page.goto('/config?tab=rules');
  await expect(page.getByTestId('config-rule-state-filter')).toBeVisible();

  await page.goto('/workbench');
  await expect(page.getByTestId('workbench-policy-summary')).toBeVisible();
  await expect(page.getByTestId('workbench-policy-summary')).toContainText('全局排程策略');
  await expect(page.getByRole('link', { name: '配置策略' })).toHaveAttribute('href', '/config?tab=policy');
});
