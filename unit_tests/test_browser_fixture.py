from pathlib import Path

from scripts.run_e2e import write_private_fixture


def test_replaces_existing_readable_fixture_with_private_file(tmp_path: Path):
    target = tmp_path / 'browser.env'
    target.write_text('old')
    target.chmod(0o644)
    write_private_fixture(target, 'synthetic-password')
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_text() == 'synthetic-password'


def test_replaces_symlink_without_writing_to_its_target(tmp_path: Path):
    original = tmp_path / 'existing'
    original.write_text('untouched')
    target = tmp_path / 'browser.env'
    target.symlink_to(original)
    write_private_fixture(target, 'synthetic-password')
    assert original.read_text() == 'untouched'
    assert not target.is_symlink()
    assert target.stat().st_mode & 0o777 == 0o600
