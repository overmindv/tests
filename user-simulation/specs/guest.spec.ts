import { test, expect, capture, expectNoHorizontalOverflow, openNavigation } from '../support/ui';

// Явная fault fixture: настоящий frontend, GraphQL недоступен. Это не API e2e.
test.beforeEach(async ({ page }) => {
  await page.route('**/graphql', route => route.abort('connectionrefused'));
});

test('@smoke студент: находит задачи через меню и сбрасывает ошибочные фильтры', async ({ page }, testInfo) => {
  await test.step('Цель: найти практику с главной страницы', async () => {
    await page.goto('/');
    await openNavigation(page);
    await page.getByRole('navigation', { name: 'Основная навигация' }).getByRole('link', { name: 'Задачи', exact: true }).click();
    await expect(page).toHaveURL(/\/tasks$/);
    await expect(page.getByRole('heading', { name: 'Задачи', exact: true })).toBeVisible();
  });
  await test.step('Ошибка: слишком узкий фильтр; восстановление: сбросить', async () => {
    await page.getByRole('combobox', { name: 'Формат' }).selectOption('programming');
    await page.getByRole('combobox', { name: 'Сложность' }).selectOption('hard');
    await page.getByRole('textbox', { name: 'Поиск задач' }).fill('несуществующая задача');
    await page.getByRole('button', { name: 'Сбросить' }).click();
    await expect(page.getByRole('combobox', { name: 'Формат' })).toHaveValue('');
    await expect(page.getByRole('combobox', { name: 'Сложность' })).toHaveValue('');
    await expect(page.getByRole('textbox', { name: 'Поиск задач' })).toHaveValue('');
    // Task results and topic options fail independently; check the task's own recovery block.
    const retryTasks = page.getByRole('button', { name: 'Повторить', exact: true });
    const taskError = page.locator('.content-state').filter({ has: retryTasks }).getByRole('alert');
    await expect(taskError).toContainText('Попробуйте ещё раз');
    await expect(page.getByRole('button', { name: 'Повторить загрузку тем', exact: true })).toBeVisible();
    await retryTasks.click();
    await expect(taskError).toContainText('Попробуйте ещё раз');
    await expect(retryTasks).toBeEnabled();
    await expectNoHorizontalOverflow(page);
    await capture(page, testInfo, 'tasks-unavailable');
  });
});

for (const [persona, route] of [['студент', '/history'], ['автор', '/admin/tasks'], ['модератор', '/admin/collected-tasks']]) {
  test(`@smoke ${persona}: защищённый адрес ${route} предлагает вход`, async ({ page }, testInfo) => {
    await page.goto(route);
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: 'Вход в аккаунт' })).toBeVisible();
    await expect(page.getByLabel('Электронная почта')).toBeEditable();
    await expectNoHorizontalOverflow(page);
    await capture(page, testInfo, 'authentication-required');
  });
}

test('@smoke обе роли: исправляют email после ошибки и могут повторить вход', async ({ page }, testInfo) => {
  await page.goto('/login');
  const email = page.getByLabel('Электронная почта');
  await email.fill('не-email');
  await page.getByLabel('Пароль', { exact: true }).fill('Synthetic-Only-Password1!');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(email).toBeFocused();
  expect(await email.evaluate((input: HTMLInputElement) => input.validity.typeMismatch)).toBe(true);
  await expect(page).toHaveURL(/\/login$/);
  await email.fill('simulation@example.invalid');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Попробуйте ещё раз');
  await expect(page.getByRole('button', { name: 'Войти', exact: true })).toBeEnabled();
  await expect(email).toHaveValue('simulation@example.invalid');
  await expect(page.getByLabel('Пароль', { exact: true })).toBeEditable();
  await expectNoHorizontalOverflow(page);
  await capture(page, testInfo, 'login-recoverable-error');
  await page.getByRole('link', { name: 'Зарегистрироваться' }).click();
  await expect(page.getByRole('heading', { name: 'Регистрация' })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, testInfo, 'registration-layout');
});
