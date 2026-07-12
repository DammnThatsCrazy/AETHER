"""LTV (lifetime value) rules — prompt §4.9.

Pure computation. LTV here is *lifetime value* (realized + predicted economic
value), not loan-to-value. All monetary results are Decimal strings or ``None``;
absence is never coerced to ``0``.

Realized value is summed USD-first through ``rollups.safe_rollup`` (which uses
``price_sources``): an event's explicit ``value_usd`` wins, otherwise its
``amount`` + ``currency`` is priced. Anything unpriced is carried as
``excluded_unpriced`` and never silently zeroed.

Every result dict carries the §4.9 common fields:
``window``, ``confidence``, ``usd_basis``, ``source_event_count``,
``excluded_unpriced``.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from services.value.models import to_decimal, to_decimal_string
from services.value.valuation import value_of


def _window_bounds(window: object) -> tuple[Optional[str], Optional[str]]:
    """Extract (start, end) ISO strings from a window, or (None, None)."""
    if window is None:
        return None, None
    if isinstance(window, dict):
        return window.get("start"), window.get("end")
    if isinstance(window, (tuple, list)) and len(window) == 2:
        return window[0], window[1]
    return None, None


def _in_window(events: Iterable[dict], window: object) -> list:
    start, end = _window_bounds(window)
    if start is None and end is None:
        return list(events)
    kept = []
    for e in events:
        occurred = e.get("occurred_at")
        if occurred is None:  # undated events are kept (cannot exclude safely)
            kept.append(e)
            continue
        if start is not None and occurred < start:
            continue
        if end is not None and occurred > end:
            continue
        kept.append(e)
    return kept


def historical_ltv(events: Iterable[dict], *, window: object = None) -> dict:
    """Sum of realized USD value over ``window`` (USD-first, unpriced != 0).

    Events look like ``{"value_usd": "12.50"}`` (USD-only, no native amount) or
    ``{"amount": "2", "currency": "ETH", "occurred_at": "2026-01-01T..."}``.
    Each event's USD is resolved via ``value_of`` (explicit ``value_usd`` wins,
    otherwise the amount+currency is priced); unpriced events are counted, never
    summed as zero.
    """
    filtered = _in_window(events, window)
    total = Decimal(0)
    any_usd = False
    unpriced = 0
    for event in filtered:
        usd = to_decimal(value_of(event, metric_kind="revenue")["valuation"]["usd_value"])
        if usd is None:
            unpriced += 1
        else:
            total += usd
            any_usd = True

    usd_basis = format(total, "f") if any_usd else None
    source_event_count = len(filtered)

    if source_event_count == 0:
        confidence = "unknown"
    elif unpriced == 0:
        confidence = "high"
    elif usd_basis is None:
        confidence = "low"
    else:
        confidence = "medium"

    return {
        "window": window,
        "confidence": confidence,
        "usd_basis": usd_basis,
        "source_event_count": source_event_count,
        "unpriced_count": unpriced,
        "excluded_unpriced": unpriced,
    }


def predicted_ltv(
    *,
    model: Optional[str] = None,
    model_version: Optional[str] = None,
    predicted_usd: object = None,
    confidence: str = "low",
) -> dict:
    """Carry a model's predicted lifetime value. ``predicted_usd`` is a Decimal
    string or ``None`` — absence is never coerced to ``0``.
    """
    pu = to_decimal_string(predicted_usd)
    return {
        "model": model,
        "model_version": model_version,
        "predicted_usd": pu,
        "usd_basis": pu,
        "confidence": confidence,
        "window": None,
        "source_event_count": 0,
        "unpriced_count": 0,
        "excluded_unpriced": 0,
    }


def net_ltv(gross_usd: Optional[str], cost_usd: Optional[str]) -> Optional[str]:
    """Gross lifetime value minus cost. ``None`` when ``gross_usd`` is ``None``."""
    if gross_usd is None:
        return None
    return format(Decimal(gross_usd) - Decimal(cost_usd or "0"), "f")
