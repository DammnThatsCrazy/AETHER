"""Shared fixtures for Agent Access Intelligence capability-catalog tests (PR 2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = str(Path(__file__).parents[3] / "Backend Architecture" / "aether-backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


@pytest.fixture(autouse=True)
def _reset_stores():
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    yield
    reset_in_memory_stores()
