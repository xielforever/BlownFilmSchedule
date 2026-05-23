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

const routes = [
  { path: '/orders', marker: '订单管理' },
  { path: '/config?tab=orders', marker: '配置中心', secondaryMarker: '新建订单' },
  { path: '/workbench', marker: '排程工作台', secondaryMarker: '订单池' },
  { path: '/gantt', marker: '排程甘特图' },
  { path: '/dashboard', marker: '仪表盘 (APS)', secondaryMarker: '交互式甘特图' },
];

test('main planning routes render meaningful Chinese screens without runtime errors', async ({ page, request }) => {
  const consoleErrors = [];
  const pageErrors = [];
  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', error => pageErrors.push(error.message));

  await login(request, page);

  for (const route of routes) {
    consoleErrors.length = 0;
    pageErrors.length = 0;

    await page.goto(route.path);
    await expect(page.locator('#root')).toContainText(route.marker);
    if (route.secondaryMarker) {
      await expect(page.locator('#root')).toContainText(route.secondaryMarker);
    }

    const rootTextLength = await page.locator('#root').evaluate(element => element.innerText.trim().length);
    expect(rootTextLength).toBeGreaterThan(40);
    await expect(page.locator('body')).not.toContainText('Vite Error');
    await expect(page.locator('body')).not.toContainText('Internal Server Error');
    await expect(page.locator('body')).not.toContainText('ReferenceError');
    await expect(page.locator('body')).not.toContainText('TypeError');
    expect(pageErrors, `${route.path} page errors`).toEqual([]);
    expect(consoleErrors, `${route.path} console errors`).toEqual([]);
  }
});
