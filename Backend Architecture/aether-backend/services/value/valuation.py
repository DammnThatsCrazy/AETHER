"""Value normalization — turn a raw record into a native value + USD valuation.

USD valuation policy:
  - explicit value_usd / amount_usd  -> provider_reported;
  - otherwise the pluggable price-source layer (services.value.price_sources)
    resolves USD via fiat identity, FX, token market price, or peg-aware
    stablecoin valuation;
  - anything the sources can't price -> unavailable, usd_value = None (unpriced).

Unpriced is NEVER zero. Rollup inclusion additionally honors ownership rules
(liabilities not assets; testnet / spam / counterparty excluded).
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import utc_now
from services.value import ownership_rules, price_sources
from services.value.models import to_decimal, to_decimal_string

# Field names a record may use for its native amount / currency / USD value.
_AMOUNT_KEYS = ("amount", "value", "quantity")
_CURRENCY_KEYS = ("currency", "asset_symbol", "asset_id", "asset")
_USD_KEYS = ("value_usd", "amount_usd", "usd_value")


def _first(record: dict, keys: tuple[str, ...]) -> Optional[Any]:
    for k in keys:
        v = record.get(k)
        if v is not None and v != "":
            return v
    return None


def value_of(
    record: dict,
    *,
    metric_kind: str = "flow",
    ownership_relationship: str = "owned",
    production: bool = True,
) -> dict:
    """Return a canonical value dict for a raw transfer/settlement/balance row.

    Shape mirrors packages/shared/value.ts (native + valuation + status), but is
    intentionally compact for aggregation call sites.
    """
    amount = to_decimal_string(_first(record, _AMOUNT_KEYS))
    currency = _first(record, _CURRENCY_KEYS)
    currency = str(currency) if currency is not None else None
    explicit_usd = to_decimal_string(_first(record, _USD_KEYS))

    if explicit_usd is not None:
        valuation = {
            "usd_value": explicit_usd, "valuation_method": "provider_reported",
            "confidence": "medium", "freshness": "recent",
            "computed_at": utc_now().isoformat(),
        }
    else:
        priced = price_sources.price(to_decimal(amount), currency)
        valuation = priced if priced is not None else {
            "usd_value": None, "valuation_method": "unavailable",
            "confidence": "unknown", "freshness": "unavailable",
            "computed_at": utc_now().isoformat(),
            "warning": "no trusted USD price within freshness window",
        }

    native = {
        "amount": amount, "currency": currency,
        "chain": record.get("chain"), "network": record.get("network"),
        "spam": record.get("spam"), "untrusted": record.get("untrusted"),
        "testnet": record.get("testnet"),
    }
    has_usd = valuation.get("usd_value") is not None
    included, exclusion = ownership_rules.rollup_inclusion(
        native, ownership_relationship=ownership_relationship,
        metric_kind=metric_kind, production=production,
    )
    include_in_rollups = has_usd and included
    exclusion_reason = None if include_in_rollups else (
        "unpriced" if not has_usd else exclusion
    )

    status: dict = {"metric_kind": metric_kind, "include_in_rollups": include_in_rollups}
    if exclusion_reason:
        status["exclusion_reason"] = exclusion_reason
    return {"native": native, "valuation": valuation, "status": status}
