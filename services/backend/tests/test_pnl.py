"""Tests for the PNL calculator — FIFO engine and result shape."""
from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone

import pytest

from services.pnl.pnl_calculator import FIFOLedger, CostBasisLot, PNLCalculator


# ── FIFOLedger unit tests ──────────────────────────────────────────────────


def test_fifo_buy_and_sell_profit():
    ledger = FIFOLedger()
    now = datetime.now(timezone.utc)
    ledger.buy(Decimal("10"), Decimal("100"), now)   # 10 units at $100
    pnl = ledger.sell(Decimal("5"), Decimal("150"))   # sell 5 at $150 → profit $250
    assert pnl == Decimal("250")
    assert ledger.realized_pnl == Decimal("250")


def test_fifo_buy_and_sell_loss():
    ledger = FIFOLedger()
    now = datetime.now(timezone.utc)
    ledger.buy(Decimal("10"), Decimal("200"), now)
    pnl = ledger.sell(Decimal("10"), Decimal("100"))  # loss $1000
    assert pnl == Decimal("-1000")


def test_fifo_multiple_lots():
    ledger = FIFOLedger()
    now = datetime.now(timezone.utc)
    ledger.buy(Decimal("5"), Decimal("100"), now)
    ledger.buy(Decimal("5"), Decimal("200"), now)
    # Sell 8 units: first 5 from lot1 at $100, then 3 from lot2 at $200
    pnl = ledger.sell(Decimal("8"), Decimal("150"))
    # lot1 contribution: 5 × (150 - 100) = 250
    # lot2 contribution: 3 × (150 - 200) = -150
    assert pnl == Decimal("100")


def test_fifo_open_cost_basis():
    ledger = FIFOLedger()
    now = datetime.now(timezone.utc)
    ledger.buy(Decimal("10"), Decimal("50"), now)
    ledger.sell(Decimal("4"), Decimal("60"))
    # 6 units remain at $50 each
    assert ledger.open_cost_basis == Decimal("300")


def test_fifo_sell_more_than_held_empties_lots():
    ledger = FIFOLedger()
    now = datetime.now(timezone.utc)
    ledger.buy(Decimal("3"), Decimal("100"), now)
    ledger.sell(Decimal("5"), Decimal("150"))  # only 3 matched
    assert len(ledger.lots) == 0


# ── PNLCalculator integration (mocked providers) ──────────────────────────


class _MockClickHouse:
    def __init__(self, rows=None):
        self.rows = rows or []

    async def query(self, sql, params=None):
        return self.rows


class _MockProvider:
    def __init__(self, result=None):
        self.result = result

    async def execute(self, method, params):
        return self.result


@pytest.mark.asyncio
async def test_calculator_empty_data_returns_zeros():
    calc = PNLCalculator(
        clickhouse_client=_MockClickHouse(rows=[]),
        coingecko_provider=_MockProvider(),
        moralis_provider=_MockProvider(),
    )
    result = await calc.compute("e1", "t1", window_days=30)
    assert result.realized_pnl_usd == Decimal("0")
    assert result.unrealized_pnl_usd == Decimal("0")
    assert result.tvl_delta_usd == Decimal("0")
    assert result.data_confidence == "exact"


@pytest.mark.asyncio
async def test_calculator_tvl_delta_from_snapshots():
    rows = [
        {"date": "2026-01-01", "total_portfolio_usd": 1000},
        {"date": "2026-01-31", "total_portfolio_usd": 1500},
    ]
    calc = PNLCalculator(
        clickhouse_client=_MockClickHouse(rows=rows),
        coingecko_provider=_MockProvider(),
        moralis_provider=_MockProvider(result={"data": {"unrealized_pnl_usd": 200}}),
    )
    result = await calc.compute("e1", "t1", window_days=30)
    assert result.tvl_delta_usd == Decimal("500")
    assert result.tvl_delta_pct == pytest.approx(50.0)
    assert result.unrealized_pnl_usd == Decimal("200")
    assert len(result.daily_series) == 2


@pytest.mark.asyncio
async def test_calculator_best_worst_day():
    tvl_rows = [
        {"date": "2026-01-01", "total_portfolio_usd": 1000},
        {"date": "2026-01-02", "total_portfolio_usd": 1200},   # best +200
        {"date": "2026-01-03", "total_portfolio_usd": 900},    # worst -300
        {"date": "2026-01-04", "total_portfolio_usd": 950},
    ]
    calc = PNLCalculator(
        clickhouse_client=_MockClickHouse(rows=tvl_rows),
        coingecko_provider=_MockProvider(),
        moralis_provider=_MockProvider(),
    )
    result = await calc.compute("e1", "t1", window_days=30)
    assert result.best_day_pnl_usd == Decimal("200")
    assert result.worst_day_pnl_usd == Decimal("-300")
