"""Run API and real browser journeys against an already running dedicated stack.

Load generated credentials without putting them in argv/logs. This script never
starts/stops services and never removes databases. Browser accounts are synthetic.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

from dotenv import dotenv_values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--infra-env', type=Path, required=True)
    parser.add_argument('--browser-env', type=Path, help='Optional mode-600 local fixture file')
    args = parser.parse_args()
    infra = dotenv_values(args.infra_env)
    if infra.get('SANDBOX_EXECUTOR_TYPE') != 'gojudge':
        raise SystemExit('Full e2e requires the real gojudge executor')
    env = os.environ.copy()
    for key in ('BOOTSTRAP_SUPERUSER_EMAIL', 'BOOTSTRAP_SUPERUSER_PASSWORD'):
        if not infra.get(key):
            raise SystemExit(f'Missing {key} in infra env')
        env[key] = infra[key]
    env['BASE_URL'] = f"http://127.0.0.1:{infra.get('API_GATEWAY_PORT', '8081')}"
    os.environ.update(env)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.api.gateway import Gateway

    api = Gateway()
    suffix = secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    student_email = f'student-{suffix}@simulation.example.test'
    student = api.register(student_email, password, f'student_{suffix}')
    env.update(SIM_DEDICATED_STACK='1', SIM_BASE_URL=f"http://127.0.0.1:{infra.get('FRONTEND_PORT', '3000')}",
               SIM_ADMIN_EMAIL=env['BOOTSTRAP_SUPERUSER_EMAIL'],
               SIM_ADMIN_PASSWORD=env['BOOTSTRAP_SUPERUSER_PASSWORD'],
               SIM_STUDENT_EMAIL=student_email, SIM_STUDENT_PASSWORD=password)
    if args.browser_env:
        import shlex
        args.browser_env.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(args.browser_env, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as output:
            output.write('\n'.join(f'export {k}={shlex.quote(v)}' for k, v in env.items() if k.startswith('SIM_')) + '\n')
    results = []
    try:
        results.append(subprocess.run([sys.executable, '-m', 'pytest', '-m', 'e2e and not skip_ci', '--maxfail=5'], env=env).returncode)
        # Still gather both role journeys when an API scenario fails.
        results.append(subprocess.run(['npm', '--prefix', 'user-simulation', 'run', 'test:live'], env=env).returncode)
    finally:
        # Preserve requested local browser fixtures so another reviewer can inspect.
        if not args.browser_env:
            api.delete_user(student, student.user_id)
    from scripts.check_evidence import verify_evidence
    verify_evidence([Path('allure-results'), Path('user-simulation/artifacts/live-results'),
                     Path('user-simulation/artifacts/live-results.json')],
                    [password, env['BOOTSTRAP_SUPERUSER_PASSWORD'], student.token])
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('evidence_safe=true\n')
    return int(any(results))


if __name__ == '__main__':
    raise SystemExit(main())
