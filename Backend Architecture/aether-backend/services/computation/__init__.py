"""Service-level orchestration for the Computation Substrate.

Where ``shared/computation`` is the pure contract layer, ``services/computation``
composes it with the rest of the platform (value/rollups, jobs/workers,
repositories, routes) to actually run, persist, allocate, reconcile, restate, and
explain canonical computations.

This package is the authoritative home for domain computations migrated onto the
substrate. ``campaign.py`` is the first migrated vertical (campaign / journey
economics).
"""

from __future__ import annotations

from services.computation.campaign import (
    CampaignAggregates,
    canonical_campaign_metrics,
    canonical_journey_allocated_cost,
)

__all__ = [
    "CampaignAggregates",
    "canonical_campaign_metrics",
    "canonical_journey_allocated_cost",
]
