"""Expectation registry + per-dimension reconciliation."""
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

from services.reconciliation.dimension_status import (  # noqa: E402
    compute_data_status,
    compute_reconciliation,
)
from services.reconciliation.expectations import (  # noqa: E402
    EXPECTATION_REGISTRY,
    get_expectation,
    registry_snapshot,
)

NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def _agg(**dimension_results):
    agg = MagicMock()
    for name in EXPECTATION_REGISTRY:
        result = dimension_results.get(name, {"items": []})
        if isinstance(result, Exception):
            setattr(agg, name, AsyncMock(side_effect=result))
        else:
            setattr(agg, name, AsyncMock(return_value=result))
    return agg


# ── registry ─────────────────────────────────────────────────────────────────


def test_registry_has_expected_dimensions():
    assert set(EXPECTATION_REGISTRY) == {
        "wallets", "sessions", "campaigns", "journeys", "financials", "relationships",
    }


def test_get_expectation_default_for_unknown():
    exp = get_expectation("nope")
    assert exp.dimension == "nope"
    assert exp.min_events == 1


def test_registry_snapshot_shape():
    snap = registry_snapshot()
    assert len(snap) == len(EXPECTATION_REGISTRY)
    row = next(r for r in snap if r["dimension"] == "journeys")
    assert row["freshness_sla_seconds"] > 0
    assert row["depends_on"] == ["sessions"]


# ── per-dimension SLA drives staleness ───────────────────────────────────────


def _item(ts: datetime) -> dict:
    return {"id": "x", "occurred_at": ts.isoformat()}


async def test_per_dimension_sla_wallets_vs_sessions():
    # 3 days old: fresh for wallets (7d SLA), stale for sessions (1d SLA).
    three_days = NOW - timedelta(days=3)
    agg = _agg(
        wallets={"items": [_item(three_days)]},
        sessions={"items": [_item(three_days)]},
    )
    result = await compute_data_status(agg, "ent", "tenant", now=NOW)
    by_dim = {d["dimension"]: d for d in result["dimensions"]}
    assert by_dim["wallets"]["state"] == "ready"
    assert by_dim["sessions"]["state"] == "stale"


# ── reconciliation expectation-vs-actual ─────────────────────────────────────


async def test_reconciliation_all_empty_is_unmet():
    result = await compute_reconciliation(_agg(), "ent", "tenant", now=NOW)
    assert result["met"] is False
    assert set(result["unmet_dimensions"]) == set(EXPECTATION_REGISTRY)
    row = next(r for r in result["dimensions"] if r["dimension"] == "wallets")
    assert row["met"] is False
    assert row["state"] == "empty"
    assert row["expected"]["freshness_sla_seconds"] == EXPECTATION_REGISTRY["wallets"].freshness_sla_seconds


async def test_reconciliation_fresh_dimension_is_met():
    fresh = NOW - timedelta(hours=1)
    agg = _agg(wallets={"items": [_item(fresh)]})
    result = await compute_reconciliation(agg, "ent", "tenant", now=NOW)
    wallets = next(r for r in result["dimensions"] if r["dimension"] == "wallets")
    assert wallets["met"] is True
    assert wallets["state"] == "ready"
    assert wallets["actual"]["count"] == 1
    assert "wallets" not in result["unmet_dimensions"]


async def test_reconciliation_failure_surfaced_as_unmet():
    agg = _agg(campaigns=RuntimeError("boom"))
    result = await compute_reconciliation(agg, "ent", "tenant", now=NOW)
    campaigns = next(r for r in result["dimensions"] if r["dimension"] == "campaigns")
    assert campaigns["state"] == "error"
    assert campaigns["met"] is False
    assert result["overall_state"] == "error"
