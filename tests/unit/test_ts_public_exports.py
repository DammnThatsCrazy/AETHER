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


def _make_pkg(tmp: str, manifest: dict, *, dist_dts_only: bool = False, dist_full: bool = False) -> Path:
    pkg_dir = Path(tmp)
    (pkg_dir / "index.ts").write_text("export {};\n")
    (pkg_dir / "package.json").write_text(json.dumps(manifest))
    if dist_dts_only or dist_full:
        dist = pkg_dir / "dist"
        dist.mkdir()
        (dist / "index.d.ts").write_text("export {};\n")
    if dist_full:
        (pkg_dir / "dist" / "index.cjs.js").write_text("module.exports = {};\n")
    return pkg_dir


_DIST_MANIFEST = {
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


def test_validator_skips_dist_path_checks_when_dist_absent() -> None:
    """No dist/ at all → skip all dist-path checks (shared, react-native case)."""
    with tempfile.TemporaryDirectory(dir=ts_exports.ROOT) as tmp:
        pkg_dir = _make_pkg(tmp, _DIST_MANIFEST)
        assert not (pkg_dir / "dist").exists()
        errors = ts_exports.validate_package(pkg_dir)
<<<<<<< HEAD
        assert errors == [], (
            "validator should not report missing-dist errors when dist/ is absent: "
            + str(errors)
        )


def test_validator_skips_dist_js_checks_when_only_declarations_committed() -> None:
    """Dist-path JS checks are skipped when dist/ has only .d.ts files.

    packages/web/dist/*.d.ts are committed to git so reviewers can inspect
    types without running a build. In CI the JS build artifacts (*.js) are
    absent because rollup hasn't run. The validator must treat a declaration-only
    dist/ the same as no dist/ for JS-file presence checks.
    """
    with tempfile.TemporaryDirectory(dir=ts_exports.ROOT) as tmp:
        pkg_dir = Path(tmp)
        (pkg_dir / "index.ts").write_text("export {};\n")
        dist = pkg_dir / "dist"
        dist.mkdir()
        # Only a .d.ts file present — no .js build artifacts
        (dist / "index.d.ts").write_text("export {};\n")
        manifest = {
            "name": "@aether/test-pkg-decl-only",
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

        errors = ts_exports.validate_package(pkg_dir)
        assert errors == [], (
            "validator should not report missing-JS errors when dist/ has only .d.ts: "
            + str(errors)
        )
=======
        assert errors == [], f"unexpected errors when dist/ absent: {errors}"


def test_validator_skips_dist_path_checks_when_dist_has_only_dts() -> None:
    """dist/ exists with only .d.ts (web pre-build case) → skip .js path checks."""
    with tempfile.TemporaryDirectory(dir=ts_exports.ROOT) as tmp:
        pkg_dir = _make_pkg(tmp, _DIST_MANIFEST, dist_dts_only=True)
        assert (pkg_dir / "dist" / "index.d.ts").exists()
        assert not any((pkg_dir / "dist").rglob("*.js"))
        errors = ts_exports.validate_package(pkg_dir)
        assert errors == [], f"unexpected errors when dist/ has only .d.ts: {errors}"


def test_validator_checks_dist_paths_when_dist_is_fully_built() -> None:
    """dist/ with .js files → all path checks run (catches stale export maps)."""
    with tempfile.TemporaryDirectory(dir=ts_exports.ROOT) as tmp:
        pkg_dir = _make_pkg(tmp, _DIST_MANIFEST, dist_full=True)
        errors = ts_exports.validate_package(pkg_dir)
        # module and esm exports reference files not created → expect errors
        missing = [e for e in errors if "missing file" in e]
        assert missing, "validator should report missing built artifacts when dist/ has .js files"
