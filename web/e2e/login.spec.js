import { expect, test } from '@playwright/test';

async function openLoginWithErrors(page, detail) {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.route('**/api/auth/login', route => route.fulfill({
    status: 400,
    contentType: 'application/json',
    body: JSON.stringify({ detail }),
  }));

  await page.goto('/login');
  await page.getByPlaceholder('用户名，例如 admin / planner / viewer').fill('bad-user');
  await page.getByPlaceholder('输入密码').fill('bad-password');
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page.locator('.login-error')).toBeVisible();
  return pageErrors;
}

test('formats object login errors as readable text instead of rendering objects', async ({ page }) => {
  const pageErrors = await openLoginWithErrors(page, { message: '用户名或密码错误' });

  await expect(page.locator('.login-error')).toContainText('用户名或密码错误');
  expect(pageErrors).toEqual([]);
});

test('formats array login errors as readable text instead of rendering arrays', async ({ page }) => {
  const pageErrors = await openLoginWithErrors(page, [{ msg: '用户名字段缺失' }]);

  await expect(page.locator('.login-error')).toContainText('用户名字段缺失');
  expect(pageErrors).toEqual([]);
});
