"""Verify and safely extract a committed private source snapshot for CI."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


def extract(archive: Path, manifest: Path, expected_ref: str, destination: Path) -> None:
    provenance = json.loads(manifest.read_text())
    if provenance.get('repository') not in {'overmindv/sandbox', 'https://github.com/overmindv/sandbox'}:
        raise ValueError('Unexpected source repository')
    if provenance.get('commit') != expected_ref:
        raise ValueError('Source commit does not match the pinned service ref')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != provenance.get('sha256'):
        raise ValueError('Source archive checksum mismatch')
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, 'r:gz') as source:
        source.extractall(destination, filter='data')
    print(f'Extracted verified sandbox source at {expected_ref}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--expected-ref', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    extract(args.archive, args.manifest, args.expected_ref, args.destination)
