"""Exclusion leakage detection — excluded-but-reached clusters.

Compares a TargetingObservation's reached sets against the eligibility
snapshot's excluded/suppressed/holdout sets. Language is observational:
findings report what was observed and heuristically likely causes — never
causal claims.
"""

from __future__ import annotations

from typing import Optional

from services.targeting_intelligence.models import (
    EvidenceRef,
    ExclusionLeakageFinding,
    TargetingEligibilitySnapshot,
    TargetingObservation,
)

# Leakage-rate severity bands (rate = reached / max(excluded_member_count, reached)).
SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (0.50, "critical"),
    (0.25, "high"),
    (0.10, "medium"),
    (0.02, "low"),
    (0.0, "info"),
)


def _severity(rate: float) -> str:
    for threshold, label in SEVERITY_BANDS:
        if rate >= threshold and (rate > 0 or threshold == 0.0):
            if rate == 0:
                return "info"
            return label
    return "info"


def _likely_causes(
    snapshot: TargetingEligibilitySnapshot,
    observation: TargetingObservation,
    cluster_id: str,
) -> list[str]:
    causes: list[str] = []
    reached_elsewhere = set(observation.reachedIncludedClusters) | set(
        observation.reachedReferenceClusters
    )
    if cluster_id in reached_elsewhere:
        causes.append("cluster_overlap")
    if observation.providerMappingQuality.identityResolutionRate < 0.5:
        causes.append("identity_resolved_after_launch")
    if observation.providerMappingQuality.mappingRate < 0.5:
        causes.append("utm_mapping_error")
    if observation.sourceProvider and not causes:
        causes.append("provider_ignored_exclusion")
    if not causes:
        causes.append("unknown")
    return causes


def detect_leakage(
    snapshot: TargetingEligibilitySnapshot,
    observation: TargetingObservation,
) -> list[ExclusionLeakageFinding]:
    """One finding per excluded/holdout cluster that was observed reached."""
    findings: list[ExclusionLeakageFinding] = []
    protected: list[tuple[str, str]] = [
        *[(c, "manual_tenant_exclusion") for c in snapshot.excludedClusters],
        *[(c, "negative_holdout") for c in snapshot.holdoutClusters],
    ]
    reached_excluded = set(observation.reachedExcludedClusters)
    reached_holdout = set(observation.reachedHoldoutClusters)
    reached_all = set(observation.reachedClusters) | reached_excluded | reached_holdout

    for cluster_id, reason in protected:
        if cluster_id not in reached_all:
            continue
        member_count = snapshot.clusterMemberCounts.get(cluster_id, 0)
        reached_count = sum(
            1 for e in observation.reachedEntities if e.label == cluster_id
        ) or 1  # at least the cluster-level observation itself
        denominator = max(member_count, reached_count)
        rate = min(1.0, reached_count / denominator) if denominator else 1.0

        findings.append(ExclusionLeakageFinding(
            tenantId=snapshot.tenantId,
            campaignId=observation.campaignId,
            targetingIntentId=snapshot.targetingIntentId,
            clusterId=cluster_id,
            reasonCode=(
                "negative_holdout" if reason == "negative_holdout"
                else "manual_tenant_exclusion"
            ),
            excludedEntityCount=member_count,
            reachedEntityCount=reached_count,
            leakageRate=round(rate, 4),
            likelyCauses=_likely_causes(snapshot, observation, cluster_id),
            severity=_severity(rate),  # type: ignore[arg-type]
            evidenceRefs=[
                EvidenceRef(
                    id=observation.observationId, type="event",
                    source="targeting_observation",
                    observedAt=observation.observedAt,
                ),
                EvidenceRef(
                    id=snapshot.snapshotId, type="annotation",
                    source="eligibility_snapshot",
                    observedAt=snapshot.asOf,
                ),
            ],
        ))
    return findings


def holdout_contamination(
    holdout_cluster_ids: list[str],
    observation: TargetingObservation,
    member_counts: Optional[dict[str, int]] = None,
) -> dict[str, float]:
    """Observed contamination rate per holdout cluster (0 when untouched)."""
    member_counts = member_counts or {}
    contamination: dict[str, float] = {}
    reached = set(observation.reachedHoldoutClusters) | set(observation.reachedClusters)
    for cluster_id in holdout_cluster_ids:
        if cluster_id in reached:
            members = member_counts.get(cluster_id, 0)
            contamination[cluster_id] = round(1.0 / members, 4) if members > 1 else 1.0
        else:
            contamination[cluster_id] = 0.0
    return contamination
