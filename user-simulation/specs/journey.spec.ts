import { randomUUID } from 'node:crypto';
import { test, expect, capture, expectNoHorizontalOverflow, signIn } from '../support/ui';
import type { Page } from '@playwright/test';

const required = ['SIM_ADMIN_EMAIL', 'SIM_ADMIN_PASSWORD', 'SIM_STUDENT_EMAIL', 'SIM_STUDENT_PASSWORD'];

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Меню профиля' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Меню профиля' })).toHaveCount(0);
}

test('@live автор публикует тест; студент исправляет ответ и возвращается к истории', async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  expect(process.env.SIM_LIVE, 'Запускайте через npm run test:live с безопасным репортером').toBe('1');
  expect(process.env.SIM_DEDICATED_STACK, 'Подтвердите выделенный тестовый стек: SIM_DEDICATED_STACK=1').toBe('1');
  for (const key of required) expect(Boolean(process.env[key]), `Требуется ${key}`).toBe(true);
  expect(process.env.SIM_ADMIN_EMAIL !== process.env.SIM_STUDENT_EMAIL, 'Нужны два разных тестовых аккаунта').toBe(true);

  const title = `User simulation ${testInfo.project.name} ${randomUUID().slice(0, 8)}`;
  let taskId: string | undefined;
  try {
    await test.step('Автор: дублирует вариант, исправляет ошибку, сохраняет черновик', async () => {
      await signIn(page, process.env.SIM_ADMIN_EMAIL!, process.env.SIM_ADMIN_PASSWORD!);
      await page.goto('/admin/tasks/new');
      await expect(page.getByRole('heading', { name: 'Создание теста' })).toBeVisible();
      await page.getByLabel('Название', { exact: true }).fill(title);
      await page.getByLabel('Условие', { exact: true }).fill('Сколько будет 2 + 2? Выберите один ответ.');
      await page.getByRole('textbox', { name: 'Вариант 1', exact: true }).fill('4');
      await page.getByRole('textbox', { name: 'Вариант 2', exact: true }).fill('4');
      await page.getByRole('button', { name: 'Создать черновик' }).click();
      await expect(page.getByRole('alert')).toBeVisible();
      await expect(page).toHaveURL(/\/admin\/tasks\/new$/);
      await expectNoHorizontalOverflow(page);
      await capture(page, testInfo, 'author-duplicate-option');
      await page.getByRole('textbox', { name: 'Вариант 2', exact: true }).fill('5');
      await page.getByRole('button', { name: 'Создать черновик' }).click();
      await expect(page).toHaveURL(/\/admin\/tasks\/[0-9a-f-]{36}$/);
      taskId = new URL(page.url()).pathname.split('/').at(-1);
      await expect(page.getByRole('heading', { name: 'Новая версия теста' })).toBeVisible();
    });
    await test.step('Автор: публикует созданный черновик', async () => {
      await page.goto('/admin/tasks');
      const row = page.getByRole('article').filter({ hasText: title });
      await expect(row).toContainText('Черновик');
      await row.getByRole('button', { name: 'Опубликовать', exact: true }).click();
      await expect(row).toContainText('Опубликован');
      await expectNoHorizontalOverflow(page);
      await capture(page, testInfo, 'author-published');
      await signOut(page);
      await signIn(page, process.env.SIM_STUDENT_EMAIL!, process.env.SIM_STUDENT_PASSWORD!);
    });
    await test.step('Студент: не получает доступ к редактору автора', async () => {
      await page.goto('/admin/tasks/new');
      await expect(page.getByRole('alert')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Создать черновик' })).toHaveCount(0);
    });
    await test.step('Студент: ошибается, меняет ответ и получает сохранённый результат', async () => {
      await page.goto(`/tasks/${taskId}`);
      await expect(page.getByRole('heading', { name: title })).toBeVisible();
      await expect(page.getByRole('button', { name: 'Проверить ответ', exact: true })).toBeDisabled();
      await page.getByRole('radio', { name: /5$/ }).check();
      await page.getByRole('button', { name: 'Проверить ответ', exact: true }).click();
      await expect(page.getByRole('status').filter({ hasText: 'Пока не сходится' })).toBeVisible();
      await capture(page, testInfo, 'student-wrong-answer');
      await page.getByRole('radio', { name: /4$/ }).check();
      await page.getByRole('button', { name: 'Проверить ответ', exact: true }).click();
      await expect(page.getByRole('status').filter({ hasText: 'Ответ принят' })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await capture(page, testInfo, 'student-correct-answer');
    });
    await test.step('Студент: после перезагрузки открывает обе попытки именно этой задачи', async () => {
      await page.goto('/history');
      await page.reload();
      await expect(page.getByRole('heading', { name: 'История попыток' })).toBeVisible();
      const attempts = page.getByRole('article');
      await expect(attempts.nth(0)).toContainText('Ответ принят');
      await expect(attempts.nth(1)).toContainText('Неверный ответ');
      await expectNoHorizontalOverflow(page);
      await capture(page, testInfo, 'student-history');
      const detailURLs = await attempts.getByRole('link', { name: 'Результат →' }).evaluateAll(links => links.slice(0, 2).map(link => (link as HTMLAnchorElement).href));
      expect(detailURLs).toHaveLength(2);
      for (const [index, url] of detailURLs.entries()) {
        await page.goto(url);
        await expect(page.getByRole('heading', { name: index === 0 ? 'Ответ принят' : 'Неверный ответ' })).toBeVisible();
        await expect(page.getByRole('link', { name: 'Открыть актуальную задачу' })).toHaveAttribute('href', `/tasks/${taskId}`);
      }
    });
  } catch (error) {
    await capture(page, testInfo, 'journey-failure-before-cleanup');
    throw error;
  } finally {
    if (taskId) {
      await test.step('Очистка: автор удаляет только созданную этим прогоном задачу', async () => {
        if (await page.getByRole('button', { name: 'Меню профиля' }).isVisible()) await signOut(page);
        await signIn(page, process.env.SIM_ADMIN_EMAIL!, process.env.SIM_ADMIN_PASSWORD!);
        await page.goto('/admin/tasks');
        const row = page.getByRole('article').filter({ hasText: title });
        await expect(row).toHaveCount(1);
        page.once('dialog', dialog => dialog.accept());
        await row.getByRole('button', { name: 'Удалить', exact: true }).click();
        await expect(row).toHaveCount(0);
      });
    }
  }
});
