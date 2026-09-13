"""Static-snapshot FX PriceProvider for services.value.price_sources.

Program 5 (multi-currency), M1 — "register a real FX provider (zero
behavior change)" per docs/architecture/RELIABILITY-PHASE-2-PROGRAM.md §5.
This module registers one PriceProvider (see services/value/price_sources.py
for the ``PriceProvider`` / ``PriceObservation`` contract) covering the ten
fiat symbols already listed in that module's ``_FX_FIAT_SYMBOLS``:
EUR, GBP, JPY, CAD, AUD, CHF, CNY, INR, BRL, MXN.

Rate table — what it is and is not
-----------------------------------
Every rate below is a **committed, dated snapshot** captured for this change,
expressed as "USD value of one unit of the listed currency" (matching
``price_sources.price``'s ``amount * rate`` convention for ``method ==
"fx_rate"``). It is NOT a live feed and intentionally does not attempt to
track a moving market rate.

  Snapshot date:    2026-08-07
  Source:           manually captured reference-rate snapshot, recorded here
                     for audit (see ``_SNAPSHOT_SOURCE`` below)
  Refresh cadence:  NONE — this is a fixed, committed table. A production
                     build MUST wire a live source (e.g. an ECB daily
                     reference-rate pull, or a paid FX API) on at least a
                     daily cadence, fetched asynchronously and cached — never
                     a synchronous call on the ingestion/measurement write
                     path (see the Program 5 "Risks" section: "It must be
                     asynchronous and cached, never a synchronous call
                     blocking `/v1/batch` or the measurement write path").
                     Replacing this static table with a live-refreshed one is
                     explicitly out of scope for M1 and is not implemented
                     here.

Zero behavior change (M1 scope)
--------------------------------
Registering this provider only affects callers of
``services.value.price_sources.price()`` for the ten symbols above — nothing
else. As of this change, no measurement repository
(``conversion_repo.py`` / ``spend_repo.py`` / ``adjustment_repo.py``) calls
``price_sources`` at all, so this module has no effect on measurement.
Wiring measurement to pricing is Program 5 M2 and is explicitly NOT done
here. This module is also not imported from any application startup path
(``main.py`` or otherwise) as part of this change — it only takes effect
once something (a test, or a future M2 startup hook) explicitly imports it,
at which point ``register()`` runs and registers ``fx_snapshot_provider``
with the shared registry.

Invariant preserved: a symbol outside ``_SNAPSHOT_RATES`` (i.e. not one of
the ten fiat symbols this snapshot covers) returns ``None`` — unpriced,
never a fabricated 0 or 1:1 default. This matches
``services/value/price_sources.py``'s documented invariant verbatim.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from services.value.price_sources import (
    PriceObservation,
    _FX_FIAT_SYMBOLS as _KNOWN_FIAT_SYMBOLS,
    register_price_provider,
)

# USD value of one unit of the listed currency. Snapshot only — see module
# docstring for date, source, and the required production refresh plan.
_SNAPSHOT_DATE = "2026-08-07"
_SNAPSHOT_SOURCE = f"fx_snapshot_{_SNAPSHOT_DATE}"
_SNAPSHOT_RATES: dict[str, Decimal] = {
    "EUR": Decimal("1.08"),
    "GBP": Decimal("1.27"),
    "JPY": Decimal("0.0067"),
    "CAD": Decimal("0.73"),
    "AUD": Decimal("0.65"),
    "CHF": Decimal("1.11"),
    "CNY": Decimal("0.14"),
    "INR": Decimal("0.012"),
    "BRL": Decimal("0.18"),
    "MXN": Decimal("0.055"),
}

# Every symbol here must also appear in price_sources._FX_FIAT_SYMBOLS, or
# price_sources.price() would classify it as a token market_price instead of
# an fx_rate valuation. Checked at import time so drift between the two
# tables fails loudly instead of silently mis-tagging a valuation method.
_unknown = set(_SNAPSHOT_RATES) - set(_KNOWN_FIAT_SYMBOLS)
if _unknown:
    raise AssertionError(
        f"fx_provider snapshot covers symbols not in price_sources._FX_FIAT_SYMBOLS: {_unknown}"
    )


def fx_snapshot_provider(symbol: str) -> Optional[PriceObservation]:
    """PriceProvider: resolve a snapshot USD rate for a known fiat symbol.

    ``symbol`` arrives pre-uppercased from ``price_sources.price()``. Returns
    ``None`` (unpriced) for any symbol not in ``_SNAPSHOT_RATES`` — never a
    fabricated 0 or 1:1 rate.
    """
    rate = _SNAPSHOT_RATES.get(symbol)
    if rate is None:
        return None
    # (rate, source, freshness, confidence) — see PriceObservation contract.
    # freshness/confidence values are drawn from services.value.models'
    # canonical FRESHNESS / CONFIDENCE enums: this is a dated, non-live
    # snapshot, so "recent" (not "live") + "medium" (not "high") confidence.
    return (rate, _SNAPSHOT_SOURCE, "recent", "medium")


def register() -> None:
    """Idempotently register ``fx_snapshot_provider`` with price_sources."""
    register_price_provider(fx_snapshot_provider)


# Self-registering module: importing this module registers the provider.
# This is intentional (see "Zero behavior change" above) — no production
# startup path imports this module as part of M1, so registration only
# activates when a caller (today: this module's tests) explicitly imports
# it.
register()
