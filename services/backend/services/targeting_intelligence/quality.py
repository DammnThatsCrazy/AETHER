"""Provider mapping quality — decides whether targeting suggestions are safe.

Low-quality provider mapping (poor identity/touchpoint/cluster resolution or
stale sync) BLOCKS suggestion generation rather than emitting low-confidence
advice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services.targeting_intelligence.models import ProviderMappingQuality, utc_now_iso

# Below this quality score, targeting suggestions are blocked.
QUALITY_BLOCK_THRESHOLD = 0.6
# Sync freshness bands.
FRESH_LIVE = timedelta(minutes=15)
FRESH_RECENT = timedelta(hours=24)

_WEIGHTS = {
    "mapping_rate": 0.30,
    "touchpoint_resolution_rate": 0.20,
    "identity_resolution_rate": 0.25,
    "cluster_assignment_rate": 0.25,
}


def _freshness(last_sync_at: Optional[str]) -> str:
    if not last_sync_at:
        return "unknown"
    try:
        sync_time = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    age = datetime.now(timezone.utc) - sync_time
    if age <= FRESH_LIVE:
        return "live"
    if age <= FRESH_RECENT:
        return "recent"
    return "stale"


def compute_mapping_quality(
    *,
    campaign_id: Optional[str] = None,
    provider: Optional[str] = None,
    mapping_rate: float = 0.0,
    touchpoint_resolution_rate: float = 0.0,
    identity_resolution_rate: float = 0.0,
    cluster_assignment_rate: float = 0.0,
    unresolved_alias_count: int = 0,
    last_sync_at: Optional[str] = None,
) -> ProviderMappingQuality:
    """Deterministic quality score from the observable resolution rates."""
    rates: dict[str, float] = {
        "mapping_rate": mapping_rate,
        "touchpoint_resolution_rate": touchpoint_resolution_rate,
        "identity_resolution_rate": identity_resolution_rate,
        "cluster_assignment_rate": cluster_assignment_rate,
    }
    quality = sum(_WEIGHTS[name] * value for name, value in rates.items())
    freshness = _freshness(last_sync_at)
    if freshness == "stale":
        quality *= 0.75
    elif freshness == "unknown":
        quality *= 0.9

    reasons: list[str] = []
    for name, value in rates.items():
        if value < 0.5:
            reasons.append(f"{name} below 0.5 (observed {value:.2f})")
    if freshness in ("stale", "unknown"):
        reasons.append(f"provider sync freshness is {freshness}")
    if unresolved_alias_count > 0:
        reasons.append(f"{unresolved_alias_count} unresolved provider aliases")

    blocks = quality < QUALITY_BLOCK_THRESHOLD
    if blocks:
        reasons.append(
            f"quality score {quality:.2f} below suggestion threshold {QUALITY_BLOCK_THRESHOLD}"
        )

    return ProviderMappingQuality(
        campaignId=campaign_id,
        provider=provider,
        mappingRate=mapping_rate,
        providerSyncFreshness=freshness,  # type: ignore[arg-type]
        unresolvedAliasCount=unresolved_alias_count,
        touchpointResolutionRate=touchpoint_resolution_rate,
        identityResolutionRate=identity_resolution_rate,
        clusterAssignmentRate=cluster_assignment_rate,
        qualityScore=round(min(1.0, max(0.0, quality)), 4),
        blocksSuggestions=blocks,
        reasons=reasons,
        computedAt=utc_now_iso(),
    )


def quality_from_observation_inputs(inputs: dict[str, Any]) -> ProviderMappingQuality:
    """Build quality from a raw observation-input dict (route/service seam)."""
    return compute_mapping_quality(
        campaign_id=inputs.get("campaignId"),
        provider=inputs.get("provider"),
        mapping_rate=float(inputs.get("mappingRate", 0.0)),
        touchpoint_resolution_rate=float(inputs.get("touchpointResolutionRate", 0.0)),
        identity_resolution_rate=float(inputs.get("identityResolutionRate", 0.0)),
        cluster_assignment_rate=float(inputs.get("clusterAssignmentRate", 0.0)),
        unresolved_alias_count=int(inputs.get("unresolvedAliasCount", 0)),
        last_sync_at=inputs.get("lastSyncAt"),
    )
