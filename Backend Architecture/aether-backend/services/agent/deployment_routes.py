"""
Aether Service — External Agent Deployment Routes

Tenant-scoped CRUD + lifecycle APIs for the external agent deployment
registry (External Agent Telemetry Plane V1), plus Kyber operator fleet
views. Observation-only: no execution, no marketplace.

Tenant routes require the ``agent:manage`` permission; cross-tenant access
always surfaces as not-found (no existence leak). Kyber routes follow the
agentic observability operator pattern (admin permission).
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from config.settings import settings
from services.agent.deployments import (
    AgentDeploymentRepository,
    get_deployment_repository,
)
from services.agentic_observability.foundation import require_permission as _require_perm
from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.agent.deployments.routes")

deployments_router = APIRouter(prefix="/v1/agent/deployments", tags=["Agent Deployments"])
kyber_router = APIRouter(
    prefix="/v1/admin/kyber/agent-telemetry", tags=["Kyber Agent Telemetry"]
)

# Health counter fields safe to expose on operator fleet views (no
# tenant-private metadata).
_HEALTH_FIELDS = (
    "health_score", "event_count_24h", "accepted_count_24h", "rejected_count_24h",
    "error_count_24h", "consent_blocked_count_24h", "graph_projection_lag_ms",
    "last_event_at", "last_seen_at",
)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Correlation-ID", "")


def _actor_id(request: Request) -> str:
    tenant = request.state.tenant
    return getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", "operator")


def _require_registry_enabled() -> None:
    cfg = settings.external_agent_telemetry
    if not (cfg.enabled or cfg.registry_enabled):
        raise BadRequestError("External agent deployment registry is not enabled")


def _require_kyber_enabled() -> None:
    cfg = settings.external_agent_telemetry
    if not (cfg.enabled or cfg.kyber_enabled):
        raise BadRequestError("Kyber external agent telemetry is not enabled")


def _tenant(request: Request):
    tenant = request.state.tenant
    tenant.require_permission("agent:manage")
    return tenant


def _repo() -> AgentDeploymentRepository:
    return get_deployment_repository()


# ── Request models ────────────────────────────────────────────────────────────

class DeploymentCreate(BaseModel):
    agent_id: str = Field(..., min_length=1, max_length=256)
    display_name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)
    external_platform: str
    external_platform_account_id: Optional[str] = Field(default=None, max_length=256)
    external_agent_id: Optional[str] = Field(default=None, max_length=256)
    external_app_id: Optional[str] = Field(default=None, max_length=256)
    external_channel_id: Optional[str] = Field(default=None, max_length=256)
    external_workspace_id: Optional[str] = Field(default=None, max_length=256)
    environment: str = "production"
    consent_mode: str = "tenant_managed"
    allowed_event_families: list[str] = Field(default_factory=list)
    required_consent_purposes: list[str] = Field(default_factory=list)
    capability_scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeploymentPatch(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2000)
    metadata: Optional[dict[str, Any]] = None
    allowed_event_families: Optional[list[str]] = None
    required_consent_purposes: Optional[list[str]] = None
    capability_scopes: Optional[list[str]] = None
    consent_mode: Optional[str] = None


class LifecycleAction(BaseModel):
    reason: str = Field(default="", max_length=2000)


# ── Tenant routes ─────────────────────────────────────────────────────────────

@deployments_router.post("")
async def create_deployment(body: DeploymentCreate, request: Request):
    """Register an external agent deployment for the authenticated tenant."""
    _require_registry_enabled()
    tenant = _tenant(request)
    record = await _repo().create(
        tenant.tenant_id,
        body.model_dump(exclude_none=True),
        actor=_actor_id(request),
        request_id=_request_id(request),
    )
    metrics.increment("agent_deployment_api_created_total")
    return APIResponse(data=record).to_dict()


@deployments_router.get("")
async def list_deployments(
    request: Request,
    status: str | None = None,
    platform: str | None = None,
    agent_id: str | None = None,
):
    """List the tenant's deployments with optional status/platform/agent filters."""
    _require_registry_enabled()
    tenant = _tenant(request)
    records = await _repo().list(
        tenant.tenant_id, status=status, platform=platform, agent_id=agent_id
    )
    return APIResponse(data={"deployments": records, "count": len(records)}).to_dict()


@deployments_router.get("/{deployment_id}")
async def get_deployment(deployment_id: str, request: Request):
    """Fetch a single deployment (not-found for other tenants' deployments)."""
    _require_registry_enabled()
    tenant = _tenant(request)
    record = await _repo().get(tenant.tenant_id, deployment_id)
    return APIResponse(data=record).to_dict()


@deployments_router.patch("/{deployment_id}")
async def patch_deployment(deployment_id: str, body: DeploymentPatch, request: Request):
    """Update mutable deployment fields (audited)."""
    _require_registry_enabled()
    tenant = _tenant(request)
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise BadRequestError("No updatable fields provided")
    record = await _repo().update(
        tenant.tenant_id, deployment_id, changes,
        actor=_actor_id(request), request_id=_request_id(request),
    )
    return APIResponse(data=record).to_dict()


