"""Exposure-aware attribution.

Joins each conversion's journey to the impression log (Iceberg `exposures`)
and grants un-clicked impressions a fractional credit, defaulting to
`exposure_weight = 0.1` (per project policy).

This module is the model side; the ETL caller in
`Data Lake Architecture/.../etl/journey_pipeline.ts` invokes it nightly.
The output shape matches `gold_attribution_actor_weighted`'s
`exposure_weighted_conversions` / `exposure_weighted_revenue` columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


DEFAULT_EXPOSURE_WEIGHT: float = 0.1


@dataclass(frozen=True)
class Touch:
    channel: str
    campaign: str
    is_click: bool   # True if the surface was clicked, False if only viewed


@dataclass(frozen=True)
class JourneyConversion:
    project_id: str
    journey_id: str
    actor_kind: str
    revenue: float
    touches: tuple[Touch, ...]


def _normalize(weights: Mapping[tuple[str, str], float]) -> dict[tuple[str, str], float]:
    total = sum(weights.values())
    if total <= 0:
        return {k: 0.0 for k in weights}
    return {k: v / total for k, v in weights.items()}


def attribute(
    conversions: Iterable[JourneyConversion],
    *,
    exposure_weight: float = DEFAULT_EXPOSURE_WEIGHT,
) -> list[dict]:
    """For each conversion, return per-(channel, campaign) credit.

    Click touches receive weight 1.0, viewed-only impressions receive
    `exposure_weight`. Weights are normalized to sum to 1.0 inside each
    journey so revenue is conserved.
    """
    out: list[dict] = []
    for conv in conversions:
        raw_weights: dict[tuple[str, str], float] = {}
        for t in conv.touches:
            key = (t.channel, t.campaign)
            raw_weights[key] = raw_weights.get(key, 0.0) + (1.0 if t.is_click else exposure_weight)
        normalized = _normalize(raw_weights)
        for (channel, campaign), w in normalized.items():
            out.append({
                "project_id": conv.project_id,
                "journey_id": conv.journey_id,
                "actor_kind": conv.actor_kind,
                "channel": channel,
                "campaign": campaign,
                "exposure_weighted_conversions": w,
                "exposure_weighted_revenue": conv.revenue * w,
            })
    return out
