"""Reliability routes.

* ``tenant_router`` (prefix ``/v1/status``) — tenant-safe system status for Aether.
  Strictly single-tenant; never exposes queues, pipelines internals, other tenants,
  infrastructure metadata, or security internals.
* ``admin_router`` (prefix ``/v1/admin/kyber``) — internal Kyber reliability command
  center. Gated by operator (admin) permission.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger

from services.reliability.models import IncidentSeverity, IncidentStatus, PostmortemStatus
from services.reliability.service import (
    incident_service,
    pipeline_service,
    postmortem_service,
    queue_service,
    runbook_service,
    service_registry,
    slo_service,
)
from services.reliability.tenant_impact import tenant_impact

logger = get_logger("aether.service.reliability.routes")

admin_router = APIRouter(prefix="/v1/admin/kyber", tags=["Admin — Kyber Reliability"])
tenant_router = APIRouter(prefix="/v1/status", tags=["System Status"])


# ── Helpers ──────────────────────────────────────────────────────────────────

from services.security.request_context import require_kyber_operator as _canonical_kyber_gate


def _require_kyber_operator(request: Request) -> None:
    """Require Olympus operator access via the canonical fail-closed gate.

    A regular Aether tenant — even one holding the ``admin`` permission or
    ``Role.ADMIN`` — is NOT a Kyber operator. Only the configured
    ``kyber:operator`` grant or the operator tenant-id allowlist passes.
    """
    _canonical_kyber_gate(request)


def _current_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state.tenant, "tenant_id", None)
    if not tenant_id:
        raise ForbiddenError("Tenant context is required")
    return tenant_id


def _actor(request: Request) -> str | None:
    tenant = getattr(request.state, "tenant", None)
    return getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", None)


# ── Request bodies ───────────────────────────────────────────────────────────

class IncidentCreate(BaseModel):
    title: str
    severity: IncidentSeverity
    status: IncidentStatus = "open"
    affected_services: list[str] = Field(default_factory=list)
    affected_tenants: Optional[list[str]] = None
    affected_pipelines: Optional[list[str]] = None
    affected_modules: Optional[list[str]] = None
    detected_at: Optional[str] = None
    owner_id: Optional[str] = None
    runbook_id: Optional[str] = None
    summary: Optional[str] = None
    customer_impact: Optional[str] = None
    internal_notes: Optional[str] = None
    mitigation_steps: list[str] = Field(default_factory=list)


class IncidentPatch(BaseModel):
    title: Optional[str] = None
    severity: Optional[IncidentSeverity] = None
    status: Optional[IncidentStatus] = None
    affected_services: Optional[list[str]] = None
    affected_tenants: Optional[list[str]] = None
    affected_pipelines: Optional[list[str]] = None
    affected_modules: Optional[list[str]] = None
    owner_id: Optional[str] = None
    runbook_id: Optional[str] = None
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    mitigation_steps: Optional[list[str]] = None
    customer_impact: Optional[str] = None
    internal_notes: Optional[str] = None
    resolved_at: Optional[str] = None


class RunbookCreate(BaseModel):
    title: str
    incident_type: str
    severity_hint: IncidentSeverity = "sev3"
    detection_signals: list[str] = Field(default_factory=list)
    diagnostic_steps: list[str] = Field(default_factory=list)
    mitigation_steps: list[str] = Field(default_factory=list)
    escalation_paths: list[str] = Field(default_factory=list)
    customer_comms_template: Optional[str] = None
    postmortem_required: bool = False


class RunbookPatch(BaseModel):
    title: Optional[str] = None
    incident_type: Optional[str] = None
    severity_hint: Optional[IncidentSeverity] = None
    detection_signals: Optional[list[str]] = None
    diagnostic_steps: Optional[list[str]] = None
    mitigation_steps: Optional[list[str]] = None
    escalation_paths: Optional[list[str]] = None
    customer_comms_template: Optional[str] = None
    postmortem_required: Optional[bool] = None


class PostmortemCreate(BaseModel):
    incident_id: str
    summary: str
    root_cause: str
    customer_impact: str
    timeline: list[str] = Field(default_factory=list)
    contributing_factors: list[str] = Field(default_factory=list)
    detection_gap: Optional[str] = None
    mitigation_gap: Optional[str] = None
    prevention_actions: list[str] = Field(default_factory=list)
    owner_id: Optional[str] = None
    status: PostmortemStatus = "draft"


class PostmortemPatch(BaseModel):
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    customer_impact: Optional[str] = None
    timeline: Optional[list[str]] = None
    contributing_factors: Optional[list[str]] = None
    detection_gap: Optional[str] = None
    mitigation_gap: Optional[str] = None
    prevention_actions: Optional[list[str]] = None
    owner_id: Optional[str] = None
    status: Optional[PostmortemStatus] = None


# ═══════════════════════════════════════════════════════════════════════════
# Kyber reliability overview + dashboards (Phase 10)
# ═══════════════════════════════════════════════════════════════════════════

def _overall_status(statuses: list[str]) -> str:
    order = ["offline", "critical", "degraded", "unknown", "healthy"]
    for level in order:
        if level in statuses:
            return level
    return "unknown"


@admin_router.get("/reliability/overview")
async def reliability_overview(request: Request):
    _require_kyber_operator(request)
    services = await service_registry.list()
    pipelines = await pipeline_service.list()
    queues = await queue_service.list()
    slos = await slo_service.list()
    incidents = await incident_service.list()
    impact = await tenant_impact.internal_summary()

    open_incidents = [i for i in incidents if i.get("status") not in ("resolved", "closed")]
    degraded_pipelines = [p for p in pipelines if p.get("status") in ("degraded", "critical", "offline")]
    queue_backlogs = [q for q in queues if (q.get("depth") or 0) > 0 or q.get("status") in ("degraded", "critical")]
    breached_slos = [s for s in slos if s.get("status") in ("breached", "at_risk")]

    data = {
        "overall_status": _overall_status([s.get("status", "unknown") for s in services]),
        "service_health_summary": {
            "total": len(services),
            "healthy": sum(1 for s in services if s.get("status") == "healthy"),
            "degraded": sum(1 for s in services if s.get("status") == "degraded"),
            "critical": sum(1 for s in services if s.get("status") in ("critical", "offline")),
            "unknown": sum(1 for s in services if s.get("status") == "unknown"),
        },
        "open_incident_count": len(open_incidents),
        "open_incidents": open_incidents[:10],
        "slo_status": {
            "total": len(slos),
            "meeting": sum(1 for s in slos if s.get("status") == "meeting"),
            "at_risk": sum(1 for s in slos if s.get("status") == "at_risk"),
            "breached": sum(1 for s in slos if s.get("status") == "breached"),
        },
        "queue_backlog_count": len(queue_backlogs),
        "degraded_pipeline_count": len(degraded_pipelines),
        "degraded_pipelines": degraded_pipelines,
        "tenant_impact": {
            "impacted_tenant_count": impact["impacted_tenant_count"],
        },
        "error_budget_status": [
            {"slo_id": s["slo_id"], "service_key": s["service_key"], "status": s["status"], "error_budget_remaining": s["error_budget_remaining"]}
            for s in breached_slos
        ],
    }
    return APIResponse(data=data).to_dict()


@admin_router.get("/reliability/services")
async def reliability_services(request: Request):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await service_registry.list()}).to_dict()


@admin_router.get("/reliability/pipelines")
async def reliability_pipelines(request: Request):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await pipeline_service.list()}).to_dict()


@admin_router.get("/reliability/queues")
async def reliability_queues(request: Request):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await queue_service.list()}).to_dict()


@admin_router.get("/reliability/slos")
async def reliability_slos(request: Request):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await slo_service.list()}).to_dict()


# ── Incidents ────────────────────────────────────────────────────────────────

@admin_router.get("/incidents")
async def list_incidents(request: Request, status: Optional[str] = None):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await incident_service.list(status=status)}).to_dict()


@admin_router.post("/incidents")
async def create_incident(body: IncidentCreate, request: Request):
    _require_kyber_operator(request)
    incident = await incident_service.create(body.model_dump(exclude_none=True), actor=_actor(request))
    return APIResponse(data=incident).to_dict()


@admin_router.get("/incidents/{incident_id}")
async def get_incident(incident_id: str, request: Request):
    _require_kyber_operator(request)
    incident = await incident_service.get(incident_id)
    if incident is None:
        raise NotFoundError("incident")
    incident["audit_trail"] = await incident_service.audit_trail(incident_id)
    return APIResponse(data=incident).to_dict()


@admin_router.patch("/incidents/{incident_id}")
async def patch_incident(incident_id: str, body: IncidentPatch, request: Request):
    _require_kyber_operator(request)
    incident = await incident_service.update(incident_id, body.model_dump(exclude_unset=True), actor=_actor(request))
    return APIResponse(data=incident).to_dict()


# ── Runbooks ─────────────────────────────────────────────────────────────────

@admin_router.get("/runbooks")
async def list_runbooks(request: Request):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await runbook_service.list()}).to_dict()


@admin_router.post("/runbooks")
async def create_runbook(body: RunbookCreate, request: Request):
    _require_kyber_operator(request)
    return APIResponse(data=await runbook_service.create(body.model_dump())).to_dict()


@admin_router.patch("/runbooks/{runbook_id}")
async def patch_runbook(runbook_id: str, body: RunbookPatch, request: Request):
    _require_kyber_operator(request)
    return APIResponse(data=await runbook_service.update(runbook_id, body.model_dump(exclude_unset=True))).to_dict()


# ── Postmortems ──────────────────────────────────────────────────────────────

@admin_router.get("/postmortems")
async def list_postmortems(request: Request):
    _require_kyber_operator(request)
    return APIResponse(data={"items": await postmortem_service.list()}).to_dict()


@admin_router.post("/postmortems")
async def create_postmortem(body: PostmortemCreate, request: Request):
    _require_kyber_operator(request)
    return APIResponse(data=await postmortem_service.create(body.model_dump())).to_dict()


@admin_router.patch("/postmortems/{postmortem_id}")
async def patch_postmortem(postmortem_id: str, body: PostmortemPatch, request: Request):
    _require_kyber_operator(request)
    return APIResponse(data=await postmortem_service.update(postmortem_id, body.model_dump(exclude_unset=True))).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# Tenant-facing status (Phase 9) — tenant-safe, single-tenant only
# ═══════════════════════════════════════════════════════════════════════════

@tenant_router.get("")
async def tenant_status(request: Request):
    request.state.tenant.require_permission("read")
    tenant_id = _current_tenant_id(request)
    return APIResponse(data=await tenant_impact.tenant_safe_summary(tenant_id)).to_dict()


@tenant_router.get("/incidents")
async def tenant_status_incidents(request: Request):
    request.state.tenant.require_permission("read")
    tenant_id = _current_tenant_id(request)
    return APIResponse(data=await tenant_impact.tenant_incidents_safe(tenant_id)).to_dict()


@tenant_router.get("/data-freshness")
async def tenant_status_data_freshness(request: Request):
    request.state.tenant.require_permission("read")
    tenant_id = _current_tenant_id(request)
    summary = await tenant_impact.tenant_safe_summary(tenant_id)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "data_freshness": summary["data_freshness"],
        "recommendation_status": summary["recommendation_status"],
        "outcome_capture_status": summary["outcome_capture_status"],
        "audit_export_status": summary["audit_export_status"],
        "updated_at": summary["updated_at"],
    }).to_dict()


@tenant_router.get("/integrations")
async def tenant_status_integrations(request: Request):
    request.state.tenant.require_permission("read")
    tenant_id = _current_tenant_id(request)
    summary = await tenant_impact.tenant_safe_summary(tenant_id)
    return APIResponse(data={
        "tenant_id": tenant_id,
        "integration_status": summary["integration_status"],
        "updated_at": summary["updated_at"],
    }).to_dict()
