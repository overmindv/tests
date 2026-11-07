import type { TestInfoError } from '@playwright/test';

export function redactSecrets(value: string) {
  for (const key of ['SIM_ADMIN_EMAIL', 'SIM_ADMIN_PASSWORD', 'SIM_STUDENT_EMAIL', 'SIM_STUDENT_PASSWORD']) {
    const secret = process.env[key];
    if (!secret) continue;
    for (const representation of [secret, JSON.stringify(secret).slice(1, -1), encodeURIComponent(secret)]) {
      value = value.split(representation).join('[REDACTED]');
    }
  }
  return value;
}

// Ошибки обрабатываются до встроенного teardown, который пишет error-context.md.
export function redactTestError(error: TestInfoError) {
  for (const field of ['message', 'stack', 'value', 'errorContext'] as const) {
    if (error[field]) error[field] = redactSecrets(error[field]);
  }
  if (error.cause) redactTestError(error.cause);
}
