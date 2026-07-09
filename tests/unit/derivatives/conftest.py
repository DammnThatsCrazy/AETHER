"""Shared fixtures for derivatives intelligence tests."""

from __future__ import annotations

import sys
from pathlib import Path

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
