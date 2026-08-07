"""P&L regression: FIFO must flag insufficient basis (missing opening lots)
instead of silently under-reporting realized P&L as if exact, and it must never
invent a zero-cost lot."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from services.pnl.pnl_calculator import FIFOLedger


def _ts():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_sell_within_basis_is_exact():
    led = FIFOLedger()
    led.buy(Decimal("10"), Decimal("100"), _ts())  # 10 units @ 100
    realized = led.sell(Decimal("4"), Decimal("150"))  # sell 4 @ 150
    assert realized == Decimal("200")  # 4 * (150 - 100)
    assert led.insufficient_basis is False


def test_sell_beyond_basis_flags_insufficient():
    led = FIFOLedger()
    led.buy(Decimal("2"), Decimal("100"), _ts())  # only 2 units of basis
    realized = led.sell(Decimal("5"), Decimal("150"))  # sell 5 (3 lack basis)
    # Only the 2 matched units realize P&L; the 3 unmatched do NOT invent a
    # zero-cost lot (which would overstate P&L), and the shortfall is flagged.
    assert realized == Decimal("100")  # 2 * (150 - 100)
    assert led.insufficient_basis is True


def test_no_lots_sell_flags_insufficient_not_zero_cost():
    led = FIFOLedger()
    realized = led.sell(Decimal("1"), Decimal("500"))  # no basis at all
    assert realized == Decimal("0")  # nothing matched
    assert led.insufficient_basis is True  # not silently "exact"
