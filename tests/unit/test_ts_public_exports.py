from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scripts import validate_ts_public_exports as ts_exports


def test_sdk_package_boundaries_validate_cleanly() -> None:
    errors = []
    for package_dir in ts_exports.PACKAGE_DIRS:
        errors.extend(ts_exports.validate_package(package_dir))
    assert errors == []


def test_validator_skips_dist_path_checks_when_dist_not_built() -> None:
    """Dist-path existence checks are skipped when dist/ hasn't been built yet.

    In CI jobs that don't run npm build (python-tests, lint-docs), dist/ is
    absent for packages that gitignore it. The validator must not report false
    positives in those environments.
    """
    with tempfile.TemporaryDirectory(dir=ts_exports.ROOT) as tmp:
        pkg_dir = Path(tmp)
        # Source barrel exists
        (pkg_dir / "index.ts").write_text("export {};\n")
        # package.json with dist-path references (no dist/ present)
        manifest = {
            "name": "@aether/test-pkg",
            "version": "1.0.0",
            "types": "./dist/index.d.ts",
            "main": "./dist/index.cjs.js",
            "module": "./dist/index.esm.js",
            "exports": {
                ".": {
                    "types": "./dist/index.d.ts",
                    "import": "./dist/index.esm.js",
                    "require": "./dist/index.cjs.js",
                }
            },
        }
        (pkg_dir / "package.json").write_text(json.dumps(manifest))
        # dist/ does NOT exist — simulates a pre-build or python-tests CI environment
        assert not (pkg_dir / "dist").exists()

        errors = ts_exports.validate_package(pkg_dir)
        assert errors == [], (
            "validator should not report missing-dist errors when dist/ is absent: "
            + str(errors)
        )
