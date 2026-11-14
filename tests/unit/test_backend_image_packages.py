"""The backend image must contain every runtime package of services/api.

services/api/Dockerfile copies an explicit list of backend packages. When
services/api/services/ (social360) was missing from it, every staging image
crashed at boot with ModuleNotFoundError: No module named 'services.social360'
(rehearsal delivery run 43351669282), although every source-tree test passed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "services/api"
DOCKERFILE = BACKEND / "Dockerfile"
# Source-tree directories that are not imported at runtime.
NOT_RUNTIME = {"tests", "docs", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"}


def _copied_backend_dirs() -> set[str]:
    text = DOCKERFILE.read_text(encoding="utf-8")
    return set(re.findall(r'COPY \["services/api/([A-Za-z0-9_]+)/"', text))


def _runtime_packages() -> set[str]:
    return {
        path.name
        for path in BACKEND.iterdir()
        if path.is_dir() and path.name not in NOT_RUNTIME and not path.name.startswith(".")
        and any(path.rglob("*.py"))
    }


def test_every_runtime_backend_package_is_copied_into_the_image() -> None:
    missing = sorted(_runtime_packages() - _copied_backend_dirs())
    assert not missing, f"services/api/Dockerfile does not COPY runtime package(s): {missing}"


def test_main_module_and_migrations_are_copied() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'COPY ["services/api/main.py", "./services/api/main.py"]' in text
    assert "services/api/alembic/" in text
