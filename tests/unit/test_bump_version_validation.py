import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "bump_version", Path(__file__).resolve().parents[2] / "scripts" / "bump_version.py"
)
bump_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bump_version)


@pytest.mark.parametrize(
    "version",
    ["0.1.0", "0.1.0-alpha.0", "0.5.0-beta.12", "1.0.0-rc.0", "1.0.0", "0.1.0-alpha.0a", "0.1.0-0"],
)
def test_accepts_valid_semver(version):
    assert bump_version.is_valid_version(version)


@pytest.mark.parametrize(
    "version",
    ["0.1.0-alpha.01", "0.1.0-01", "01.1.0", "0.1", "0.1.0-", "0.1.0-alpha..1", "0.1.0+build", "v0.1.0"],
)
def test_rejects_invalid_semver(version):
    assert not bump_version.is_valid_version(version)


def test_check_flags_version_file_mismatch(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(bump_version, "ROOT", tmp_path)
    monkeypatch.setattr(bump_version, "read_current_version", lambda: "0.1.0-alpha.0")
    monkeypatch.setattr(bump_version, "PACKAGE_JSONS", [])
    monkeypatch.setattr(bump_version, "DOC_HEADERS", [])
    monkeypatch.setattr(bump_version, "README_HEADERS", [])
    assert bump_version.check_version_alignment() == 1
