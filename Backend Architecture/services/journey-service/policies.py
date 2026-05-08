"""Journey-boundary policy resolution.

Defaults are inactivity=30d and new-origin breaks; overridable per project
via the `journey_policies` Postgres table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_CONVERSION_TYPES: tuple[str, ...] = (
    "payment_completed",
    "entitlement_granted",
    "conversion",
)


@dataclass(frozen=True)
class JourneyPolicy:
    project_id: str
    inactivity_window_days: int = 30
    new_origin_breaks: bool = True
    conversion_event_types: tuple[str, ...] = DEFAULT_CONVERSION_TYPES
    cross_journey_lookback_days: int = 365
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def inactivity_window_seconds(self) -> int:
        return self.inactivity_window_days * 86_400


class PolicyResolver:
    """Caches per-project policies. In prod, reads from Postgres + Redis."""

    def __init__(self) -> None:
        self._cache: dict[str, JourneyPolicy] = {}

    async def get(self, project_id: str) -> JourneyPolicy:
        cached = self._cache.get(project_id)
        if cached:
            return cached
        # --- PRODUCTION: SELECT FROM journey_policies WHERE project_id = $1 ---
        policy = JourneyPolicy(project_id=project_id)
        self._cache[project_id] = policy
        return policy

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)


def attribution_origin(event: dict) -> str:
    """Stable origin key derived from campaign + referrer.

    Two events that share the same origin should NOT split a journey;
    a different origin DOES split (per `new_origin_breaks=True`).
    """
    ctx = event.get("context", {}) or {}
    campaign = (ctx.get("campaign") or {}) if isinstance(ctx.get("campaign"), dict) else {}
    source   = campaign.get("source") or "direct"
    name     = campaign.get("campaign") or ""
    ref_dom  = campaign.get("referrerDomain") or ""
    return f"{source}|{name}|{ref_dom}"


def is_conversion(event: dict, policy: JourneyPolicy) -> bool:
    return event.get("type") in policy.conversion_event_types
