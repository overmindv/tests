"""Refuse publication when generated evidence contains credentials."""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import quote

_JWT = re.compile(rb'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}')


def verify_evidence(paths: list[Path], secrets: list[str]) -> None:
    needles = {variant.encode() for value in secrets if value for variant in
               (value, quote(value, safe=''), json.dumps(value)[1:-1])}
    for root in paths:
        for path in root.rglob('*') if root.is_dir() else [root]:
            if not path.is_file():
                continue
            data = path.read_bytes()
            if _JWT.search(data) or any(needle in data for needle in needles):
                raise RuntimeError(f'Evidence privacy check failed: {path.name}; artifact upload is disabled')
