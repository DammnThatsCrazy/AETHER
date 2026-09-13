"""Web2 account valuation — prompt §4.13.

Pure computation over a single account record. Classifies the account as an
``asset`` or ``liability`` and produces a signed USD value:

  - credit-card / loan / negative-balance accounts are liabilities and their
    ``usd_value`` is negative;
  - deposit / brokerage / positive-balance accounts are assets and positive;
  - anything the price sources cannot value is ``None`` (never ``0``).

USD is resolved through ``price_sources.price``; native currency is preserved.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from services.value import price_sources
from services.value.models import to_decimal, to_decimal_string

_LIABILITY_ACCOUNT_TYPES = frozenset({
    "credit_card", "credit", "credit_line", "line_of_credit",
    "loan", "mortgage", "liability", "student_loan", "auto_loan",
})


def _classification(account: dict, current: Optional[Decimal]) -> str:
    account_type = str(account.get("account_type") or "").lower()
    if account_type in _LIABILITY_ACCOUNT_TYPES:
        return "liability"
    if account.get("is_liability") or account.get("liability"):
        return "liability"
    if current is not None and current < 0:
        return "liability"
    return "asset"


def account_value(account: dict) -> dict:
    """Return a signed USD valuation + display envelope for a Web2 account."""
    currency = account.get("currency")
    current = to_decimal(account.get("current_balance"))
    classification = _classification(account, current)

    # Price the magnitude, then apply the classification's sign so a credit card
    # reported as a positive balance still values negatively.
    magnitude = None if current is None else abs(current)
    priced = price_sources.price(magnitude, currency)
    usd_mag = to_decimal(priced["usd_value"]) if priced else None
    if usd_mag is None:
        usd_value: Optional[str] = None
    else:
        signed = -usd_mag if classification == "liability" else usd_mag
        usd_value = format(signed, "f")

    if usd_value is None:
        primary = "Value unavailable"
    elif classification == "liability":
        primary = f"-${format(abs(Decimal(usd_value)), 'f')} USD"
    else:
        primary = f"${usd_value} USD"

    provider = account.get("provider")
    account_type = account.get("account_type")
    secondary = " · ".join(str(p) for p in (account_type, provider) if p)

    return {
        "account_type": account_type,
        "provider": provider,
        "currency": currency,
        "current": to_decimal_string(account.get("current_balance")),
        "available": to_decimal_string(account.get("available_balance")),
        "pending": to_decimal_string(account.get("pending_balance")),
        "classification": classification,
        "usd_value": usd_value,
        "original_currency": currency,
        "last_synced": account.get("last_synced"),
        "display": {"primary": primary, "secondary": secondary or None},
    }
