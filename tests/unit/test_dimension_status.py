"""Dimension-state helpers + the profile data-status computation."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from shared.dimension_state import (  # noqa: E402
    DimensionFreshness,
    envelope_for_error,
    envelope_for_items,
    rollup_state,
    worst_state,
)
from services.reconciliation.dimension_status import compute_data_status  # noqa: E402

NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


# ── dimension_state helpers ──────────────────────────────────────────────────


def test_worst_state_picks_worst():
    assert worst_state(["ready", "empty", "error"]) == "error"
    assert worst_state(["ready", "stale"]) == "stale"
    assert worst_state([]) == "ready"
    assert worst_state(["ready", "ready"]) == "ready"


def test_worst_state_ignores_unknown():
    assert worst_state(["ready", "bogus", "stale"]) == "stale"


def test_envelope_for_items_states():
    assert envelope_for_items("d", count=0).state == "empty"
    assert envelope_for_items("d", count=5).state == "ready"
    assert envelope_for_items("d", count=1, min_items=3).state == "insufficient_data"
    assert envelope_for_items("d", count=5, applicable=False).state == "not_applicable"
    stale = DimensionFreshness(is_stale=True)
    assert envelope_for_items("d", count=5, freshness=stale).state == "stale"


def test_envelope_for_error():
    env = envelope_for_error("d", message="boom")
    assert env.state == "error"
    assert env.reason_code == "computation_error"


def test_rollup_state():
    envs = [envelope_for_items("a", count=5), envelope_for_error("b")]
    assert rollup_state(envs) == "error"


# ── compute_data_status ──────────────────────────────────────────────────────


def _agg(**dimension_results):
    """Fake aggregator whose dimension methods return the given envelope dicts."""
    agg = MagicMock()
    for name in ("wallets", "sessions", "campaigns", "journeys", "financials", "relationships"):
        result = dimension_results.get(name, {"items": []})
        if isinstance(result, Exception):
            setattr(agg, name, AsyncMock(side_effect=result))
        else:
            setattr(agg, name, AsyncMock(return_value=result))
    return agg


async def test_data_status_all_empty_is_empty_overall():
    agg = _agg()
    result = await compute_data_status(agg, "ent", "tenant", now=NOW)
    assert result["overall_state"] == "empty"
    assert result["ready"] is False
    assert result["dimension_count"] == 6
    assert all(d["state"] == "empty" for d in result["dimensions"])


async def test_data_status_ready_when_fresh_items():
    fresh_ts = (NOW - timedelta(hours=1)).isoformat()
    agg = _agg(wallets={"items": [{"id": "w1", "linked_at": fresh_ts}]})
    result = await compute_data_status(agg, "ent", "tenant", now=NOW)
    wallets = next(d for d in result["dimensions"] if d["dimension"] == "wallets")
    assert wallets["state"] == "ready"
    assert wallets["count"] == 1
    assert wallets["freshness"]["is_stale"] is False


async def test_data_status_stale_when_old_items():
    old_ts = (NOW - timedelta(hours=48)).isoformat()
    agg = _agg(sessions={"items": [{"id": "s1", "occurred_at": old_ts}]})
    result = await compute_data_status(agg, "ent", "tenant", now=NOW)
    sessions = next(d for d in result["dimensions"] if d["dimension"] == "sessions")
    assert sessions["state"] == "stale"
    assert sessions["freshness"]["is_stale"] is True
    # A stale dimension drives overall worse than ready.
    assert result["overall_state"] == "stale"


async def test_data_status_dimension_failure_is_surfaced_not_fatal():
    agg = _agg(campaigns=RuntimeError("db down"))
    result = await compute_data_status(agg, "ent", "tenant", now=NOW)
    campaigns = next(d for d in result["dimensions"] if d["dimension"] == "campaigns")
    assert campaigns["state"] == "error"
    assert result["overall_state"] == "error"
    # Other dimensions still computed.
    assert len(result["dimensions"]) == 6
