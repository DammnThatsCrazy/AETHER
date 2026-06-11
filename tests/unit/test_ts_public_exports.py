from __future__ import annotations

from scripts import validate_ts_public_exports as ts_exports


def test_sdk_package_boundaries_validate_cleanly() -> None:
    errors = []
    for package_dir in ts_exports.PACKAGE_DIRS:
        errors.extend(ts_exports.validate_package(package_dir))
    assert errors == []
