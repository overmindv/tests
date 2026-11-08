import hashlib
import io
import json
import tarfile

import pytest

from scripts.extract_private_source import extract


def source(tmp_path, filename='README.md'):
    archive = tmp_path / 'sandbox.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        data = b'sandbox source\n'
        member = tarfile.TarInfo(filename)
        member.size = len(data)
        bundle.addfile(member, io.BytesIO(data))
    manifest = tmp_path / 'sandbox-source.json'
    manifest.write_text(json.dumps({'repository': 'overmindv/sandbox', 'commit': 'a' * 40,
                                    'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}))
    return archive, manifest


def test_verified_archive_extracts_source(tmp_path):
    archive, manifest = source(tmp_path)
    extract(archive, manifest, 'a' * 40, tmp_path / 'output')
    assert (tmp_path / 'output/README.md').read_text() == 'sandbox source\n'


def test_archive_commit_and_bytes_must_match(tmp_path):
    archive, manifest = source(tmp_path)
    with pytest.raises(ValueError, match='commit'):
        extract(archive, manifest, 'b' * 40, tmp_path / 'output')
    archive.write_bytes(archive.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='checksum'):
        extract(archive, manifest, 'a' * 40, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_archive_cannot_escape_destination(tmp_path):
    archive, manifest = source(tmp_path, '../outside.txt')
    with pytest.raises(tarfile.FilterError):
        extract(archive, manifest, 'a' * 40, tmp_path / 'output')
    assert not (tmp_path / 'outside.txt').exists()
