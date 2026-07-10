"""Tenant routes for Cluster Targeting Intelligence.

* ``router`` — ``/v1/targeting-intelligence`` (intents, snapshots,
  observations, leakage, holdouts, journey deltas, exports).
* ``scoped_router`` — campaign/cluster-scoped reads
  (``/v1/campaigns/{id}/targeting-intelligence``,
  ``/v1/clusters/{id}/targeting-impact``) owned by this package so the
  campaign/cluster services stay untouched.

Aether observes and recommends; it never executes campaigns.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError, ForbiddenError
from shared.logger.logger import get_logger

from services.targeting_intelligence.export import build_export_package
from services.targeting_intelligence.leakage import detect_leakage
from services.targeting_intelligence.models import (
    ClusterTargetingImpact,
    TargetingEligibilitySnapshot,
    TargetingObservation,
    utc_now_iso,
)
from services.targeting_intelligence.quality import quality_from_observation_inputs
from services.targeting_intelligence.repository import get_targeting_repositories
from services.targeting_intelligence.service import get_targeting_service

logger = get_logger("aether.targeting.routes")

router = APIRouter(prefix="/v1/targeting-intelligence", tags=["Targeting Intelligence"])
scoped_router = APIRouter(prefix="/v1", tags=["Targeting Intelligence"])


def _require_enabled() -> None:
    if not settings.targeting_intelligence.enabled:
        raise BadRequestError(
            "Cluster Targeting Intelligence is not enabled "
            "(AETHER_CLUSTER_TARGETING_INTELLIGENCE_ENABLED=false)"
        )


def _tenant_id(request: Request, permission: str = "read") -> str:
    request.state.tenant.require_permission(permission)
    tid = getattr(request.state.tenant, "tenant_id", None)
    if not tid:
        raise ForbiddenError("Tenant context is required")
    return tid


def _actor(request: Request) -> str:
    t = getattr(request.state, "tenant", None)
    return getattr(t, "user_id", None) or getattr(t, "tenant_id", None) or "tenant"


# ── Intents ────────────────────────────────────────────────────────────────

@router.post("/intents")
async def create_intent(body: dict, request: Request):
    _require_enabled()
    tenant_id = _tenant_id(request, "write")
    record = await get_targeting_service().create_intent(tenant_id, body, _actor(request))
    return APIResponse(data={"intent": record}).to_dict()


@router.get("/intents")
async def list_intents(request: Request, campaign_id: Optional[str] = None,
                       limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().intents.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=limit
    )
    return APIResponse(data={"intents": records}).to_dict()


@router.get("/intents/{intent_id}")
async def get_intent(intent_id: str, request: Request):
    _require_enabled()
    tenant_id = _tenant_id(request)
    record = await get_targeting_repositories().intents.get(tenant_id, intent_id)
    return APIResponse(data={"intent": record}).to_dict()


@router.patch("/intents/{intent_id}")
async def update_intent(intent_id: str, body: dict, request: Request):
    _require_enabled()
    tenant_id = _tenant_id(request, "write")
    record = await get_targeting_service().update_intent(
        tenant_id, intent_id, body, _actor(request)
    )
    return APIResponse(data={"intent": record}).to_dict()


# ── Eligibility snapshots ─────────────────────────────────────────────────

class SnapshotRequest(BaseModel):
    asOf: Optional[str] = None


@router.post("/intents/{intent_id}/eligibility-snapshot")
async def compute_snapshot(intent_id: str, body: SnapshotRequest, request: Request):
    _require_enabled()
    tenant_id = _tenant_id(request, "write")
    record = await get_targeting_service().compute_eligibility_snapshot(
        tenant_id, intent_id, body.asOf or utc_now_iso(), actor=_actor(request)
    )
    return APIResponse(data={"snapshot": record}).to_dict()


@router.get("/snapshots")
async def list_snapshots(request: Request, intent_id: Optional[str] = None,
                         limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().snapshots.list_for_tenant(
        tenant_id, targetingIntentId=intent_id, limit=limit
    )
    return APIResponse(data={"snapshots": records}).to_dict()


# ── Observations (+ automatic leakage detection) ──────────────────────────

@router.post("/observations")
async def record_observation(body: dict, request: Request):
    """Record an observed-targeting result and derive leakage findings."""
    _require_enabled()
    tenant_id = _tenant_id(request, "write")
    repos = get_targeting_repositories()

    body = {**body, "tenantId": tenant_id}
    if isinstance(body.get("providerMappingQuality"), dict) and \
            "qualityScore" not in body["providerMappingQuality"]:
        body["providerMappingQuality"] = quality_from_observation_inputs(
            body["providerMappingQuality"]
        ).model_dump(mode="json")
    observation = TargetingObservation.model_validate(body)
    record = await repos.observations.save(
        tenant_id, observation.model_dump(mode="json")
    )

    findings: list[dict[str, Any]] = []
    if observation.eligibilitySnapshotId:
        snapshot = TargetingEligibilitySnapshot.model_validate(
            await repos.snapshots.get(tenant_id, observation.eligibilitySnapshotId)
        )
        for finding in detect_leakage(snapshot, observation):
            findings.append(await repos.leakage.save(
                tenant_id, finding.model_dump(mode="json")
            ))
    await repos.audit.record(
        tenant_id, "observation_recorded",
        {"observationId": observation.observationId, "leakageFindings": len(findings)},
        _actor(request),
    )
    return APIResponse(data={"observation": record, "leakageFindings": findings}).to_dict()


@router.get("/observations")
async def list_observations(request: Request, campaign_id: Optional[str] = None,
                            limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().observations.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=limit
    )
    return APIResponse(data={"observations": records}).to_dict()


# ── Leakage / holdouts / journey deltas ───────────────────────────────────

@router.get("/leakage")
async def list_leakage(request: Request, campaign_id: Optional[str] = None,
                       severity: Optional[str] = None, limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().leakage.list_for_tenant(
        tenant_id, campaignId=campaign_id, severity=severity, limit=limit
    )
    return APIResponse(data={"findings": records}).to_dict()


@router.post("/holdouts")
async def create_holdout(body: dict, request: Request):
    _require_enabled()
    tenant_id = _tenant_id(request, "write")
    from services.targeting_intelligence.models import TargetingHoldout
    holdout = TargetingHoldout.model_validate({**body, "tenantId": tenant_id})
    record = await get_targeting_repositories().holdouts.save(
        tenant_id, holdout.model_dump(mode="json")
    )
    return APIResponse(data={"holdout": record}).to_dict()


@router.get("/holdouts")
async def list_holdouts(request: Request, limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().holdouts.list_for_tenant(
        tenant_id, limit=limit
    )
    return APIResponse(data={"holdouts": records}).to_dict()


@router.get("/journey-deltas")
async def list_journey_deltas(request: Request, campaign_id: Optional[str] = None,
                              limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().journey_deltas.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=limit
    )
    return APIResponse(data={"journeyDeltas": records}).to_dict()


# ── Export packages ───────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    targetingIntentId: Optional[str] = None
    suggestionId: Optional[str] = None


@router.post("/exports")
async def create_export(body: ExportRequest, request: Request):
    _require_enabled()
    tenant_id = _tenant_id(request, "write")
    record = await build_export_package(
        tenant_id,
        targeting_intent_id=body.targetingIntentId,
        suggestion_id=body.suggestionId,
        actor=_actor(request),
    )
    return APIResponse(data={"export": record}).to_dict()


@router.get("/exports")
async def list_exports(request: Request, limit: int = 100):
    _require_enabled()
    tenant_id = _tenant_id(request)
    records = await get_targeting_repositories().exports.list_for_tenant(
        tenant_id, limit=limit
    )
    return APIResponse(data={"exports": records}).to_dict()


# ── Campaign/cluster-scoped reads (scoped_router) ─────────────────────────

@scoped_router.get("/campaigns/{campaign_id}/targeting-intelligence")
async def campaign_targeting_intelligence(campaign_id: str, request: Request):
    """Campaign360 Targeting Intelligence tab payload."""
    _require_enabled()
    tenant_id = _tenant_id(request)
    repos = get_targeting_repositories()

    intents = await repos.intents.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=10
    )
    snapshots: list[dict] = []
    for intent in intents:
        snapshots.extend(await repos.snapshots.list_for_tenant(
            tenant_id, targetingIntentId=intent["id"], limit=1
        ))
    observations = await repos.observations.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=5
    )
    findings = await repos.leakage.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=50
    )
    mapping_quality = (
        observations[0].get("providerMappingQuality") if observations else None
    )
    return APIResponse(data={
        "campaignId": campaign_id,
        "intents": intents,
        "latestSnapshots": snapshots,
        "observations": observations,
        "leakageFindings": findings,
        "mappingQuality": mapping_quality,
        "executionByAether": False,
        "externalExecutionRequired": True,
    }).to_dict()


@scoped_router.get("/clusters/{cluster_id}/targeting-impact")
async def cluster_targeting_impact(cluster_id: str, request: Request,
                                   campaign_id: Optional[str] = None):
    """Cluster360 Targeting Impact tab payload (observed, per campaign)."""
    _require_enabled()
    tenant_id = _tenant_id(request)
    repos = get_targeting_repositories()

    observations = await repos.observations.list_for_tenant(
        tenant_id, campaignId=campaign_id, limit=100
    )
    deltas = [
        d for d in await repos.journey_deltas.list_for_tenant(
            tenant_id, campaignId=campaign_id, limit=100
        )
        if d.get("clusterId") == cluster_id
    ]

    reached = engaged = converted = attributed = 0
    campaign_seen = campaign_id
    evidence: list[dict] = []
    for obs in observations:
        touched = set(obs.get("reachedClusters", [])) | \
            set(obs.get("reachedIncludedClusters", [])) | \
            set(obs.get("reachedExcludedClusters", [])) | \
            set(obs.get("reachedHoldoutClusters", []))
        if cluster_id in touched:
            reached += 1
            campaign_seen = campaign_seen or obs.get("campaignId")
            evidence.append({"id": obs["observationId"], "type": "event",
                             "source": "targeting_observation"})
    for delta in deltas:
        engaged += delta.get("engagedCount", 0)
        converted += delta.get("convertedCount", 0)
        attributed += delta.get("attributedCount", 0)

    impact = ClusterTargetingImpact(
        tenantId=tenant_id,
        campaignId=campaign_seen or "unknown",
        clusterId=cluster_id,
        reachedCount=reached,
        engagedCount=engaged,
        convertedCount=converted,
        attributedCount=attributed,
        evidenceCoverage=1.0 if evidence else 0.0,
    )
    payload = impact.model_dump(mode="json")
    payload["evidenceRefs"] = evidence
    return APIResponse(data={"impact": payload, "journeyDeltas": deltas}).to_dict()
