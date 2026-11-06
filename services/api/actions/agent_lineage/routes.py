"""Tenant routes at ``/v1/agent-lineage`` and Kyber operator investigation routes.

Tenant scope is server-authoritative: it comes from the authenticated context,
never the path, so a principal id from another tenant simply has no rows. Every
list is cursor-paged and every aggregate carries a ``Disclosure``. A principal
with 100,000 agents is reached through summary, clusters and tree, never one list.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from governance.security.request_context import require_kyber_operator
from config.settings import settings
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger

from ._common import LineageQueryError
from .service import AgentLineageService, get_service

logger = get_logger("aether.agent_lineage.routes")

router = APIRouter(prefix="/v1/agent-lineage", tags=["Agent Lineage"])
kyber_router = APIRouter(prefix="/v1/admin/kyber/agent-lineage", tags=["Kyber Agent Lineage"])


def _require_enabled() -> None:
    if not settings.external_agent_telemetry.registry_enabled:
        raise NotFoundError("Agent lineage is not enabled")


def _tenant_id(request: Request) -> str:
    _require_enabled()
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    return tenant.tenant_id


def _operator(request: Request) -> None:
    if not settings.external_agent_telemetry.kyber_enabled:
        raise NotFoundError("Kyber agent lineage is not enabled")
    # Tenant ids come from the path here. A tenant admin must never pass this gate,
    # even where route-policy enforcement is off.
    require_kyber_operator(request)


async def _call(coroutine: Any) -> dict[str, Any]:
    try:
        return APIResponse(data=await coroutine).to_dict()
    except LineageQueryError as exc:
        raise BadRequestError(str(exc))


def _agent_filters(
    relationship: Optional[str], attribution_class: Optional[str], active_state: Optional[str],
    lineage_status: Optional[str], risk: Optional[str], cluster_id: Optional[str],
    deployment_id: Optional[str], operator_entity_id: Optional[str], authority_status: Optional[str],
    min_depth: Optional[int], max_depth: Optional[int],
) -> dict[str, Any]:
    return {
        "relationship": relationship, "attribution_class": attribution_class, "active_state": active_state,
        "lineage_status": lineage_status, "risk": risk, "cluster_id": cluster_id,
        "deployment_id": deployment_id, "operator_entity_id": operator_entity_id,
        "authority_status": authority_status, "min_depth": min_depth, "max_depth": max_depth,
    }


@router.get("/principals/{principal_id}/summary")
async def principal_summary(principal_id: str, request: Request):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.summary(tenant_id, principal_id))


@router.get("/principals/{principal_id}/agents")
async def principal_agents(
    principal_id: str, request: Request,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
    relationship: Optional[str] = None, attribution_class: Optional[str] = None,
    active_state: Optional[str] = None, lineage_status: Optional[str] = None, risk: Optional[str] = None,
    cluster_id: Optional[str] = None, deployment_id: Optional[str] = None,
    operator_entity_id: Optional[str] = None, authority_status: Optional[str] = None,
    min_depth: Optional[int] = Query(default=None, ge=0), max_depth: Optional[int] = Query(default=None, ge=0),
):
    tenant_id = _tenant_id(request)
    service = await get_service()
    filters = _agent_filters(
        relationship, attribution_class, active_state, lineage_status, risk, cluster_id,
        deployment_id, operator_entity_id, authority_status, min_depth, max_depth,
    )
    return await _call(service.agents(tenant_id, principal_id, filters=filters, cursor=cursor, page_size=page_size))


@router.get("/principals/{principal_id}/clusters")
async def principal_clusters(
    principal_id: str, request: Request,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.clusters(tenant_id, principal_id, cursor=cursor, page_size=page_size))


@router.get("/principals/{principal_id}/tree")
async def principal_tree(
    principal_id: str, request: Request, parent: Optional[str] = None,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.tree(tenant_id, principal_id, parent=parent, cursor=cursor, page_size=page_size))


@router.get("/principals/{principal_id}/risk")
async def principal_risk(principal_id: str, request: Request):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.risk(tenant_id, principal_id))


@router.get("/principals/{principal_id}/restatements")
async def principal_restatements(
    principal_id: str, request: Request,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.restatements(tenant_id, principal_id, cursor=cursor, page_size=page_size))


class LineageExportRequest(BaseModel):
    format: str = Field(default="ndjson", pattern="^(json|ndjson|csv)$")
    relationship: Optional[str] = None
    attribution_class: Optional[str] = None
    # Resume after this agent id. A part that reports ``rows_remaining`` continues here.
    after: Optional[str] = Field(default=None, max_length=256)


@router.post("/principals/{principal_id}/export", status_code=202)
async def principal_export(principal_id: str, body: LineageExportRequest, request: Request):
    """Full extraction as an asynchronous job; large lineage never renders over HTTP."""
    tenant_id = _tenant_id(request)
    tenant = request.state.tenant
    if not (tenant.has_permission("export") or tenant.has_permission("admin")):
        tenant.require_permission("export")
    from governance.security.export_governance import audit_export_governance
    from ingestion.export.service import request_export
    from shared.privacy.ip_hmac import audit_ip_token

    # Same governance as POST /v1/exports: permission, tenant boundary and audit record.
    await audit_export_governance.authorize_create(
        actor_id=getattr(tenant, "user_id", None) or tenant_id,
        actor_type="tenant_user",
        tenant_id=tenant_id,
        export_type="agent_lineage",
        has_export_permission=True,
        target_tenant=tenant_id,
        manifest={"params": {"principal_entity_id": principal_id, "after": body.after}, "format": body.format},
        ip_address=audit_ip_token(request.client.host if request.client else None, tenant_id),
    )
    job = await request_export(
        tenant_id,
        export_type="agent_lineage",
        params={
            "principal_entity_id": principal_id, "format": body.format,
            "relationship": body.relationship, "attribution_class": body.attribution_class, "after": body.after,
        },
        requested_by=getattr(tenant, "user_id", None),
        correlation_id=getattr(request.state, "request_id", None),
    )
    return APIResponse(data={**job, "status_url": f"/v1/agent-lineage/exports/{job['job_id']}"}).to_dict()


@router.get("/exports/{job_id}")
async def export_status(job_id: str, request: Request):
    tenant_id = _tenant_id(request)
    from workers.jobs.service import get_jobs_service

    job = await get_jobs_service().get_job(tenant_id, job_id)
    if job is None or job.get("tenant_id") != tenant_id or job.get("job_type") != "export.generate":
        raise NotFoundError("export job not found")
    if (job.get("payload") or {}).get("export_type") != "agent_lineage":
        raise NotFoundError("export job not found")
    return APIResponse(data={
        "job_id": job_id, "status": job.get("status"), "result": job.get("result"),
    }).to_dict()


@router.post("/reconcile", status_code=202)
async def reconcile(request: Request, full: bool = False):
    """Fold new evidence into the projection. ``full`` rebuilds and logs restatements."""
    tenant_id = _tenant_id(request)
    from workers.jobs.service import get_jobs_service

    from .jobs import JOB_TYPE

    job = await get_jobs_service().enqueue(
        tenant_id, JOB_TYPE, {"full": full},
        correlation_id=getattr(request.state, "request_id", None),
        requested_by=getattr(request.state.tenant, "user_id", None),
    )
    return APIResponse(data={"job_id": job["id"], "status": job.get("status", "queued"), "full": full}).to_dict()


class PrincipalBindingRequest(BaseModel):
    kind: str = Field(pattern="^(claim|agent)$")
    principal_entity_id: str = Field(min_length=1, max_length=256)
    namespace: Optional[str] = Field(default=None, max_length=128)
    claim_ref: Optional[str] = Field(default=None, max_length=256)
    agent_entity_id: Optional[str] = Field(default=None, max_length=256)
    evidence_refs: list[str] = Field(default_factory=list, max_length=25)


@router.post("/bindings", status_code=201)
async def declare_binding(body: PrincipalBindingRequest, request: Request):
    """Record a tenant's declaration of a principal link.

    The API accepts no evidence class: a declaration can never self-certify as
    proof, so it is stored ``TENANT_DECLARED`` and resolves as inferred at most.
    """
    tenant_id = _tenant_id(request)
    from actions.agent.identity_hierarchy import ensure_distinct_human_agent

    from ._common import stable_hash
    from .evidence import PrincipalBinding
    from .repository import PrincipalBindingRepository

    try:
        binding = PrincipalBinding.from_mapping({
            "tenant_id": tenant_id, "evidence_class": "TENANT_DECLARED", **body.model_dump(),
        })
        if binding.agent_entity_id:
            ensure_distinct_human_agent(human_entity_id=binding.principal_entity_id, agent_entity_id=binding.agent_entity_id)
    except ValueError as exc:
        raise BadRequestError(str(exc))
    binding_id = "alb_" + stable_hash(tenant_id, *binding.key)
    repo = PrincipalBindingRepository()
    existing = await repo.find_by_id(binding_id)
    version = int((existing or {}).get("version") or 0) + 1
    record = {
        "id": binding_id, "tenant_id": tenant_id, "kind": binding.kind,
        "principal_entity_id": binding.principal_entity_id, "evidence_class": binding.evidence_class,
        "namespace": binding.namespace, "claim_ref": binding.claim_ref,
        "agent_entity_id": binding.agent_entity_id, "version": version,
        "evidence_refs": list(binding.evidence_refs),
    }
    stored = await (repo.update(binding_id, record) if existing else repo.insert(binding_id, record))
    return APIResponse(data=stored).to_dict()


class AdjudicationRequest(BaseModel):
    verdict: str = Field(pattern="^(confirmed_malicious|cleared)$")
    reason: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(min_length=1, max_length=25)


@router.put("/agents/{agent_id}/adjudication")
async def adjudicate_agent(agent_id: str, body: AdjudicationRequest, request: Request):
    """Record a person's verdict. Needs ``admin`` as well, since it sets confirmed malice."""
    tenant_id = _tenant_id(request)
    tenant = request.state.tenant
    tenant.require_permission("admin")
    actor = getattr(tenant, "user_id", None)
    if not actor:
        # A verdict must name who made it, so an API key cannot record one.
        raise BadRequestError("adjudication requires an authenticated user")
    from ._common import stable_hash
    from .repository import AdjudicationRepository

    record_id = "ala_" + stable_hash(tenant_id, agent_id)
    repo = AdjudicationRepository()
    existing = await repo.find_by_id(record_id)
    record = {
        "id": record_id, "tenant_id": tenant_id, "agent_entity_id": agent_id,
        "verdict": body.verdict, "reason": body.reason, "evidence_refs": body.evidence_refs,
        "adjudicated_by": actor,
    }
    stored = await (repo.update(record_id, record) if existing else repo.insert(record_id, record))
    return APIResponse(data=stored).to_dict()


