"""WS-D Silver exact-money helpers (item 7 / Invariant #13).

Reuses the financial-normalization exact machinery
(``services.value.models.to_decimal_string``) — WS-D does NOT re-implement it
and does NOT build a second money type (reserved row 658: coordinate with
feat/financial-normalization). These helpers only choose WHICH values the Silver
projection writes: under ``AETHER_SILVER_EXACT_MONEY_ENABLED`` a missing amount
stays a typed absence (``None``) instead of the current collapse to ``0.0`` /
``'USD'``, and a present amount is recorded as an exact decimal string.

The legacy NOT NULL ``amount``/``currency`` columns keep pre-WS-D semantics for
byte parity (flag OFF is byte-for-byte unchanged); the additive ``*_exact``
columns are the flag-ON canonical money surface that exact-money / event-time
valuation consumers read.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.backend_interpretation.flags import silver_exact_money_enabled
from services.value.models import to_decimal_string

# Canonical money column names the Silver projectors emit (additive schema).
_AMOUNT_EXACT_KEYS = ("amount", "total", "value", "amount_usd", "total_amount")
_VALUE_EXACT_KEYS = ("value", "amount")


def exact_money_fields(
    props: dict[str, Any],
    *,
    amount_keys: tuple[str, ...] = _AMOUNT_EXACT_KEYS,
    currency_key: str = "currency",
    default_currency: Optional[str] = None,
    prefix: str = "",
    enabled: Optional[bool] = None,
) -> dict[str, Any]:
    """Return ``{<prefix>amount_exact, <prefix>currency_exact}`` for one row.

    Flag OFF (default) returns an empty dict: the caller's legacy column values
    are untouched, so Silver output is byte-for-byte identical. Flag ON parses
    the first present amount key through the canonical exact machinery —
    missing/unparseable amounts yield ``None`` (never ``0.0``) and the currency
    is the source's currency verbatim (never the ``'USD'`` default).
    """
    if enabled is None:
        enabled = silver_exact_money_enabled()
    if not enabled:
        return {}

    raw_amount: Any = None
    for key in amount_keys:
        value = props.get(key)
        if value not in (None, ""):
            raw_amount = value
            break
    currency = props.get(currency_key)
    if currency is None or currency == "":
        currency = default_currency

    return {
        f"{prefix}amount_exact": to_decimal_string(raw_amount),
        f"{prefix}currency_exact": currency,
    }


def revenue_exact_money(props: dict[str, Any], *, enabled: Optional[bool] = None) -> dict[str, Any]:
    return exact_money_fields(props, enabled=enabled)


def outcome_exact_money(props: dict[str, Any], *, enabled: Optional[bool] = None) -> dict[str, Any]:
    """Outcome rows use value_amount/value_currency legacy names.

    Legacy outcome money (value_amount NUMERIC(20,4) nullable, value_currency
    TEXT nullable) is not NOT NULL, so under the flag we ALSO replace the
    collapsed value/currency with exact values in place (no separate column
    needed for the outcome family — the additive value_*_exact columns mirror
    the revenue *_exact names so the schema is uniform).
    """
    fields = exact_money_fields(
        props,
        amount_keys=_VALUE_EXACT_KEYS,
        prefix="value_",
        enabled=enabled,
    )
    return fields


__all__ = [
    "exact_money_fields",
    "outcome_exact_money",
    "revenue_exact_money",
]
