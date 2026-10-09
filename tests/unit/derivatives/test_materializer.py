"""The materializer turns raw fills into epochs, P&L snapshots and variances."""

from __future__ import annotations

from decimal import Decimal

import pytest

from repositories.derivatives_repos import (
    FillRepo,
    PnlSnapshotRepo,
    PositionEpochRepo,
    PositionRepo,
    PriceObservationRepo,
    ReconciliationVarianceRepo,
    TradingAccountRepo,
)
from services.derivatives import materializer
from services.derivatives.models import NormalizedFillFact, OrderSide, PositionStatus

TENANT = "t-mat-a"
OTHER_TENANT = "t-mat-b"
ACCT = "acct-1"
MKT = "hyperliquid:BTC-PERP"


def D(value: str) -> Decimal:
    return Decimal(value)


async def _fill(tenant, fill_id, side, price, qty, at, fee="0", account=ACCT, market=MKT):
    await FillRepo().insert({
        "tenant_id": tenant, "fill_id": fill_id, "trading_account_id": account,
        "canonical_market_id": market, "side": side, "price": D(price), "quantity": D(qty),
        "fee_amount": D(fee), "executed_at": at, "liquidity_role": "taker",
        "idempotency_key": f"{tenant}|{fill_id}", "execution_by_aether": False,
    })


async def _account(tenant):
    await TradingAccountRepo().insert({
        "tenant_id": tenant, "trading_account_id": ACCT, "venue_id": "hyperliquid",
        "venue_deployment_id": "mainnet", "idempotency_key": f"{tenant}|acct",
        "execution_by_aether": False,
    })


async def _mark(tenant, price, at="2026-07-10T00:00:00+00:00", obs="px-1"):
    await PriceObservationRepo().insert({
        "tenant_id": tenant, "price_observation_id": obs, "canonical_market_id": MKT,
        "price_type": "mark", "price": D(price), "observed_at": at,
        "idempotency_key": f"{tenant}|{obs}", "execution_by_aether": False,
    })


async def _venue_position(tenant, side, size, realized=None):
    await PositionRepo().insert({
        "tenant_id": tenant, "position_id": "vp-1", "trading_account_id": ACCT,
        "canonical_market_id": MKT, "side": side, "status": "open", "size": D(size),
        "realized_pnl": D(realized) if realized is not None else None,
        "updated_at": "2026-07-10T00:00:00+00:00",
        "idempotency_key": f"{tenant}|vp-1|{size}", "execution_by_aether": False,
    })


# ── replay ────────────────────────────────────────────────────────────────


def _fact(fill_id, side, price, qty, at, fee="0"):
    return NormalizedFillFact(
        tenant_id=TENANT, provider="hyperliquid", deployment="mainnet", trading_account_id=ACCT,
        canonical_market_id=MKT, fill_id=fill_id, side=side, price=D(price), quantity=D(qty),
        executed_at=at, fee_amount=D(fee),
    )


def test_a_round_trip_is_one_closed_epoch_and_a_second_lifecycle_gets_its_own():
    closed, open_state = materializer.replay_epochs([
        _fact("f1", OrderSide.BUY, "100", "2", "t1"),
        _fact("f2", OrderSide.SELL, "110", "2", "t2"),
        _fact("f3", OrderSide.BUY, "120", "1", "t3"),
    ])
    assert len(closed) == 1
    assert closed[0].open_size == D("2") and closed[0].close_size == D("2")
    assert closed[0].state.realized_pnl == D("20")
    assert open_state is not None and open_state.size == D("1")
    assert open_state.epoch_id != closed[0].state.epoch_id  # a fresh epoch, not a reopen


def test_a_flip_closes_the_epoch_and_opens_another_for_the_remainder():
    closed, open_state = materializer.replay_epochs([
        _fact("f1", OrderSide.BUY, "100", "1", "t1"),
        _fact("f2", OrderSide.SELL, "110", "3", "t2"),
    ])
    assert len(closed) == 1 and closed[0].close_size == D("1")
    assert closed[0].state.realized_pnl == D("10")
    assert open_state.status is PositionStatus.OPEN and open_state.size == D("2")
    assert open_state.side.value == "short"


# ── persistence ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_closed_epochs_and_a_pnl_snapshot_are_written_once():
    await _account(TENANT)
    await _fill(TENANT, "f1", "buy", "100", "2", "2026-07-01T00:00:00+00:00", fee="1")
    await _fill(TENANT, "f2", "sell", "110", "2", "2026-07-02T00:00:00+00:00", fee="1")
    await _fill(TENANT, "f3", "buy", "120", "1", "2026-07-03T00:00:00+00:00")
    await _mark(TENANT, "130")

    first = await materializer.materialize_tenant(TENANT)
    assert first.totals["epochs_written"] == 1 and first.totals["snapshots_written"] == 1

    epochs = await PositionEpochRepo().find_many({"tenant_id": TENANT})
    assert len(epochs) == 1 and epochs[0]["open_size"] == D("2") and epochs[0]["close_size"] == D("2")
    assert epochs[0]["execution_by_aether"] is False

    snapshot = (await PnlSnapshotRepo().find_many({"tenant_id": TENANT}))[0]
    assert snapshot["realized_pnl"] == D("20")
    assert snapshot["unrealized_pnl"] == D("10")      # (130 - 120) * 1
    assert snapshot["net_exposure"] == D("130") and snapshot["gross_exposure"] == D("130")
    assert snapshot["accounting_method"] == "average_entry"
    assert snapshot["evidence"]["mark_price_available"] is True
    assert snapshot["evidence"]["fees"] == "2"

    # Nothing changed, so a second pass writes nothing.
    second = await materializer.materialize_tenant(TENANT)
    assert second.totals["epochs_written"] == 0 and second.totals["snapshots_written"] == 0
    assert len(await PnlSnapshotRepo().find_many({"tenant_id": TENANT})) == 1

    # A new fill (or mark) writes a new snapshot.
    await _fill(TENANT, "f4", "sell", "125", "1", "2026-07-04T00:00:00+00:00")
    third = await materializer.materialize_tenant(TENANT)
    assert third.totals["snapshots_written"] == 1 and third.totals["epochs_written"] == 1


