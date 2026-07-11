"""Value normalization — turn a raw record into a native value + USD valuation.

USD valuation policy (no live third-party credentials required):
  - currency USD                     -> fiat_identity, usd_value = amount, high
  - explicit value_usd / amount_usd  -> provider_reported, usd_value = that
  - anything else (fx/token/unknown) -> unavailable, usd_value = None (unpriced)

Unpriced is NEVER zero. FX and market pricing are provided by the pluggable
price-source layer at a higher level; here we only trust identities and
provider-reported USD so CI is deterministic.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import utc_now
from services.value.models import is_usd, to_decimal_string

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


def value_of(record: dict, *, metric_kind: str = "flow") -> dict:
    """Return a canonical value dict for a raw transfer/settlement/balance row.

    Shape mirrors packages/shared/value.ts (native + valuation + status), but is
    intentionally compact for aggregation call sites.
    """
    amount = to_decimal_string(_first(record, _AMOUNT_KEYS))
    currency = _first(record, _CURRENCY_KEYS)
    currency = str(currency) if currency is not None else None
    explicit_usd = to_decimal_string(_first(record, _USD_KEYS))

    usd_value: Optional[str] = None
    method = "unavailable"
    confidence = "unknown"
    freshness = "unavailable"
    warning: Optional[str] = None

    if explicit_usd is not None:
        usd_value = explicit_usd
        method = "provider_reported"
        confidence = "medium"
        freshness = "recent"
    elif is_usd(currency) and amount is not None:
        usd_value = amount
        method = "fiat_identity"
        confidence = "high"
        freshness = "live"
    else:
        # No trusted USD price. Unknown != 0 — leave usd_value None.
        warning = "no trusted USD price within freshness window"

    priced = usd_value is not None
    return {
        "native": {"amount": amount, "currency": currency},
        "valuation": {
            "usd_value": usd_value,
            "valuation_method": method,
            "confidence": confidence,
            "freshness": freshness,
            "computed_at": utc_now().isoformat(),
            **({"warning": warning} if warning else {}),
        },
        "status": {
            "metric_kind": metric_kind,
            "include_in_rollups": priced,
            **({} if priced else {"exclusion_reason": "unpriced"}),
        },
    }
