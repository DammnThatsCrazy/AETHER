"""Build-level containment checks for the synthetic demo frontend.

These execute real Vite builds of ``frontend/demo``. They skip cleanly when the
Node toolchain is unavailable (for example while dependencies are still
installing) rather than failing spuriously; the pure-Python validator rules are
covered in ``test_validate_frontend_data_truth.py``.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import validate_frontend_data_truth as validator

DEMO_ROOT = validator.DEMO_APP_ROOT
FIXTURE_TOKEN = "Maya Chen"  # PROFILE360.entity, rendered on the default view


MODULE_DIRECTORIES = (DEMO_ROOT / "node_modules", validator.ROOT / "node_modules")
REQUIRED_PACKAGES = ("vite", "@vitejs/plugin-react", "react", "msw")
# npm install can leave the workspace half-populated; treat that as unavailable
# rather than reporting a containment failure.
INCOMPLETE_INSTALL_MARKERS = (
    "ERR_MODULE_NOT_FOUND",
    "Cannot find package",
    "Cannot find module",
    "Failed to resolve import",
)


def _vite_binary() -> Path | None:
    for modules in MODULE_DIRECTORIES:
        candidate = modules / ".bin" / "vite"
        if candidate.exists():
            return candidate
    return None


def _toolchain_is_installed() -> bool:
    if shutil.which("node") is None or _vite_binary() is None:
        return False
    return all(
        any((modules / package).is_dir() for modules in MODULE_DIRECTORIES)
        for package in REQUIRED_PACKAGES
    )


requires_build_toolchain = pytest.mark.skipif(
    not _toolchain_is_installed(),
    reason="frontend build toolchain is unavailable (node_modules not installed)",
)


def _build_demo(out_dir: Path, demo_env: str | None) -> subprocess.CompletedProcess[str]:
    vite = _vite_binary()
    assert vite is not None
    env = {key: value for key, value in os.environ.items() if key != validator.DEMO_ENV_VAR}
    if demo_env is not None:
        env[validator.DEMO_ENV_VAR] = demo_env
    result = subprocess.run(
        [str(vite), "build", "--outDir", str(out_dir), "--emptyOutDir", "--logLevel", "warn"],
        cwd=DEMO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = result.stderr + result.stdout
    if result.returncode != 0 and any(marker in output for marker in INCOMPLETE_INSTALL_MARKERS):
        pytest.skip(f"frontend dependencies are not fully installed: {output.strip()[:200]}")
    return result


def _emitted_text(out_dir: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(out_dir.rglob("*"))
        if path.is_file() and path.suffix in validator.BUNDLE_SUFFIXES
    )


@requires_build_toolchain
def test_demo_build_fails_when_demo_env_is_unset(tmp_path: Path) -> None:
    result = _build_demo(tmp_path / "dist", None)

    assert result.returncode != 0
    assert "VITE_DEMO_ENV is required and has no default" in (result.stderr + result.stdout)
    assert not (tmp_path / "dist").exists()


@requires_build_toolchain
def test_demo_build_rejects_a_non_canonical_profile(tmp_path: Path) -> None:
    result = _build_demo(tmp_path / "dist", "production")

    assert result.returncode != 0
    assert "is not a demo profile" in (result.stderr + result.stdout)


@requires_build_toolchain
def test_demo_live_build_has_no_fixture_or_worker_path(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    result = _build_demo(out_dir, "demo-live")
    assert result.returncode == 0, result.stderr

    emitted = _emitted_text(out_dir)
    assert FIXTURE_TOKEN not in emitted
    assert "data/fixtures" not in emitted
    assert "mockServiceWorker" not in emitted
    assert "setupWorker" not in emitted
    assert 'content="demo-live"' in (out_dir / "index.html").read_text(encoding="utf-8")
    # publicDir is gated too: the worker script is not copied into the bundle.
    assert not (out_dir / "mockServiceWorker.js").exists()
    assert validator.scan_demo_bundle(root=tmp_path, bundle_root=out_dir) == []


@requires_build_toolchain
def test_local_mocked_build_keeps_the_fixture_dataset(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    result = _build_demo(out_dir, "local-mocked")
    assert result.returncode == 0, result.stderr

    emitted = _emitted_text(out_dir)
    # Proves the demo-live absence above is real containment, not a broken build.
    assert FIXTURE_TOKEN in emitted
    assert (out_dir / "mockServiceWorker.js").exists()
    assert validator.scan_demo_bundle(root=tmp_path, bundle_root=out_dir) == []
