import { defineConfig, devices } from '@playwright/test';

// Встроенный переключатель закреплённой версии Playwright: не собирать DOM/ARIA
// с заполненными паролями для error-context.md, даже при trace: off.
process.env.PLAYWRIGHT_NO_COPY_PROMPT = '1';

const live = process.env.SIM_LIVE === '1';
const startFrontend = process.env.SIM_START_FRONTEND === '1';
const baseURL = process.env.SIM_BASE_URL ?? 'http://127.0.0.1:5174';

export default defineConfig({
  testDir: './specs',
  outputDir: live ? './artifacts/live-results' : './artifacts/results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  forbidOnly: Boolean(process.env.CI),
  reporter: live ? [['./support/live-reporter.ts']] : [
    ['list'],
    ['html', { outputFolder: './artifacts/report', open: 'never' }],
    ['json', { outputFile: './artifacts/results.json' }],
  ],
  use: {
    baseURL,
    actionTimeout: 15_000,
    locale: 'ru-RU',
    timezoneId: 'Europe/Madrid',
    colorScheme: 'light',
    // Сетевые трассы/видео могут сохранить cookie, пароль и тела запросов.
    trace: 'off',
    video: 'off',
    screenshot: 'off',
  },
  projects: [
    { name: 'laptop-chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 900 } } },
    { name: 'phone-chromium', use: { ...devices['Pixel 7'], defaultBrowserType: 'chromium' } },
  ],
  webServer: startFrontend ? {
    command: 'npm --prefix ../../frontend run dev -- --host 127.0.0.1 --port 5174 --strictPort',
    url: 'http://127.0.0.1:5174',
    reuseExistingServer: false,
    timeout: 30_000,
    stdout: 'ignore',
    stderr: 'ignore',
  } : undefined,
});