@router.get("/agents/{agent_id}")
async def agent_detail(agent_id: str, request: Request):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.agent_detail(tenant_id, agent_id))


@router.get("/agents/{agent_id}/counts")
async def agent_counts(agent_id: str, request: Request):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.agent_counts(tenant_id, agent_id))


@router.get("/agents/{agent_id}/descendants")
async def agent_descendants(
    agent_id: str, request: Request,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.descendants(tenant_id, agent_id, cursor=cursor, page_size=page_size))


@router.get("/agents/{agent_id}/ancestors")
async def agent_ancestors(agent_id: str, request: Request):
    tenant_id = _tenant_id(request)
    service = await get_service()
    return await _call(service.ancestors(tenant_id, agent_id))


# ── Kyber operator investigation ──────────────────────────────────────────


async def _kyber_service() -> AgentLineageService:
    return await get_service()


@kyber_router.get("/tenants/{tenant_id}/principals/{principal_id}/investigation")
async def kyber_investigation(tenant_id: str, principal_id: str, request: Request):
    _operator(request)
    service = await _kyber_service()
    return await _call(service.investigation(tenant_id, principal_id))


@kyber_router.get("/tenants/{tenant_id}/principals/{principal_id}/agents")
async def kyber_agents(
    tenant_id: str, principal_id: str, request: Request,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
    relationship: Optional[str] = None, attribution_class: Optional[str] = None,
    active_state: Optional[str] = None, lineage_status: Optional[str] = None, risk: Optional[str] = None,
    cluster_id: Optional[str] = None, deployment_id: Optional[str] = None,
    operator_entity_id: Optional[str] = None, authority_status: Optional[str] = None,
    min_depth: Optional[int] = Query(default=None, ge=0), max_depth: Optional[int] = Query(default=None, ge=0),
):
    _operator(request)
    service = await _kyber_service()
    filters = _agent_filters(
        relationship, attribution_class, active_state, lineage_status, risk, cluster_id,
        deployment_id, operator_entity_id, authority_status, min_depth, max_depth,
    )
    return await _call(service.agents(tenant_id, principal_id, filters=filters, cursor=cursor, page_size=page_size))


@kyber_router.get("/tenants/{tenant_id}/principals/{principal_id}/tree")
async def kyber_tree(
    tenant_id: str, principal_id: str, request: Request, parent: Optional[str] = None,
    cursor: Optional[str] = None, page_size: Optional[int] = Query(default=None, ge=1, le=500),
):
    _operator(request)
    service = await _kyber_service()
    return await _call(service.tree(tenant_id, principal_id, parent=parent, cursor=cursor, page_size=page_size))


@kyber_router.get("/tenants/{tenant_id}/calibration")
async def kyber_calibration(tenant_id: str, request: Request):
    """Fan-out thresholds against adjudicated principals. Read-only; policy is changed by hand."""
    _operator(request)
    service = await _kyber_service()
    return await _call(service.calibration(tenant_id))


@kyber_router.get("/tenants/{tenant_id}/agents/{agent_id}")
async def kyber_agent(tenant_id: str, agent_id: str, request: Request):
    _operator(request)
    service = await _kyber_service()
    return await _call(service.agent_detail(tenant_id, agent_id))
