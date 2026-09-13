"""Stablecoin price write-path tests (agent 1E).

Proves:
  * price-observation persistence through the connector path;
  * multi-provider price disagreement produces a durable ``conflict``
    reconciliation record, and re-reconciling the same snapshot set produces the
    ``duplicate`` state (idempotent — no second conflict row).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinReconciliationRepository
from services.stablecoins.price_feed import (
    CONFLICT_STATE,
    StablecoinPriceObservation,
)
from services.stablecoins.price_persistence import (
    STATE_DUPLICATE,
    StablecoinPriceReconciler,
    persist_price_observation,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    yield


# ═══════════════════════════════════════════════════════════════════════════
# Price observation persistence through the connector path
# ═══════════════════════════════════════════════════════════════════════════

class _FakePriceConnector:
    """Duck-typed price connector: yields one deterministic snapshot."""

    def __init__(self, snapshot) -> None:
        self.sink = None
        self.emit_enabled = False
        self._snapshot = snapshot

    async def get_price_observation(self, *, tenant_id: str = ""):
        return self._snapshot


def _snapshot(provider: str, price: Decimal) -> StablecoinPriceObservation:
    return StablecoinPriceObservation(
        deployment_id="d1", chain_id="1", canonical_asset_id="usdc",
        available=True, price_usd=price, peg_status="on_peg",
        peg_deviation_bps=Decimal("0"), confidence="high", stale=False,
        observed_at="2026-08-08T00:00:00+00:00",
        source={"provider": provider, "feed_address": f"0x{provider}"},
    )


async def test_persist_price_observation_wires_default_sink():
    snap = _snapshot("chainlink_price_feed", Decimal("1.00000000"))
    connector = _FakePriceConnector(snap)
    await persist_price_observation(connector, tenant_id="t1")
    assert connector.emit_enabled is True
    # Snapshot persisted to the durable JSONB store.
    from repositories.stablecoin_repos import StablecoinObservationRepository
    # The default sink writes to BaseRepository("stablecoin_price_observations").
    from repositories.repos import BaseRepository
    store = BaseRepository("stablecoin_price_observations")
    rows = await store.find_many(filters={"tenant_id": "t1"}, limit=10)
    assert len(rows) == 1
    assert rows[0]["price_usd"] == "1.00000000"
    assert rows[0]["available"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Multi-provider disagreement -> durable conflict / duplicate
# ═══════════════════════════════════════════════════════════════════════════

async def test_price_disagreement_persists_conflict_then_duplicate():
    reconciler = StablecoinPriceReconciler()
    a = _snapshot("chainlink_price_feed", Decimal("1.00000000"))
    b = _snapshot("pyth_price_feed", Decimal("1.00200000"))  # 200 bps apart
    first = await reconciler.reconcile("t1", [a, b])
    assert first["state"] == CONFLICT_STATE
    assert set(first["providers"]) == {"chainlink_price_feed", "pyth_price_feed"}
    assert "bps" in first["reason"]

    # Re-reconcile the same snapshot set -> DUPLICATE, no second conflict row.
    second = await reconciler.reconcile("t1", [a, b])
    assert second["state"] == STATE_DUPLICATE
    assert second["duplicate_of"] == first["reconciliation_id"]

    repo = StablecoinReconciliationRepository()
    rows = await repo.find_many(filters={"tenant_id": "t1", "state": CONFLICT_STATE}, limit=100)
    assert len(rows) == 1  # conflict persisted exactly once


async def test_new_snapshot_with_same_providers_produces_fresh_conflict():
    """A genuinely new snapshot — new price or new observation time — from the
    same provider set is a NEW signature and a real conflict, not a stale
    duplicate of the old record (regression: the replay signature used to omit
    the snapshot's prices/timestamps, collapsing every later conflict for the
    same providers into a duplicate of the first)."""
    reconciler = StablecoinPriceReconciler()
    a = _snapshot("chainlink_price_feed", Decimal("1.00000000"))
    b = _snapshot("pyth_price_feed", Decimal("1.00200000"))
    first = await reconciler.reconcile("t1", [a, b])
    assert first["state"] == CONFLICT_STATE

    # Re-reconciling the identical snapshot set still dedupes (true replay).
    replay = await reconciler.reconcile("t1", [a, b])
    assert replay["state"] == STATE_DUPLICATE

    repo = StablecoinReconciliationRepository()

    # Same providers, drifted price -> fresh conflict, a second row.
    drifted = _snapshot("pyth_price_feed", Decimal("1.00600000"))
    fresh = await reconciler.reconcile("t1", [a, drifted])
    assert fresh["state"] == CONFLICT_STATE
    rows = await repo.find_many(
        filters={"tenant_id": "t1", "state": CONFLICT_STATE}, limit=100,
    )
    assert len(rows) == 2

    # Same providers + same prices, new observation time -> still a fresh
    # conflict, a third row (observation time is part of the signature).
    later_b = StablecoinPriceObservation(
        deployment_id="d1", chain_id="1", canonical_asset_id="usdc",
        available=True, price_usd=Decimal("1.00200000"), peg_status="on_peg",
        peg_deviation_bps=Decimal("0"), confidence="high", stale=False,
        observed_at="2026-08-08T01:00:00+00:00",
        source={"provider": "pyth_price_feed", "feed_address": "0xpyth_price_feed"},
    )
    timed = await reconciler.reconcile("t1", [a, later_b])
    assert timed["state"] == CONFLICT_STATE
    rows = await repo.find_many(
        filters={"tenant_id": "t1", "state": CONFLICT_STATE}, limit=100,
    )
    assert len(rows) == 3


async def test_price_consensus_persists_consensus():
    reconciler = StablecoinPriceReconciler()
    a = _snapshot("chainlink_price_feed", Decimal("1.00000000"))
    b = _snapshot("pyth_price_feed", Decimal("1.00001000"))
    result = await reconciler.reconcile("t1", [a, b])
    assert result["state"] == "consensus"
    assert result["reconciliation_id"].startswith("stablecoin_price_reconciled:t1:")


async def test_reconcile_requires_tenant_and_snapshots():
    reconciler = StablecoinPriceReconciler()
    with pytest.raises(ValueError):
        await reconciler.reconcile("t1", [])
    with pytest.raises(ValueError):
        await reconciler.reconcile("", [_snapshot("chainlink_price_feed", Decimal("1"))])
