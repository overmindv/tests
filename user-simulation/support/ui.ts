import { expect, test as base, type Page, type TestInfo } from '@playwright/test';

import { redactTestError } from './redact';

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    await use(page);
    for (const error of testInfo.errors) redactTestError(error);
    if (!page.isClosed() && testInfo.status !== testInfo.expectedStatus) {
      await capture(page, testInfo, 'failure');
    }
  },
});
export { expect };

export async function capture(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({
    path,
    fullPage: true,
    mask: [page.locator('input[type="password"], input[name="email"], input[name="phone"]')],
  });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

export async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.content, 'Страница не требует горизонтального скролла').toBeLessThanOrEqual(dimensions.viewport + 1);
}

export async function openNavigation(page: Page) {
  const menu = page.getByRole('button', { name: 'Открыть меню', exact: true });
  if (await menu.isVisible()) await menu.click();
}

export async function signIn(page: Page, email: string, password: string) {
  await page.goto('/login');
  await page.getByLabel('Электронная почта').fill(email);
  await page.getByLabel('Пароль', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  // После входа допустим возврат на исходную защищённую страницу.
  await expect(page.getByRole('button', { name: 'Меню профиля' })).toBeVisible();
  await expect(page).not.toHaveURL(/\/login$/);
}
