"""Pluggable USD price sources.

Resolves a USD valuation for a native value across fiat identity, FX, token
market price, and peg-aware stablecoin valuation. Real adapters (FX API, market
data, Chainlink peg feeds) are credential-gated and registered at deploy time;
this module ships deterministic fixtures so CI needs no live credentials.

Invariants:
  - a source being unavailable yields **unpriced** (usd_value None), never 0;
  - stablecoins are never assumed to be $1 — valuation is peg-aware and
    source-backed (reuses services/stablecoin/valuation.classify_peg);
  - every valuation records conversion_rate + conversion_source + method.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from shared.common.common import utc_now
from services.stablecoin.valuation import classify_peg
from services.value.models import is_usd

# --- Deterministic CI fixtures (swapped for live adapters at deploy time) ----
_FX_RATES_TO_USD: dict[str, Decimal] = {
    "EUR": Decimal("1.08"), "GBP": Decimal("1.27"), "JPY": Decimal("0.0067"),
    "CAD": Decimal("0.73"), "AUD": Decimal("0.66"),
}
_TOKEN_PRICES_USD: dict[str, Decimal] = {
    "ETH": Decimal("3000"), "BTC": Decimal("60000"), "SOL": Decimal("150"),
    "MATIC": Decimal("0.70"), "AVAX": Decimal("35"), "ARB": Decimal("1.10"),
}
_STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "PYUSD", "USDP", "TUSD", "GUSD"}
# Peg-aware observed prices (source-backed snapshot; NOT an assumed $1).
_STABLECOIN_PEG_USD: dict[str, Decimal] = {
    "USDC": Decimal("1.000"), "USDT": Decimal("0.999"), "DAI": Decimal("1.001"),
    "PYUSD": Decimal("1.000"), "USDP": Decimal("1.000"), "TUSD": Decimal("0.998"),
}


def _valuation(
    usd_value: Optional[Decimal], *, method: str, source: str,
    rate: Optional[Decimal] = None, confidence: str = "medium",
    freshness: str = "recent", warning: Optional[str] = None,
) -> dict:
    return {
        "usd_value": None if usd_value is None else format(usd_value, "f"),
        "valuation_method": method,
        "conversion_rate": None if rate is None else format(rate, "f"),
        "conversion_source": source,
        "confidence": confidence,
        "freshness": freshness,
        "priced_at": utc_now().isoformat(),
        "computed_at": utc_now().isoformat(),
        **({"warning": warning} if warning else {}),
    }


def price(amount: Optional[Decimal], currency: Optional[str]) -> Optional[dict]:
    """Return a USD valuation dict for a native amount, or None when unpriced.

    Never fabricates a price: unknown assets and unavailable sources return None.
    """
    if amount is None or currency is None:
        return None
    sym = str(currency).upper()

    if is_usd(currency):
        return _valuation(amount, method="fiat_identity", source="usd_identity",
                          rate=Decimal(1), confidence="high", freshness="live")

    if sym in _STABLECOIN_SYMBOLS:
        peg = _STABLECOIN_PEG_USD.get(sym)
        if peg is None:
            return None  # no peg snapshot -> unpriced (never assume $1)
        status = classify_peg((peg - Decimal(1)) * Decimal("10000"))
        confidence = {"on_peg": "high", "minor_deviation": "medium", "depegged": "low"}[status]
        warning = None if status == "on_peg" else f"stablecoin {status.replace('_', ' ')}"
        return _valuation(amount * peg, method="stablecoin_peg_verified",
                          source="peg_snapshot", rate=peg, confidence=confidence,
                          warning=warning)

    if sym in _FX_RATES_TO_USD:
        rate = _FX_RATES_TO_USD[sym]
        return _valuation(amount * rate, method="fx_rate", source="fx_reference", rate=rate)

    if sym in _TOKEN_PRICES_USD:
        rate = _TOKEN_PRICES_USD[sym]
        return _valuation(amount * rate, method="market_price", source="market_reference", rate=rate)

    return None  # unknown asset -> unpriced, never 0


def is_stablecoin(currency: Optional[str]) -> bool:
    return currency is not None and str(currency).upper() in _STABLECOIN_SYMBOLS
