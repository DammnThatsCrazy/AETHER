"""Idempotent recompute/backfill controls (operator + tenant surfaces).

Deterministic: recomputing the same inputs replaces the prior result rather
than duplicating it (snapshot identity is preserved per (tenant, intent,
asOf)). Every recompute is audited.
"""

from __future__ import annotations

from typing import Optional

from shared.logger.logger import metrics

from services.targeting_intelligence.leakage import detect_leakage
from services.targeting_intelligence.models import (
    TargetingEligibilitySnapshot,
    TargetingObservation,
)
from services.targeting_intelligence.repository import (
    TargetingRepositories,
    get_targeting_repositories,
)
from services.targeting_intelligence.service import (
    TargetingIntentService,
    get_targeting_service,
)


async def recompute_snapshot(
    tenant_id: str, intent_id: str, as_of: str, actor: str = "operator",
    service: Optional[TargetingIntentService] = None,
) -> dict:
    service = service or get_targeting_service()
    record = await service.compute_eligibility_snapshot(
        tenant_id, intent_id, as_of, actor=actor
    )
    metrics.increment("targeting_recompute_total", labels={"kind": "snapshot"})
    return record


async def recompute_leakage(
    tenant_id: str, observation_id: str, actor: str = "operator",
    repositories: Optional[TargetingRepositories] = None,
) -> list[dict]:
    """Re-derive leakage findings for an observation (replaces prior ones)."""
    repos = repositories or get_targeting_repositories()
    observation = TargetingObservation.model_validate(
        await repos.observations.get(tenant_id, observation_id)
    )
    if not observation.eligibilitySnapshotId:
        return []
    snapshot = TargetingEligibilitySnapshot.model_validate(
        await repos.snapshots.get(tenant_id, observation.eligibilitySnapshotId)
    )
    # Remove prior findings for this observation, then re-detect.
    prior = await repos.leakage.list_for_tenant(
        tenant_id, campaignId=observation.campaignId, limit=500
    )
    for finding in prior:
        refs = {r.get("id") for r in finding.get("evidenceRefs", [])}
        if observation_id in refs:
            await repos.leakage.delete(tenant_id, finding["findingId"])

    findings = detect_leakage(snapshot, observation)
    saved = [
        await repos.leakage.save(tenant_id, f.model_dump(mode="json"))
        for f in findings
    ]
    await repos.audit.record(
        tenant_id, "leakage_recomputed",
        {"observationId": observation_id, "findingCount": len(saved)}, actor,
    )
    metrics.increment("targeting_recompute_total", labels={"kind": "leakage"})
    return saved
