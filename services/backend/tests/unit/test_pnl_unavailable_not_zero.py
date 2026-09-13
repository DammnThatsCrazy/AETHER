"""PNL/TVL: a provider/store failure is UNAVAILABLE, never a numeric zero
(Zero Silent Failure, program sec7).

Under test:
- ``_get_tvl_snapshots`` raises ``PNLUnavailableError`` when the store query
  fails — a failed read is NOT an empty store.
- ``_compute_realized_pnl`` raises when the tx query fails.
- ``_compute_unrealized_pnl`` raises when Moralis is absent or fails.
- A GENUINELY empty dataset still legitimately yields zero (no raise).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.pnl.pnl_calculator import PNLCalculator, PNLUnavailableError


class _FailingCH:
    async def query(self, sql, params=None):
        raise RuntimeError("clickhouse down")


class _EmptyCH:
    async def query(self, sql, params=None):
        return []


class _FailingMoralis:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("moralis down")


class _EmptyMoralis:
    async def execute(self, *args, **kwargs):
        return {}


def _calculator(ch, moralis=None) -> PNLCalculator:
    return PNLCalculator(
        clickhouse_client=ch,
        coingecko_provider=object(),
        moralis_provider=moralis,
    )


class TestTvlSnapshotsUnavailableNotZero:
    async def test_store_failure_raises_unavailable(self):
        calc = _calculator(_FailingCH())
        with pytest.raises(PNLUnavailableError):
            await calc._get_tvl_snapshots("e1", "t1", None, None)

    async def test_store_failure_is_not_zero_delta(self):
        calc = _calculator(_FailingCH())
        try:
            await calc._get_tvl_snapshots("e1", "t1", None, None)
        except PNLUnavailableError:
            pass
        else:
            pytest.fail("must raise, never return (0, 0, [])")

    async def test_genuinely_empty_dataset_is_zero(self):
        calc = _calculator(_EmptyCH())
        tvl_start, tvl_end, daily = await calc._get_tvl_snapshots("e1", "t1", None, None)
        assert tvl_start == Decimal("0")
        assert tvl_end == Decimal("0")
        assert daily == []


class TestRealizedPnlUnavailableNotZero:
    async def test_tx_query_failure_raises_unavailable(self):
        calc = _calculator(_FailingCH())
        with pytest.raises(PNLUnavailableError):
            await calc._compute_realized_pnl("e1", "t1", None, None)

    async def test_empty_tx_history_is_zero_with_exact_confidence(self):
        calc = _calculator(_EmptyCH())
        realized, confidence = await calc._compute_realized_pnl("e1", "t1", None, None)
        assert realized == Decimal("0")
        assert confidence == "exact"


class TestUnrealizedPnlUnavailableNotZero:
    async def test_missing_moralis_raises_not_zero(self):
        calc = _calculator(_EmptyCH(), moralis=None)
        with pytest.raises(PNLUnavailableError):
            await calc._compute_unrealized_pnl("e1")

    async def test_moralis_failure_raises_not_zero(self):
        calc = _calculator(_EmptyCH(), moralis=_FailingMoralis())
        with pytest.raises(PNLUnavailableError):
            await calc._compute_unrealized_pnl("e1")

    async def test_empty_portfolio_is_zero(self):
        calc = _calculator(_EmptyCH(), moralis=_EmptyMoralis())
        assert await calc._compute_unrealized_pnl("e1") == Decimal("0")

    async def test_healthy_portfolio_returns_value(self):
        class _MoralisWithData:
            async def execute(self, *args, **kwargs):
                return {"data": {"unrealized_pnl_usd": "200"}}

        calc = _calculator(_EmptyCH(), moralis=_MoralisWithData())
        assert await calc._compute_unrealized_pnl("e1") == Decimal("200")
