"""Slot freshness verdicts from source watermarks.

A surface's ``freshnessPolicy.slots`` maps a slot to its ``maxAgeSeconds`` and
the canonical authorities whose watermarks bound it. A slot is as current as
its least-current source: the oldest watermark decides. Any listed source
without a watermark leaves the slot ``unknown``; nothing here infers freshness
from record timestamps or from the absence of records.

Operators override thresholds per deployment with the JSON environment
variable ``EXPERIENCE360_FRESHNESS_MAX_AGE_OVERRIDES``, for example
``{"profile360": {"risk_summary": 3600}}``. Invalid entries are ignored.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from shared.intelligence_projections.contracts import Experience360Freshness

OVERRIDES_ENV = "EXPERIENCE360_FRESHNESS_MAX_AGE_OVERRIDES"


def _overrides(surface_id: str) -> dict[str, int]:
    raw = os.getenv(OVERRIDES_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    surface = parsed.get(surface_id) if isinstance(parsed, dict) else None
    if not isinstance(surface, dict):
        return {}
    return {
        slot: value
        for slot, value in surface.items()
        if isinstance(slot, str) and isinstance(value, int) and not isinstance(value, bool) and value > 0
    }


def slot_freshness_policies(surface: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``{slot_id: {"maxAgeSeconds": int, "watermarkAuthorities": [...]}}``."""
    policy = surface.get("freshnessPolicy")
    slots = policy.get("slots") if isinstance(policy, Mapping) else None
    if not isinstance(slots, Mapping):
        return {}
    overrides = _overrides(str(surface.get("id", "")))
    resolved: dict[str, dict[str, Any]] = {}
    for slot_id, entry in slots.items():
        if not isinstance(entry, Mapping):
            continue
        max_age = overrides.get(slot_id, entry.get("maxAgeSeconds"))
        authorities = entry.get("watermarkAuthorities")
        if not isinstance(max_age, int) or max_age <= 0 or not isinstance(authorities, (list, tuple)) or not authorities:
            continue
        resolved[slot_id] = {"maxAgeSeconds": max_age, "watermarkAuthorities": list(authorities)}
    return resolved


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def evaluate_slot_freshness(
    policies: Mapping[str, Mapping[str, Any]],
    slot_ids: list[str],
    watermarks: Mapping[str, Optional[str]],
    evaluated_at: str,
) -> dict[str, Experience360Freshness]:
    """Return a freshness verdict for each requested slot that has a policy."""
    evaluated = _parse(evaluated_at) or datetime.now(timezone.utc)
    verdicts: dict[str, Experience360Freshness] = {}
    for slot_id in slot_ids:
        policy = policies.get(slot_id)
        if policy is None:
            continue
        max_age = float(policy["maxAgeSeconds"])
        instants = [_parse(watermarks.get(authority)) for authority in policy["watermarkAuthorities"]]
        if any(instant is None for instant in instants):
            verdicts[slot_id] = Experience360Freshness(
                state="unknown", evaluatedAt=evaluated_at, maxAgeSeconds=max_age,
            )
            continue
        oldest = min(instants)  # type: ignore[type-var]
        age = max(0.0, (evaluated - oldest).total_seconds())
        verdicts[slot_id] = Experience360Freshness(
            state="fresh" if age <= max_age else "stale",
            sourceAsOf=oldest.isoformat(),
            evaluatedAt=evaluated_at,
            ageSeconds=age,
            maxAgeSeconds=max_age,
        )
    return verdicts
