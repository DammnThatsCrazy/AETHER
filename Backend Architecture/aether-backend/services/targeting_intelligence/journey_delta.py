"""Journey deltas, frequency pressure / overexposure, and negative outcome
attribution — all in observational (correlated, not causal) language."""

from __future__ import annotations

from typing import Any, Optional

from services.targeting_intelligence.models import (
    ClusterJourneyDelta,
    EvidenceRef,
    NegativeOutcomes,
    TimeRangeFilter,
)

# Touches per entity in the window beyond which a cluster reads overexposed.
OVEREXPOSURE_TOUCH_THRESHOLD = 8
# Overexposure score above which an overexposed-exclusion is recommended.
OVEREXPOSURE_RECOMMEND_THRESHOLD = 0.7


def compute_journey_delta(
    *,
    tenant_id: str,
    campaign_id: str,
    cluster_id: str,
    before_stage_counts: dict[str, int],
    after_stage_counts: dict[str, int],
    before_window: dict[str, Any],
    after_window: dict[str, Any],
    compared_to_cluster_ids: Optional[list[str]] = None,
    holdout_cluster_ids: Optional[list[str]] = None,
    evidence_refs: Optional[list[EvidenceRef]] = None,
) -> ClusterJourneyDelta:
    """Stage-count deltas between two observation windows for one cluster."""
    stages = sorted(set(before_stage_counts) | set(after_stage_counts))
    deltas = {
        stage: float(after_stage_counts.get(stage, 0) - before_stage_counts.get(stage, 0))
        for stage in stages
    }
    reached = after_stage_counts.get("reached", 0)
    engaged = after_stage_counts.get("engaged", 0)
    converted = after_stage_counts.get("converted", 0)
    attributed = after_stage_counts.get("attributed", 0)
    non_progressed = max(0, reached - engaged)
    progressed_elsewhere = max(0, engaged - converted - non_progressed) \
        if engaged > converted else 0

    return ClusterJourneyDelta(
        tenantId=tenant_id,
        campaignId=campaign_id,
        clusterId=cluster_id,
        comparedToClusterIds=compared_to_cluster_ids,
        holdoutClusterIds=holdout_cluster_ids,
        beforeWindow=TimeRangeFilter.model_validate(before_window),
        afterWindow=TimeRangeFilter.model_validate(after_window),
        populationStageDeltas=deltas,
        reachedCount=reached,
        engagedCount=engaged,
        convertedCount=converted,
        attributedCount=attributed,
        nonProgressedCount=non_progressed,
        progressedElsewhereCount=progressed_elsewhere,
        evidenceRefs=evidence_refs or [],
    )


def overexposure_score(touches_per_entity: list[int]) -> float:
    """Share of entities touched beyond the threshold, weighted by excess.

    0.0 = nobody overexposed; 1.0 = every observed entity far beyond the
    threshold. Deterministic and bounded.
    """
    if not touches_per_entity:
        return 0.0
    scores = []
    for touches in touches_per_entity:
        if touches <= OVEREXPOSURE_TOUCH_THRESHOLD:
            scores.append(0.0)
        else:
            excess = touches - OVEREXPOSURE_TOUCH_THRESHOLD
            scores.append(min(1.0, excess / OVEREXPOSURE_TOUCH_THRESHOLD))
    return round(sum(scores) / len(scores), 4)


def is_overexposed(score: float) -> bool:
    return score >= OVEREXPOSURE_RECOMMEND_THRESHOLD


def attribute_negative_outcomes(outcome_counts: dict[str, int]) -> NegativeOutcomes:
    """Correlated negative-outcome counts observed in the targeting window."""
    return NegativeOutcomes(
        unsubscribes=int(outcome_counts.get("unsubscribes", 0)),
        complaints=int(outcome_counts.get("complaints", 0)),
        churnSignals=int(outcome_counts.get("churn_signals", 0)),
        fraudSignals=int(outcome_counts.get("fraud_signals", 0)),
        refunds=int(outcome_counts.get("refunds", 0)),
        supportBurden=int(outcome_counts.get("support_burden", 0)),
        overexposureSignals=int(outcome_counts.get("overexposure_signals", 0)),
    )
