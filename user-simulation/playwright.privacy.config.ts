import { defineConfig } from '@playwright/test';
import config from './playwright.config';

export default defineConfig(config, {
  testDir: './privacy',
  testMatch: '**/*.probe.ts',
  outputDir: './artifacts/privacy/results',
  reporter: [['./support/live-reporter.ts', { outputFile: './artifacts/privacy/report.json' }]],
  webServer: undefined,
});