@pytest.mark.asyncio
async def test_without_a_mark_price_the_snapshot_says_so():
    await _fill(TENANT, "f1", "buy", "100", "1", "2026-07-01T00:00:00+00:00")
    await materializer.materialize_tenant(TENANT)
    snapshot = (await PnlSnapshotRepo().find_many({"tenant_id": TENANT}))[0]
    assert snapshot["evidence"]["mark_price_available"] is False
    assert snapshot["evidence"]["open_size"] == "1"


@pytest.mark.asyncio
async def test_an_unusable_fill_is_skipped_and_counted_not_fatal():
    await _fill(TENANT, "bad", "buy", "100", "0", "2026-07-01T00:00:00+00:00")
    await _fill(TENANT, "ok", "buy", "100", "1", "2026-07-02T00:00:00+00:00")
    result = await materializer.materialize_tenant(TENANT)
    market = result.markets[(ACCT, MKT)]
    assert market.skipped_fills == 1 and market.fills == 1 and market.size == D("1")


@pytest.mark.asyncio
async def test_tenants_are_materialized_independently():
    await _fill(TENANT, "f1", "buy", "100", "1", "2026-07-01T00:00:00+00:00")
    await _fill(OTHER_TENANT, "f1", "buy", "50", "5", "2026-07-01T00:00:00+00:00")
    await materializer.materialize_tenant(TENANT)
    assert await PnlSnapshotRepo().find_many({"tenant_id": OTHER_TENANT}) == []
    await materializer.materialize_tenant(OTHER_TENANT)
    assert (await PnlSnapshotRepo().find_many({"tenant_id": OTHER_TENANT}))[0]["evidence"]["open_size"] == "5"


@pytest.mark.asyncio
async def test_the_flags_choose_what_is_written():
    await _fill(TENANT, "f1", "buy", "100", "1", "2026-07-01T00:00:00+00:00")
    await _venue_position(TENANT, "long", "3")
    await materializer.materialize_tenant(TENANT, write_pnl=False, write_variances=False)
    assert await PnlSnapshotRepo().find_many({"tenant_id": TENANT}) == []
    assert await ReconciliationVarianceRepo().find_many({"tenant_id": TENANT}) == []


# ── reconciliation against the venue ─────────────────────────────────────


@pytest.mark.asyncio
async def test_a_position_that_matches_the_venue_records_no_variance():
    await _fill(TENANT, "f1", "buy", "100", "2", "2026-07-01T00:00:00+00:00")
    await _venue_position(TENANT, "long", "2", realized="0")
    result = await materializer.materialize_tenant(TENANT)
    assert result.totals["variances_written"] == 0
    assert await ReconciliationVarianceRepo().find_many({"tenant_id": TENANT}) == []


@pytest.mark.asyncio
async def test_a_position_that_disagrees_with_the_venue_is_recorded_once():
    await _fill(TENANT, "f1", "buy", "100", "2", "2026-07-01T00:00:00+00:00")
    await _venue_position(TENANT, "long", "3")
    first = await materializer.materialize_tenant(TENANT)
    assert first.totals["variances_written"] == 1
    rows = await ReconciliationVarianceRepo().find_many({"tenant_id": TENANT})
    assert len(rows) == 1
    assert rows[0]["variance_type"] == "size_mismatch"
    assert rows[0]["expected_value"] == D("2") and rows[0]["observed_value"] == D("3")
    assert rows[0]["difference"] == D("1")
    assert MKT in rows[0]["source_refs"]
    # The same disagreement on the next pass is not recorded again.
    again = await materializer.materialize_tenant(TENANT)
    assert again.totals["variances_written"] == 1  # detected again ...
    assert len(await ReconciliationVarianceRepo().find_many({"tenant_id": TENANT})) == 1  # ... stored once


@pytest.mark.asyncio
async def test_a_short_venue_position_is_compared_with_its_sign():
    await _fill(TENANT, "f1", "sell", "100", "2", "2026-07-01T00:00:00+00:00")
    await _venue_position(TENANT, "short", "2")
    result = await materializer.materialize_tenant(TENANT)
    assert result.totals["variances_written"] == 0
    assert result.markets[(ACCT, MKT)].size == D("-2")
