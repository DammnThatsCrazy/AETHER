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
