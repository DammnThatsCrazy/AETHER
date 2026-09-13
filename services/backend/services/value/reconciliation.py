"""Reconciliation state resolution for a value observed across sources."""
from __future__ import annotations

from typing import Optional

RECONCILIATION_STATES = frozenset({
    "sdk_only", "provider_only", "matched", "stale", "conflict",
    "ignored_duplicate", "unreconciled", "not_applicable",
})


def reconcile(
    *,
    sdk_present: bool,
    provider_present: bool,
    amounts_match: Optional[bool] = None,
    stale: bool = False,
    duplicate: bool = False,
) -> str:
    """Resolve the reconciliation state from cross-source presence + agreement."""
    if duplicate:
        return "ignored_duplicate"
    if stale:
        return "stale"
    if sdk_present and provider_present:
        if amounts_match is False:
            return "conflict"
        return "matched"
    if provider_present:
        return "provider_only"
    if sdk_present:
        return "sdk_only"
    return "unreconciled"
