"""Kyber operator routes for Cluster Targeting Intelligence.

Operator-gated fleet diagnostics; aggregates never expose raw tenant-private
data. Recompute controls are audited.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger

from services.targeting_intelligence.recompute import recompute_leakage, recompute_snapshot
from services.targeting_intelligence.release_readiness import release_readiness
from services.targeting_intelligence.repository import get_targeting_repositories

logger = get_logger("aether.targeting.kyber")

kyber_router = APIRouter(prefix="/v1/admin/kyber/targeting",
                         tags=["Admin — Kyber Targeting"])


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


def _require_kyber_enabled() -> None:
    flags = settings.targeting_intelligence
    if not (flags.enabled or flags.kyber_enabled):
        raise BadRequestError(
            "Kyber targeting surfaces are not enabled "
            "(KYBER_TARGETING_INTELLIGENCE_ENABLED=false)"
        )


@kyber_router.get("/health")
async def fleet_health(request: Request):
    _require_kyber_enabled()
    _require_operator(request)
    repos = get_targeting_repositories()
    intents = await repos.intents.list_all()
    snapshots = await repos.snapshots.list_all()
    findings = await repos.leakage.list_all()

    return APIResponse(data={
        "tenantsObserved": len({r.get("tenantId") for r in intents}),
        "intentCount": len(intents),
        "snapshotCount": len(snapshots),
        "leakageBySeverity": dict(Counter(f.get("severity", "info") for f in findings)),
        "intentsBySource": dict(Counter(i.get("source", "unknown") for i in intents)),
    }).to_dict()


@kyber_router.get("/leakage-queue")
async def leakage_queue(request: Request, severity: Optional[str] = None,
                        limit: int = 100):
    _require_kyber_enabled()
    _require_operator(request)
    findings = await get_targeting_repositories().leakage.list_all()
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]
    findings.sort(key=lambda f: (f.get("severity") != "critical",
                                 f.get("severity") != "high",
                                 f.get("computedAt", "")))
    queue = [{
        "findingId": f.get("findingId"),
        "tenantId": f.get("tenantId"),
        "campaignId": f.get("campaignId"),
        "clusterId": f.get("clusterId"),
        "severity": f.get("severity"),
        "leakageRate": f.get("leakageRate"),
        "reasonCode": f.get("reasonCode"),
        "likelyCauses": f.get("likelyCauses"),
        "computedAt": f.get("computedAt"),
    } for f in findings[:limit]]
    return APIResponse(data={"queue": queue}).to_dict()


@kyber_router.get("/mapping-quality")
async def mapping_quality_diagnostics(request: Request, limit: int = 100):
    _require_kyber_enabled()
    _require_operator(request)
    observations = await get_targeting_repositories().observations.list_all()
    rows = []
    for obs in observations[:limit]:
        quality = obs.get("providerMappingQuality") or {}
        rows.append({
            "tenantId": obs.get("tenantId"),
            "campaignId": obs.get("campaignId"),
            "provider": quality.get("provider"),
            "qualityScore": quality.get("qualityScore"),
            "blocksSuggestions": quality.get("blocksSuggestions"),
            "providerSyncFreshness": quality.get("providerSyncFreshness"),
            "reasons": quality.get("reasons", []),
            "computedAt": quality.get("computedAt"),
        })
    rows.sort(key=lambda r: r.get("qualityScore") or 0.0)
    return APIResponse(data={"diagnostics": rows}).to_dict()


class RecomputeRequest(BaseModel):
    tenantId: str
    intentId: Optional[str] = None
    asOf: Optional[str] = None
    observationId: Optional[str] = None


@kyber_router.post("/recompute")
async def recompute(body: RecomputeRequest, request: Request):
    _require_kyber_enabled()
    operator = _require_operator(request)
    actor = getattr(operator, "operator_id", None) or "kyber-operator"
    if body.intentId and body.asOf:
        record = await recompute_snapshot(body.tenantId, body.intentId, body.asOf,
                                          actor=actor)
        return APIResponse(data={"recomputed": "snapshot", "snapshot": record}).to_dict()
    if body.observationId:
        findings = await recompute_leakage(body.tenantId, body.observationId,
                                           actor=actor)
        return APIResponse(data={"recomputed": "leakage",
                                 "findings": findings}).to_dict()
    raise BadRequestError("Provide intentId+asOf (snapshot) or observationId (leakage)")


@kyber_router.get("/release-readiness")
async def targeting_release_readiness(request: Request):
    _require_kyber_enabled()
    _require_operator(request)
    return APIResponse(data=await release_readiness()).to_dict()


@kyber_router.get("/audit")
async def audit_trail(request: Request, limit: int = 100):
    _require_kyber_enabled()
    _require_operator(request)
    records = await get_targeting_repositories().audit.list_all(limit=limit)
    return APIResponse(data={"audit": records}).to_dict()
