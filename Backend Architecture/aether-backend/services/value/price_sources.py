"""Pluggable USD price sources.

Resolves a USD valuation for a native value across fiat identity, FX, token
market price, and peg-aware stablecoin valuation. Real adapters (FX API, market
data, Chainlink peg feeds) register observed rates at deploy time. No runtime
reference prices are bundled.

Invariants:
  - a source being unavailable yields **unpriced** (usd_value None), never 0;
  - stablecoins are never assumed to be $1 — valuation is peg-aware and
    source-backed (reuses services/stablecoin/valuation.classify_peg);
  - every valuation records conversion_rate + conversion_source + method.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from shared.common.common import utc_now
from services.stablecoin.valuation import classify_peg
from services.value.models import is_usd

_STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "PYUSD", "USDP", "TUSD", "GUSD"}
_FX_FIAT_SYMBOLS = frozenset({"EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "BRL", "MXN"})
PriceObservation = tuple[Decimal, str, str, str]
PriceProvider = Callable[[str], Optional[PriceObservation]]
_providers: list[PriceProvider] = []


def register_price_provider(provider: PriceProvider) -> None:
    """Register a canonical observed-rate provider."""
    if provider not in _providers:
        _providers.append(provider)


def clear_price_providers() -> None:
    """Clear process-local provider registrations (startup/test lifecycle)."""
    _providers.clear()


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

    observation = next(
        (observed for provider in _providers if (observed := provider(sym)) is not None),
        None,
    )
    if observation is None:
        return None
    rate, source, freshness, observed_confidence = observation

    if sym in _STABLECOIN_SYMBOLS:
        peg = rate
        status = classify_peg((peg - Decimal(1)) * Decimal("10000"))
        confidence = (
            "low"
            if status == "depegged"
            else observed_confidence
        )
        warning = None if status == "on_peg" else f"stablecoin {status.replace('_', ' ')}"
        return _valuation(amount * peg, method="stablecoin_peg_verified",
                          source=source, rate=peg, confidence=confidence,
                          freshness=freshness, warning=warning)

    # "Three alpha chars" is not fiat — ETH/BTC/SOL all match. Only symbols in
    # the known fiat set are FX conversions; everything else observed is a
    # token market price.
    method = "fx_rate" if sym in _FX_FIAT_SYMBOLS else "market_price"
    return _valuation(
        amount * rate,
        method=method,
        source=source,
        rate=rate,
        confidence=observed_confidence,
        freshness=freshness,
    )


def is_stablecoin(currency: Optional[str]) -> bool:
    return currency is not None and str(currency).upper() in _STABLECOIN_SYMBOLS
