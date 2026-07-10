"""Targeting recommendation export packages.

Evidence-backed implementation packages the TENANT applies in their own
external campaign platform. Aether never executes a package; the
non-execution fields are frozen literals on the model and re-asserted here.
"""

from __future__ import annotations

from typing import Optional

from config.settings import settings
from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import metrics

from services.targeting_intelligence.models import (
    EvidenceRef,
    TargetingRecommendationExportPackage,
)
from services.targeting_intelligence.repository import (
    TargetingRepositories,
    get_targeting_repositories,
)

_EXTERNAL_ONLY_NOTE = (
    "This package is for your external platform. Aether does not execute it."
)


async def build_export_package(
    tenant_id: str,
    *,
    targeting_intent_id: Optional[str] = None,
    suggestion_id: Optional[str] = None,
    actor: str = "tenant",
    repositories: Optional[TargetingRepositories] = None,
) -> dict:
    if not settings.targeting_intelligence.exports_enabled:
        raise BadRequestError(
            "Targeting exports are not enabled (AETHER_TARGETING_EXPORTS_ENABLED=false)"
        )
    if not (targeting_intent_id or suggestion_id):
        raise BadRequestError("targetingIntentId or suggestionId is required")

    repos = repositories or get_targeting_repositories()
    include: list[str] = []
    reference: list[str] = []
    exclude: list[str] = []
    holdout: list[str] = []
    evidence: list[EvidenceRef] = []
    campaign_id = None
    notes: list[str] = [_EXTERNAL_ONLY_NOTE]

    if targeting_intent_id:
        intent = await repos.intents.get(tenant_id, targeting_intent_id)
        campaign_id = intent.get("campaignId")
        include = list(intent.get("includeClusters") or [])
        reference = list(intent.get("referenceClusters") or [])
        exclude = list(intent.get("excludeClusters") or [])
        holdout = list(intent.get("holdoutClusters") or [])
        evidence.append(EvidenceRef(
            id=targeting_intent_id, type="annotation", source="targeting_intent",
        ))
        snapshots = await repos.snapshots.list_for_tenant(
            tenant_id, targetingIntentId=targeting_intent_id, limit=1
        )
        if snapshots:
            latest = snapshots[0]
            # The snapshot's policy view is authoritative for what is safe.
            include = list(latest.get("eligibleClusters") or include)
            exclude = list(latest.get("excludedClusters") or exclude)
            holdout = list(latest.get("holdoutClusters") or holdout)
            evidence.append(EvidenceRef(
                id=latest["snapshotId"], type="annotation",
                source="eligibility_snapshot", observedAt=latest.get("asOf"),
            ))
        else:
            notes.append(
                "No eligibility snapshot exists yet — cluster lists reflect the "
                "declared intent only. Compute a snapshot for policy-checked lists."
            )

    if not (include or reference or exclude or holdout):
        raise NotFoundError("Nothing to export for this intent/suggestion")

    notes.extend([
        "Apply the include/exclude/holdout lists in your campaign platform's "
        "audience settings; keep holdout clusters fully unexposed.",
        "Re-run an eligibility snapshot after applying changes so Aether can "
        "observe whether the targeting matched the intent.",
    ])

    package = TargetingRecommendationExportPackage(
        tenantId=tenant_id,
        suggestionId=suggestion_id,
        targetingIntentId=targeting_intent_id,
        campaignId=campaign_id,
        includeClusterIds=include,
        referenceClusterIds=reference,
        excludeClusterIds=exclude,
        holdoutClusterIds=holdout,
        implementationNotes=notes,
        evidenceRefs=evidence,
    )
    record = await repos.exports.save(tenant_id, package.model_dump(mode="json"))
    await repos.audit.record(
        tenant_id, "export_package_generated",
        {"exportId": package.exportId, "intentId": targeting_intent_id,
         "suggestionId": suggestion_id},
        actor,
    )
    metrics.increment("targeting_export_packages_total")
    return record
