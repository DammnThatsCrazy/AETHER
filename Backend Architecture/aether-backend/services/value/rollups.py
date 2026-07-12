"""Safe value rollups — never a single mixed-currency scalar, unknown != 0.

A rollup groups values by native currency, sums a USD total across only the
values that carry a trustworthy USD valuation, and records why anything was
excluded. If no value can be priced, the USD total is None (not 0). A
single-native-currency raw sum is exposed separately as an unambiguous
convenience (deprecated); a mixed-currency raw sum is never produced.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from services.value.models import to_decimal
from services.value.valuation import value_of


def _dstr(d: Optional[Decimal]) -> Optional[str]:
    return None if d is None else format(d, "f")


def safe_rollup(records: Iterable[dict], *, metric_kind: str = "flow") -> dict:
    """Roll up an iterable of raw value records safely.

    Returns a dict matching packages/shared/value.ts RollupResult, plus
    `native_currency` / `native_total` (the unambiguous single-currency raw sum,
    or None when currencies are mixed).
    """
    by_currency: dict[str, dict] = {}
    included = 0          # records with a parseable native amount
    priced = 0           # records counted into the USD total (priced + eligible)
    unpriced = 0         # records with an amount but no trusted USD value
    excluded = 0         # records with no amount, or priced-but-rollup-ineligible
    total_usd = Decimal(0)
    any_usd = False

    for record in records:
        v = value_of(record, metric_kind=metric_kind)
        amount = to_decimal(v["native"]["amount"])
        if amount is None:
            excluded += 1
            continue
        included += 1
        currency = v["native"]["currency"] or "unknown"
        usd = to_decimal(v["valuation"]["usd_value"])
        eligible = v["status"].get("include_in_rollups", usd is not None)

        bucket = by_currency.setdefault(
            currency, {"amount": Decimal(0), "usd": Decimal(0), "count": 0, "priced": True}
        )
        bucket["amount"] += amount
        bucket["count"] += 1
        if usd is not None and eligible:
            bucket["usd"] += usd
            total_usd += usd
            any_usd = True
            priced += 1
        elif usd is None:
            bucket["priced"] = False
            unpriced += 1
        else:
            # Priced but ownership/policy-excluded (testnet / spam / liability /
            # counterparty) — never enters the trusted USD total.
            bucket["priced"] = False
            excluded += 1

    if included == 0 and excluded == 0:
        rollup_status = "unavailable"
    elif priced == 0:
        rollup_status = "unavailable"
    elif unpriced == 0 and priced == included:
        rollup_status = "complete"
    else:
        rollup_status = "partial"

    # Single unambiguous native currency => expose a raw sum; otherwise None.
    native_currency: Optional[str] = None
    native_total: Optional[str] = None
    if len(by_currency) == 1:
        native_currency = next(iter(by_currency))
        native_total = _dstr(by_currency[native_currency]["amount"])

    return {
        "total_usd": _dstr(total_usd) if any_usd else None,
        "by_native_currency": {
            cur: {
                "amount": _dstr(b["amount"]),
                "usd_value": _dstr(b["usd"]) if b["priced"] else None,
                "count": b["count"],
                "priced": b["priced"],
            }
            for cur, b in by_currency.items()
        },
        "unpriced_count": unpriced,
        "stale_count": 0,
        "excluded_count": excluded,
        "rollup_status": rollup_status,
        "native_currency": native_currency,
        "native_total": native_total,
    }
