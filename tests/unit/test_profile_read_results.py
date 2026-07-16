"""Typed Profile360 dependency availability tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from services.profile.aggregator import _safe
from services.profile.read_result import DimensionReadResult


async def _returns_empty():
    return []


async def _fails():
    raise RuntimeError("dependency down")


@pytest.mark.asyncio
async def test_legitimate_empty_is_available():
    result = await _safe("wallets", _returns_empty())

    assert isinstance(result, DimensionReadResult)
    assert result.status == "available"
    assert result.value == []
    assert result.error_code is None


@pytest.mark.asyncio
async def test_dependency_failure_is_not_indistinguishable_from_empty():
    result = await _safe("wallets", _fails())

    assert result.status == "unavailable"
    assert result.value is None
    assert result.error_code == "RuntimeError"
    assert result.value_or([]) == []
