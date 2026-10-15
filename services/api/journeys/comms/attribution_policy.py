"""Comms attribution eligibility policy (Phase 16, ADR-C8).

Consumed by the existing attribution engine — there is no second engine.
The policy decides whether a campaign touchpoint may carry positive credit:

- delivery observations are context only (never credited),
- provider-reported opens are excluded by default (optional low-confidence
  view-through when the tenant enables it),
- machine-classified engagement never reaches touchpoints at all (gated in
  TouchpointProjector), and any legacy rows carrying machine probability are
  excluded here as defense in depth,
- human-qualified clicks are eligible,
- replies are eligible when tenant configuration permits,
- transactional messages never earn acquisition credit,
- unsubscribes/complaints are negative outcomes and never appear as
  positive-engagement touchpoints (also gated upstream).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CommsAttributionConfig:
    """Tenant-configurable comms eligibility switches."""
    reported_opens_as_view_through: bool = False
    replies_eligible: bool = True
    machine_probability_cutoff: float = 0.7


DEFAULT_CONFIG = CommsAttributionConfig()

# Touchpoint types this policy governs; everything else passes through to
# the engine's existing rules untouched.
_COMMS_TOUCHPOINT_TYPES = frozenset({
    "email_delivery", "email_open", "email_click", "email_reply",
    "push_presentation", "push_click",
})

_CONTEXT_ONLY = frozenset({"email_delivery", "push_presentation"})


def comms_touchpoint_eligibility(
    touchpoint: dict[str, Any],
    config: Optional[CommsAttributionConfig] = None,
) -> tuple[bool, Optional[str]]:
    """Return (eligible, exclusion_reason) for one touchpoint row.

    Non-comms touchpoints are always eligible from this policy's perspective.
    """
    cfg = config or DEFAULT_CONFIG
    tp_type = touchpoint.get("touchpoint_type", "")
    if tp_type not in _COMMS_TOUCHPOINT_TYPES:
        return True, None

    machine_prob = touchpoint.get("machine_activity_probability")
    try:
        if machine_prob is not None and float(machine_prob) >= cfg.machine_probability_cutoff:
            return False, "machine_activity"
    except (TypeError, ValueError):
        pass

    if tp_type in _CONTEXT_ONLY:
        return False, "delivery_context_only"
    if tp_type == "email_open":
        if cfg.reported_opens_as_view_through:
            return True, None  # engine treats it as view-through weighting
        return False, "reported_open_excluded"
    if tp_type == "email_reply":
        if cfg.replies_eligible:
            return True, None
        return False, "reply_ineligible_by_config"
    # email_click / push_click — human-qualified by upstream gating
    return True, None


def message_category_attribution_eligible(category: Optional[str]) -> bool:
    """Transactional/security/account messages never earn acquisition credit."""
    return category not in ("transactional", "security", "account", "operational")
