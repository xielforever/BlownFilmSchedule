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

test('uses Chinese labels for gantt navigation and page headings', async ({ page, request }) => {
  await login(request, page);

  await page.goto('/dashboard');
  await expect(page.locator('.sidebar-nav a[href="/gantt"]')).toContainText('甘特图');
  await expect(page.getByRole('heading', { name: '交互式甘特图' })).toBeVisible();
  await expect(page.getByRole('link', { name: '打开完整甘特图' })).toBeVisible();

  await page.goto('/gantt');
  await expect(page.getByRole('heading', { name: '排程甘特图' })).toBeVisible();
});
