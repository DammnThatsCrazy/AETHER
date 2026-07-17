"""Path setup + shared fixtures for comparison-engine unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from comparison_fakes import FakeAnalytics  # noqa: E402


@pytest.fixture()
def fake_analytics() -> FakeAnalytics:
    return FakeAnalytics()


@pytest.fixture(autouse=True)
def _clean_stores():
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    yield
    reset_in_memory_stores()
