"""Save bounded, scrubbed Compose diagnostics without printing raw service logs."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_evidence import verify_evidence

_JWT = re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}')


def sanitize(text: str, secrets: list[str]) -> str:
    import json
    from urllib.parse import quote

    variants = {variant for value in secrets if value for variant in
                (value, quote(value, safe=''), json.dumps(value)[1:-1])}
    for value in sorted(variants, key=len, reverse=True):
        text = text.replace(value, '[REDACTED]')
    return _JWT.sub('[REDACTED]', text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--infra-env', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    env_file = args.infra_env.resolve()
    secrets = [value for key, value in dotenv_values(env_file).items()
               if value and any(part in key.upper() for part in ('PASSWORD', 'SECRET', 'TOKEN'))]
    chunks = []
    for arguments in (['ps', '--all'], ['logs', '--no-color', '--tail', '100']):
        command = ['docker', 'compose', '--env-file', str(env_file), '--profile', 'sandbox', '--profile', 'gojudge', *arguments]
        result = subprocess.run(command, cwd=env_file.parent, text=True, capture_output=True, timeout=45)
        chunks.append(f"Command {' '.join(arguments)}; exit {result.returncode}\n" + result.stdout + result.stderr)
    cleaned = sanitize('\n'.join(chunks), secrets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(cleaned)
    verify_evidence([args.output], secrets)
    print('Saved sanitized bounded service diagnostics')


if __name__ == '__main__':
    main()
