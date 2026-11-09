import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = join(root, 'artifacts/privacy');
const email = `canary-${randomUUID()}@example.invalid`;
const password = `Canary-${randomUUID()}-Secret!` + '"\\';
// Удаляется только каталог предыдущего синтетического прогона, до запуска.
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
const result = spawnSync(process.execPath, [
  'node_modules/@playwright/test/cli.js', 'test', '--config=playwright.privacy.config.ts',
], {
  cwd: root,
  env: { ...process.env, SIM_LIVE: '1', SIM_START_FRONTEND: '0', SIM_ADMIN_EMAIL: email, SIM_ADMIN_PASSWORD: password },
  encoding: 'utf8',
  timeout: 60_000,
});
writeFileSync(join(output, 'runner.log'), `${result.stdout ?? ''}\n${result.stderr ?? ''}`);
function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(item => {
    const path = join(directory, item.name);
    return item.isDirectory() ? files(path) : [path];
  });
}
const artifacts = files(output);
if (artifacts.some(path => /\.(zip|har|webm)$/.test(path))) throw new Error('Unexpected unredacted trace/network/video artifact');
const leaks = artifacts.filter(path => {
  const bytes = readFileSync(path);
  return [email, password].flatMap(secret => [secret, JSON.stringify(secret).slice(1, -1), encodeURIComponent(secret)])
    .some(secret => bytes.includes(Buffer.from(secret)));
});
if (leaks.length) {
  console.error(`Privacy canary FAILED: synthetic secret found in ${leaks.map(path => path.slice(root.length + 1)).join(', ')}`);
  process.exit(1);
}
const report = JSON.parse(readFileSync(join(output, 'report.json'), 'utf8'));
if (result.status !== 1 || report.tests.length !== 4 || report.tests.some(test => test.status !== 'failed')) {
  throw new Error('Privacy probe did not execute exactly four intentional browser failures');
}
if (!artifacts.some(path => path.endsWith('.png'))) throw new Error('Failure screenshot path was not exercised');
console.log(`Privacy canary passed: 4 intentional failures (2 cases × 2 devices), ${artifacts.length} artifact files scanned, no synthetic credentials found`);
