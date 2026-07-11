"""Canonical value model — backend mirror of packages/shared/value.ts.

All amounts are Decimal strings, never floats. unknown/stale/unpriced/conflicted
values are never coerced to zero.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

# Canonical enumerations (kept in lockstep with packages/shared/value.ts).
METRIC_KINDS = frozenset({
    "balance", "flow", "kpi", "forecast", "valuation", "liability",
    "cost", "fee", "revenue", "risk_exposure", "unknown",
})
FRESHNESS = frozenset({"live", "recent", "stale", "expired", "unavailable"})
CONFIDENCE = frozenset({"high", "medium", "low", "unknown"})
OWNERSHIP_RELATIONSHIPS = frozenset({
    "owned", "linked", "controlled", "custodied", "delegated",
    "counterparty", "observed", "inferred", "external", "unknown",
})
RECONCILIATION_STATES = frozenset({
    "sdk_only", "provider_only", "matched", "stale", "conflict",
    "ignored_duplicate", "unreconciled", "not_applicable",
})
VALUATION_METHODS = frozenset({
    "fiat_identity", "fx_rate", "market_price", "provider_reported",
    "stablecoin_peg_verified", "manual", "unavailable",
})
ROLLUP_STATUSES = frozenset({"complete", "partial", "stale", "unavailable", "conflicted"})

# Fiat currencies whose USD value is a 1:1 identity (USD) or would require FX.
USD_CODES = frozenset({"USD", "usd"})


def to_decimal(value: object) -> Optional[Decimal]:
    """Parse a value into a Decimal, or None if it is not a finite number.

    Never returns 0 for an unparseable/absent value — returns None so callers
    must decide explicitly (unknown != 0).
    """
    if value is None:
        return None
    if isinstance(value, bool):  # guard: bool is an int subclass
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return d


def to_decimal_string(value: object) -> Optional[str]:
    """Normalize a numeric value to a plain decimal string, or None."""
    d = to_decimal(value)
    if d is None:
        return None
    # Normalize but avoid scientific notation.
    return format(d, "f")


def is_usd(currency: Optional[str]) -> bool:
    return currency is not None and currency in USD_CODES
