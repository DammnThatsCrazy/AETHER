"""Kyber financial-diagnostics helpers (§4.19).

Pure, tenant-safe transforms over the canonical value dict shapes produced by
``services/value`` (``value_of`` / ``safe_rollup``, mirroring
``packages/shared/value.ts`` ``AetherValue`` / ``RollupResult``). These helpers
*explain* a value or a rollup for Kyber's financial-diagnostics surfaces — they
never fetch, never touch tenant state, and never coerce an absent value to zero.

Two entry points:

* ``diagnose_rollup(rollup)`` — rollup-level health: valuation status,
  stale/unpriced/conflict counts, completeness, reconciliation state, and an
  aggregate why-included / why-excluded narrative.
* ``value_status(aether_value)`` — per-value status: valuation status, price
  source, ``priced_at``, ownership relationship + confidence, reconciliation
  state, and why the value is (or is not) in a trusted rollup.

Invariant: monetary absences (``total_usd`` / ``usd_value`` == ``None``) are
preserved as ``None``. They are NEVER turned into ``0``. Counts (which the
canonical ``RollupResult`` always emits as integers) default to ``0`` only when
a caller omits them entirely.
"""
from __future__ import annotations

from typing import Any, Optional


def _as_count(value: object) -> int:
    """Coerce an integer count field, defaulting a missing/invalid one to 0.

    This applies ONLY to count fields (which are structurally non-monetary).
    Monetary fields are handled separately and their ``None`` is preserved.
    """
    if isinstance(value, bool):  # guard: bool is an int subclass
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def diagnose_rollup(rollup: dict) -> dict:
    """Diagnose a ``RollupResult`` (or ``safe_rollup`` output) dict.

    Reads the canonical rollup shape (``total_usd`` decimal-string-or-None,
    ``by_native_currency`` buckets, ``*_count`` integers, ``rollup_status``) and
    returns a structured diagnostic. ``total_usd`` is echoed verbatim so an
    absent trusted total stays ``None`` rather than ``0``.
    """
    r = _as_dict(rollup)

    # Monetary field: preserve None (never coerce to 0).
    total_usd: Optional[str] = r.get("total_usd")
    has_trusted_total = total_usd is not None

    valuation_status = r.get("rollup_status") or "unavailable"
    by_currency = _as_dict(r.get("by_native_currency"))

    unpriced_count = _as_count(r.get("unpriced_count"))
    stale_count = _as_count(r.get("stale_count"))
    excluded_count = _as_count(r.get("excluded_count"))
    # RollupResult has no dedicated conflict_count; honor one if a caller supplies
    # it, else infer a conflicted rollup as a single conflict signal.
    conflict_count = _as_count(r.get("conflict_count"))
    if conflict_count == 0 and valuation_status == "conflicted":
        conflict_count = 1

    priced_currencies: list[str] = []
    unpriced_currencies: list[str] = []
    priced_records = 0
    total_records = 0
    for currency, bucket in by_currency.items():
        b = _as_dict(bucket)
        count = _as_count(b.get("count"))
        total_records += count
        if b.get("priced"):
            priced_currencies.append(str(currency))
            priced_records += count
        else:
            unpriced_currencies.append(str(currency))

    # Completeness ratio: None when there is nothing to divide (an absence, not 0%).
    completeness_ratio: Optional[float] = None
    if total_records > 0:
        completeness_ratio = round(priced_records / total_records, 4)

    why_included: list[str] = []
    if priced_currencies:
        why_included.append(
            "priced native currencies: " + ", ".join(sorted(priced_currencies))
        )
    if has_trusted_total:
        why_included.append("trusted USD total available")

    why_excluded: list[str] = []
    if unpriced_count:
        why_excluded.append(
            f"{unpriced_count} value(s) unpriced — no trusted USD valuation"
        )
    if excluded_count:
        why_excluded.append(
            f"{excluded_count} value(s) excluded by ownership/policy rules"
        )
    if stale_count:
        why_excluded.append(f"{stale_count} value(s) stale")
    if conflict_count:
        why_excluded.append(f"{conflict_count} value(s) in reconciliation conflict")
    if unpriced_currencies:
        why_excluded.append(
            "unpriced native currencies: " + ", ".join(sorted(unpriced_currencies))
        )

    # Reconciliation state: use an explicit top-level state if present, else infer
    # a coarse one from the rollup status.
    reconciliation_state = r.get("reconciliation_state")
    if reconciliation_state is None:
        reconciliation_state = (
            "conflict" if valuation_status == "conflicted" else "not_applicable"
        )

    return {
        "valuation_status": valuation_status,
        "total_usd": total_usd,  # None preserved — never coerced to 0
        "has_trusted_total": has_trusted_total,
        "is_complete": valuation_status == "complete",
        "currency_count": len(by_currency),
        "priced_currencies": sorted(priced_currencies),
        "unpriced_currencies": sorted(unpriced_currencies),
        "unpriced_count": unpriced_count,
        "stale_count": stale_count,
        "excluded_count": excluded_count,
        "conflict_count": conflict_count,
        "completeness": {
            "priced_records": priced_records,
            "total_records": total_records,
            "ratio": completeness_ratio,  # None when unknown — never 0
        },
        "reconciliation_state": reconciliation_state,
        "why_included": why_included,
        "why_excluded": why_excluded,
    }


