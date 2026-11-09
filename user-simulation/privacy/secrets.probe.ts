import { test, expect } from '../support/ui';

test.beforeEach(async ({ page }) => {
  await page.setContent('<label>Email<input name="email" type="email"></label><label>Password<input type="password"></label>');
  await page.getByLabel('Email').fill(process.env.SIM_ADMIN_EMAIL!);
  await page.getByLabel('Password').fill(process.env.SIM_ADMIN_PASSWORD!);
});

test('privacy canary: обычная ошибка после заполнения формы', async () => {
  throw new Error('Intentional privacy probe failure');
});

test('privacy canary: matcher сохраняет значение поля в ошибке', async ({ page }) => {
  await expect.soft(page.getByLabel('Email')).toHaveValue('intentionally-different', { timeout: 100 });
  await expect.soft(page.getByLabel('Password')).toHaveValue('intentionally-different', { timeout: 100 });
});
