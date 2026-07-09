"""Shared fixtures for stablecoin intelligence tests."""

from __future__ import annotations

import sys
from pathlib import Path

from uuid import uuid4

import pytest

BACKEND = str(Path(__file__).parents[3] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


@pytest.fixture(autouse=True)
def _reset_typed_stores():
    from repositories.typed_repo import reset_typed_in_memory_stores

    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


@pytest.fixture(autouse=True)
def _fresh_tenants(request, monkeypatch):
    """Unique tenant ids per test.

    Some suites in the full run reload backend modules (sys.modules
    surgery in contract tests), which can leave stale module instances
    holding old in-memory stores that the reset above cannot reach.
    Unique tenants make every test independent of any leaked state.
    """
    unique = uuid4().hex[:8]
    for name in ("TENANT", "OTHER_TENANT"):
        if hasattr(request.module, name):
            monkeypatch.setattr(request.module, name, f"{getattr(request.module, name)}-{unique}")
