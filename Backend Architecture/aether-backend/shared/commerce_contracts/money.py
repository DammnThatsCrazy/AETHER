"""Canonical money vocabulary for the provider-neutral commerce contracts.

:class:`Money` is the single provider-neutral amount type exchanged across
commerce integrations. It pairs an exact :class:`decimal.Decimal` amount with
an ISO-4217 currency code so arithmetic never drifts through binary floats.

:class:`Currency` is deliberately a *minimal vocabulary*, not a gate: the enum
documents the ISO-4217 codes the platform speaks today and is open-ended by
design. ``Money.currency`` is a plain ``str`` precisely so providers with a
currency code outside the curated set can still round-trip without rejection.

Negative amounts are legitimate (refunds and credits), so they are accepted
without validation. All instances are frozen and therefore hashable, making
them safe as dict keys and set members.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict

# Neutral fallback currency for ``sum_money`` of an empty input, where no
# "common currency" exists to inherit. USD is the platform's base ledger
# currency and the first member of :class:`Currency`.
_DEFAULT_SUM_CURRENCY = "USD"


class Currency(str, Enum):
    """Minimal ISO-4217 set (open-ended is fine — a vocabulary, not a gate)."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    AUD = "AUD"


class Money(BaseModel):
    """Exact decimal amount in a single ISO-4217 currency.

    ``amount`` is a :class:`decimal.Decimal`; pydantic v2 coerces ``int`` and
    numeric ``str`` inputs (e.g. ``"12.34"``) to ``Decimal`` on construction.
    Negative amounts are allowed (refunds/credits).
    """

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    currency: str

    def __str__(self) -> str:  # pragma: no cover - trivial formatting helper
        return f"{self.amount} {self.currency}"


def sum_money(items: Iterable[Money]) -> Money:
    """Sum :class:`Money` values, raising ``ValueError`` on mixed currency.

    The sum is exact (``Decimal``) and keeps the currency of the first item.
    An empty input returns a zero amount in the platform's default currency
    (:data:`_DEFAULT_SUM_CURRENCY`), since no common currency can be inferred.
    """
    items = list(items)
    if not items:
        return Money(amount=Decimal("0"), currency=_DEFAULT_SUM_CURRENCY)
    currency = items[0].currency
    total = Decimal("0")
    for m in items:
        if m.currency != currency:
            raise ValueError(
                "sum_money requires a single currency across all items; "
                f"got {currency!r} and {m.currency!r}"
            )
        total += m.amount
    return Money(amount=total, currency=currency)


def money_from_cents(cents: int, currency: str) -> Money:
    """Build a :class:`Money` from an integer minor-unit (cents) count."""
    return Money(amount=Decimal(cents) / 100, currency=currency)


def to_cents(m: Money) -> int:
    """Convert a :class:`Money` to an integer minor-unit (cents) count.

    Deterministic: the amount is quantized to 2 decimal places with
    ``ROUND_HALF_UP`` before scaling, so half-cents never leak and identical
    inputs always produce identical output.
    """
    amount = m.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(amount * 100)


__all__ = [
    "Currency",
    "Money",
    "money_from_cents",
    "sum_money",
    "to_cents",
]
