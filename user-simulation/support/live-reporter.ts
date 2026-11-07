import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { redactSecrets } from './redact';
import type { Reporter, TestCase, TestResult, FullResult } from '@playwright/test/reporter';

// Не сохраняем API steps (fill содержит пароль) и сетевые данные в live-отчёт.
export default class LiveReporter implements Reporter {
  private results: object[] = [];
  constructor(private options: { outputFile?: string } = {}) {}
  onTestEnd(test: TestCase, result: TestResult) {
    const title = test.titlePath().filter(Boolean).join(' › ');
    const errors = result.errors.map(error => redactSecrets(error.message ?? 'Ошибка без сообщения'));
    this.results.push({ title, status: result.status, durationMs: result.duration, errors,
      screenshots: result.attachments.filter(item => item.contentType === 'image/png').map(item => item.path) });
    console.log(`${result.status}: ${title}`);
    for (const error of errors) console.log(error);
  }
  onError(error: { message?: string }) {
    console.error(redactSecrets(error.message ?? 'Ошибка runner'));
  }
  onEnd(result: FullResult) {
    const outputFile = this.options.outputFile ?? 'artifacts/live-results.json';
    mkdirSync(dirname(outputFile), { recursive: true });
    writeFileSync(outputFile, JSON.stringify({ status: result.status, tests: this.results }, null, 2));
  }
}