async def _lifecycle(
    request: Request, deployment_id: str, target_status: str, reason: str
) -> dict:
    _require_registry_enabled()
    tenant = _tenant(request)
    record = await _repo().transition(
        tenant.tenant_id, deployment_id, target_status,
        actor=_actor_id(request), request_id=_request_id(request), reason=reason,
    )
    return APIResponse(data=record).to_dict()


@deployments_router.post("/{deployment_id}/pause")
async def pause_deployment(deployment_id: str, request: Request, body: LifecycleAction | None = None):
    """Pause telemetry acceptance for a deployment (active → paused)."""
    return await _lifecycle(request, deployment_id, "paused", (body.reason if body else ""))


@deployments_router.post("/{deployment_id}/reactivate")
async def reactivate_deployment(deployment_id: str, request: Request, body: LifecycleAction | None = None):
    """Reactivate a paused or errored deployment (paused|error → active)."""
    return await _lifecycle(request, deployment_id, "active", (body.reason if body else ""))


@deployments_router.post("/{deployment_id}/revoke")
async def revoke_deployment(deployment_id: str, request: Request, body: LifecycleAction | None = None):
    """Revoke a deployment; its telemetry is rejected from then on."""
    return await _lifecycle(request, deployment_id, "revoked", (body.reason if body else ""))


@deployments_router.post("/{deployment_id}/archive")
async def archive_deployment(deployment_id: str, request: Request, body: LifecycleAction | None = None):
    """Archive a deployment (terminal)."""
    return await _lifecycle(request, deployment_id, "archived", (body.reason if body else ""))


@deployments_router.get("/{deployment_id}/health")
async def deployment_health(deployment_id: str, request: Request):
    """Rolling 24h health counters + lifecycle status for a deployment."""
    _require_registry_enabled()
    tenant = _tenant(request)
    record = await _repo().get(tenant.tenant_id, deployment_id)
    return APIResponse(data={
        "deployment_id": deployment_id,
        "status": record.get("status"),
        "counters_reset_at": record.get("counters_reset_at"),
        **{f: record.get(f) for f in _HEALTH_FIELDS},
    }).to_dict()


@deployments_router.get("/{deployment_id}/activity")
async def deployment_activity(
    deployment_id: str,
    request: Request,
    limit: int = 50,
):
    """Audit trail + last-events summary for a deployment."""
    _require_registry_enabled()
    limit = min(max(limit, 1), 200)
    tenant = _tenant(request)
    record = await _repo().get(tenant.tenant_id, deployment_id)
    audit = await _repo().audit_trail(tenant.tenant_id, deployment_id, limit=limit)
    return APIResponse(data={
        "deployment_id": deployment_id,
        "status": record.get("status"),
        "audit": audit,
        "audit_count": len(audit),
        "last_events": {
            "last_event_at": record.get("last_event_at"),
            "last_seen_at": record.get("last_seen_at"),
            "first_seen_at": record.get("first_seen_at"),
            "event_count_24h": record.get("event_count_24h", 0),
            "accepted_count_24h": record.get("accepted_count_24h", 0),
            "rejected_count_24h": record.get("rejected_count_24h", 0),
            "error_count_24h": record.get("error_count_24h", 0),
            "consent_blocked_count_24h": record.get("consent_blocked_count_24h", 0),
        },
    }).to_dict()


# ── Kyber operator routes ─────────────────────────────────────────────────────

@kyber_router.get("/deployments")
async def kyber_fleet_overview(request: Request):
    """Kyber operator: cross-tenant fleet overview.

    Aggregate counts only — no tenant-private metadata, display names, or
    descriptions. Per-deployment rows carry id/tenant/status/platform plus
    health counters.
    """
    _require_kyber_enabled()
    _require_perm(request, "admin")
    records = await get_deployment_repository().list_all()

    by_status: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    health_totals = {
        "event_count_24h": 0, "accepted_count_24h": 0, "rejected_count_24h": 0,
        "error_count_24h": 0, "consent_blocked_count_24h": 0,
    }
    rows: list[dict] = []
    for record in records:
        by_status[record.get("status", "unknown")] = by_status.get(record.get("status", "unknown"), 0) + 1
        by_platform[record.get("external_platform", "unknown")] = by_platform.get(record.get("external_platform", "unknown"), 0) + 1
        for field_name in health_totals:
            health_totals[field_name] += int(record.get(field_name, 0) or 0)
        rows.append({
            "id": record.get("id"),
            "tenant_id": record.get("tenant_id"),
            "status": record.get("status"),
            "external_platform": record.get("external_platform"),
            **{f: record.get(f) for f in _HEALTH_FIELDS},
        })

    return APIResponse(data={
        "count": len(rows),
        "by_status": by_status,
        "by_platform": by_platform,
        "health_totals": health_totals,
        "deployments": rows,
    }).to_dict()


@kyber_router.get("/deployments/{tenant_id}/{deployment_id}")
async def kyber_deployment_detail(tenant_id: str, deployment_id: str, request: Request):
    """Kyber operator: single-deployment diagnostics detail."""
    _require_kyber_enabled()
    _require_perm(request, "admin")
    repo = get_deployment_repository()
    record = await repo.get(tenant_id, deployment_id)
    audit = await repo.audit_trail(tenant_id, deployment_id, limit=50)
    return APIResponse(data={
        "deployment": record,
        "audit": audit,
        "audit_count": len(audit),
    }).to_dict()