def value_status(aether_value: dict) -> dict:
    """Diagnose a single canonical value dict.

    Accepts either the full ``AetherValue`` envelope or the compact
    ``value_of`` shape (``native`` / ``valuation`` / ``status`` [+ ``ownership``]).
    Surfaces valuation status, price source, ``priced_at``, ownership
    relationship + confidence, reconciliation state, and why the value is (or is
    not) rollup-eligible. ``usd_value`` is echoed verbatim so an unpriced value
    stays ``None`` — never ``0``.
    """
    v = _as_dict(aether_value)
    native = _as_dict(v.get("native"))
    valuation = _as_dict(v.get("valuation"))
    status = _as_dict(v.get("status"))
    ownership = _as_dict(v.get("ownership"))

    # Monetary field: preserve None (never coerce to 0).
    usd_value: Optional[Any] = valuation.get("usd_value")
    is_priced = usd_value is not None

    freshness = valuation.get("freshness")
    confidence = valuation.get("confidence")
    valuation_method = valuation.get("valuation_method")
    # Price source: prefer the explicit conversion source, fall back to method.
    price_source = valuation.get("conversion_source") or valuation_method
    priced_at = valuation.get("priced_at")
    warning = valuation.get("warning")

    if not is_priced:
        valuation_status = "unpriced"
    elif freshness in ("stale", "expired", "unavailable"):
        valuation_status = str(freshness)
    else:
        valuation_status = "priced"

    is_stale = freshness in ("stale", "expired")

    include_in_rollups = bool(status.get("include_in_rollups"))
    exclusion_reason = status.get("exclusion_reason")

    # Reconciliation state may live on status (canonical) or top-level (compact).
    reconciliation_state = (
        status.get("reconciliation_state") or v.get("reconciliation_state")
    )

    ownership_relationship = ownership.get("relationship")
    ownership_confidence = ownership.get("confidence")

    why_included: list[str] = []
    why_excluded: list[str] = []
    if include_in_rollups:
        why_included.append("included in trusted USD rollup")
        if price_source:
            method = valuation_method or "price source"
            why_included.append(f"priced via {method} ({price_source})")
    else:
        if exclusion_reason:
            why_excluded.append(str(exclusion_reason))
        elif not is_priced:
            why_excluded.append("unpriced")
        if warning:
            why_excluded.append(str(warning))

    return {
        "valuation_status": valuation_status,
        "is_priced": is_priced,
        "usd_value": usd_value,  # None preserved — never coerced to 0
        "native_amount": native.get("amount"),
        "native_currency": native.get("currency"),
        "freshness": freshness,
        "is_stale": is_stale,
        "confidence": confidence,
        "valuation_method": valuation_method,
        "price_source": price_source,
        "priced_at": priced_at,
        "warning": warning,
        "reconciliation_state": reconciliation_state,
        "ownership_relationship": ownership_relationship,
        "ownership_confidence": ownership_confidence,
        "include_in_rollups": include_in_rollups,
        "exclusion_reason": exclusion_reason,
        "why_included": why_included,
        "why_excluded": why_excluded,
    }
