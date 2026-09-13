"""Deterministic derivatives position reconstruction."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from services.derivatives.models import NormalizedFillFact, OrderSide, PositionEpochState, PositionSide, PositionStatus


def apply_fill(state: PositionEpochState | None, fill: NormalizedFillFact) -> list[PositionEpochState]:
    """Apply one fill and return one or more epoch states.

    A long-to-short or short-to-long flip closes the current epoch and opens a
    new epoch for the remainder, preserving the PR2 epoch invariant that each
    zero -> non-zero lifecycle receives a distinct epoch.
    """
    current = state or _new_epoch(fill)
    if current.status in {PositionStatus.ABSENT, PositionStatus.CLOSED} or current.size == 0:
        return [_open_from_flat(current, fill)]

    signed_delta = fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
    current_signed = current.size if current.side is PositionSide.LONG else -current.size
    new_signed = current_signed + signed_delta

    if current_signed == 0:
        return [_open_from_flat(current, fill)]
    if _same_direction(current_signed, signed_delta):
        return [_increase(current, fill, abs(new_signed))]
    if new_signed == 0:
        return [_close(current, fill)]
    if _same_direction(current_signed, new_signed):
        return [_reduce(current, fill, abs(new_signed))]

    closed = _close(current, fill, close_quantity=abs(current_signed))
    remainder = abs(new_signed)
    reopened_fill = replace(fill, quantity=remainder)
    return [closed, _open_from_flat(_new_epoch(fill, suffix="flip"), reopened_fill)]


def _new_epoch(fill: NormalizedFillFact, suffix: str | None = None) -> PositionEpochState:
    suffix_part = f":{suffix}" if suffix else ""
    return PositionEpochState(
        tenant_id=fill.tenant_id,
        trading_account_id=fill.trading_account_id,
        canonical_market_id=fill.canonical_market_id,
        epoch_id=f"epoch:{fill.trading_account_id}:{fill.canonical_market_id}:{fill.fill_id}{suffix_part}",
    )


def _open_from_flat(state: PositionEpochState, fill: NormalizedFillFact) -> PositionEpochState:
    side = PositionSide.LONG if fill.side is OrderSide.BUY else PositionSide.SHORT
    return replace(
        state,
        side=side,
        status=PositionStatus.OPEN,
        size=fill.quantity,
        entry_notional=fill.price * fill.quantity,
        fees=state.fees + fill.fee_amount,
        opened_at=state.opened_at or fill.executed_at,
        closed_at=None,
        source_fill_ids=[*state.source_fill_ids, fill.fill_id],
    )


def _increase(state: PositionEpochState, fill: NormalizedFillFact, new_size: Decimal) -> PositionEpochState:
    return replace(
        state,
        size=new_size,
        entry_notional=state.entry_notional + (fill.price * fill.quantity),
        fees=state.fees + fill.fee_amount,
        source_fill_ids=[*state.source_fill_ids, fill.fill_id],
    )


def _reduce(state: PositionEpochState, fill: NormalizedFillFact, new_size: Decimal) -> PositionEpochState:
    entry_price = state.entry_price or Decimal("0")
    realized = _realized_pnl(state.side, entry_price, fill.price, fill.quantity)
    remaining_notional = entry_price * new_size
    return replace(
        state,
        size=new_size,
        entry_notional=remaining_notional,
        realized_pnl=state.realized_pnl + realized,
        fees=state.fees + fill.fee_amount,
        source_fill_ids=[*state.source_fill_ids, fill.fill_id],
    )


def _close(state: PositionEpochState, fill: NormalizedFillFact, close_quantity: Decimal | None = None) -> PositionEpochState:
    qty = close_quantity or state.size
    entry_price = state.entry_price or Decimal("0")
    realized = _realized_pnl(state.side, entry_price, fill.price, qty)
    return replace(
        state,
        status=PositionStatus.CLOSED,
        size=Decimal("0"),
        entry_notional=Decimal("0"),
        realized_pnl=state.realized_pnl + realized,
        fees=state.fees + fill.fee_amount,
        closed_at=fill.executed_at,
        source_fill_ids=[*state.source_fill_ids, fill.fill_id],
    )


def _same_direction(a: Decimal, b: Decimal) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _realized_pnl(side: PositionSide, entry_price: Decimal, exit_price: Decimal, quantity: Decimal) -> Decimal:
    if side is PositionSide.LONG:
        return (exit_price - entry_price) * quantity
    if side is PositionSide.SHORT:
        return (entry_price - exit_price) * quantity
    return Decimal("0")
