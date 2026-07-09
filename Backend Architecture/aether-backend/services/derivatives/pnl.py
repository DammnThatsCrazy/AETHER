"""Decimal-only derivatives P&L and exposure.

Binary floating point is never a legal carrier for canonical finance:
every entry point routes amounts through repositories.typed_repo.as_decimal,
which raises TypeError on float. Linear and inverse contract conventions are
implemented; quanto settlement honestly raises NotImplementedError.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from repositories.typed_repo import as_decimal

ZERO = Decimal("0")


def realized_pnl_average_entry(fills: Iterable[dict[str, Any]]) -> dict[str, Decimal]:
    """Average-entry realized P&L over a chronological fill stream for one
    market. Fills: {side: 'buy'|'sell', price, quantity, multiplier?}.

    Long flow: buys build the position at a running average entry; sells
    realize (exit - avg_entry) * qty. Short flow symmetric. Reversals close
    the old exposure first, then open the remainder at the fill price.
    """
    position = ZERO          # signed base quantity (+ long / - short)
    avg_entry = ZERO
    realized = ZERO

    for fill in fills:
        price = as_decimal(fill["price"])
        quantity = as_decimal(fill["quantity"])
        multiplier = as_decimal(fill.get("multiplier", 1))
        if quantity <= ZERO:
            raise ValueError("fill quantity must be positive")
        signed = quantity if fill["side"] == "buy" else -quantity

        if position == ZERO or (position > ZERO) == (signed > ZERO):
            # Extending (or opening) — new weighted average entry.
            new_position = position + signed
            avg_entry = (
                (avg_entry * abs(position) + price * abs(signed)) / abs(new_position)
                if new_position != ZERO else ZERO
            )
            position = new_position
            continue

        # Reducing / reversing: realize on the closed portion.
        closing = min(abs(signed), abs(position))
        direction = Decimal(1) if position > ZERO else Decimal(-1)
        realized += (price - avg_entry) * closing * direction * multiplier
        position += signed
        if position == ZERO:
            avg_entry = ZERO
        elif (position > ZERO) != (direction > ZERO):
            # Reversal: the remainder opens a fresh exposure at the fill price.
            avg_entry = price

    return {"realized_pnl": realized, "open_position": position, "avg_entry": avg_entry}


def unrealized_pnl(
    position_size: Any,
    avg_entry: Any,
    mark_price: Any,
    contract_style: str = "linear",
    multiplier: Any = 1,
) -> Decimal:
    """Unrealized P&L for a signed position (+ long / - short).

    linear:  (mark - entry) * size * multiplier              (quote units)
    inverse: (1/entry - 1/mark) * size * multiplier          (base units)
    quanto:  requires a venue-specific conversion rate — not implemented.
    """
    size = as_decimal(position_size)
    entry = as_decimal(avg_entry)
    mark = as_decimal(mark_price)
    mult = as_decimal(multiplier)
    if size == ZERO:
        return ZERO
    if contract_style == "linear":
        return (mark - entry) * size * mult
    if contract_style == "inverse":
        if entry == ZERO or mark == ZERO:
            raise ValueError("inverse P&L requires non-zero entry and mark prices")
        return (Decimal(1) / entry - Decimal(1) / mark) * size * mult
    if contract_style == "quanto":
        raise NotImplementedError(
            "quanto settlement requires venue-specific conversion — deferred"
        )
    raise ValueError(f"unknown contract style: {contract_style!r}")


def exposure(positions: Iterable[dict[str, Any]]) -> dict[str, Decimal]:
    """Gross/net notional exposure over {size, mark_price, multiplier?} rows.
    Size is signed (+ long / - short)."""
    gross = ZERO
    net = ZERO
    for position in positions:
        size = as_decimal(position["size"])
        mark = as_decimal(position["mark_price"])
        mult = as_decimal(position.get("multiplier", 1))
        notional = size * mark * mult
        gross += abs(notional)
        net += notional
    return {"gross_exposure": gross, "net_exposure": net}
