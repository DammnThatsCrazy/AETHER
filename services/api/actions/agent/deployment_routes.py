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

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from config.settings import settings
from actions.agent.deployments import (
    AgentDeploymentRepository,
    get_deployment_repository,
)
from actions.agentic_observability.foundation import require_permission as _require_perm
from actions.agent_marketplace.models import AgentMarketplaceOrigin
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
    marketplace_origin: Optional[AgentMarketplaceOrigin] = None
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
    if record.get("marketplace_origin"):
        if not settings.external_agent_telemetry.graph_enabled:
            record["marketplace_origin_graph_projection_status"] = "disabled"
        else:
            try:
                from actions.agent_marketplace.lineage import build_marketplace_origin_mutations
                from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox

                queued = await AgentMarketplaceGraphProjectionOutbox().enqueue_mutations(
                    tenant.tenant_id,
                    str(record.get("id") or ""),
                    build_marketplace_origin_mutations(record),
                )
                record["marketplace_origin_graph_projection_status"] = (
                    queued.get("graph_projection_status") or "failed"
                )
            except Exception as exc:
                # Registry persistence is authoritative; source-to-outbox
                # reconciliation can recover this projection after a transient
                # store outage without losing the tenant's declaration.
                logger.warning(
                    "marketplace origin graph enqueue failed",
                    extra={"tenant_id": tenant.tenant_id, "deployment_id": record.get("id"),
                           "error": type(exc).__name__},
                )
                record["marketplace_origin_graph_projection_status"] = "failed"
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


@deployments_router.get("/{deployment_id}/runs/{run_id}/explanation")
async def explain_agent_run(
    deployment_id: str,
    run_id: str,
    request: Request,
    limit: int = 200,
):
    """Return an evidence timeline for one observed external-agent run.

    The response reports source assertions and their gaps. It never generates
    hidden reasoning or promotes telemetry claims into verified identity or
    policy authority.
    """
    _require_registry_enabled()
    tenant = _tenant(request)
    await _repo().get(tenant.tenant_id, deployment_id)
    if not run_id or len(run_id) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in run_id):
        raise BadRequestError("run_id must be a printable source reference of at most 256 characters")
    limit = min(max(limit, 1), 500)

    try:
        from dependencies.providers import get_cache
        from repositories.repos import AnalyticsRepository

        rows = await AnalyticsRepository(get_cache()).query_silver(
            "silver_agent_execution_facts",
            {
                "tenant_id": tenant.tenant_id,
                "deployment_id": deployment_id,
                "run_id": run_id,
            },
            limit=limit,
        )
    except Exception as exc:
        logger.warning(
            "agent run explanation evidence unavailable",
            extra={"tenant_id": tenant.tenant_id, "deployment_id": deployment_id,
                   "run_id": run_id, "error": type(exc).__name__},
        )
        return APIResponse(data={
            "tenant_id": tenant.tenant_id,
            "deployment_id": deployment_id,
            "run_id": run_id,
            "source_status": "unavailable",
            "evidence": [],
            "explanation_boundary": "source evidence unavailable; no causal explanation asserted",
        }).to_dict()

    rows.sort(key=lambda row: str(row.get("occurred_at") or ""))
    evidence = []
    for row in rows:
        evidence.append({
            "source_event_id": row.get("source_event_id"),
            "event_type": row.get("event_name"),
            "occurred_at": row.get("occurred_at"),
            "evidence_authority": "tenant_source_asserted",
            "task_ref": row.get("task_ref"),
            "action_ref": row.get("action_ref"),
            "action_type": row.get("action_type"),
            "trigger_ref": row.get("trigger_ref"),
            "trigger_type": row.get("trigger_type"),
            "decision_ref": row.get("decision_ref"),
            "policy": {
                "id": row.get("policy_id"),
                "version": row.get("policy_version"),
                "decision": row.get("policy_decision"),
                "reason_codes": row.get("policy_reason_codes") or [],
            } if row.get("policy_id") or row.get("policy_decision") else None,
            "delegation_ref": row.get("delegation_id"),
            "delegated_to_ref": row.get("delegated_to_ref"),
            "tool_name": row.get("tool_name"),
            "status": row.get("status"),
            "outcome_ref": row.get("outcome_ref"),
            "outcome": row.get("outcome"),
            "trace_id": row.get("trace_id"),
            "causation_id": row.get("causation_id"),
        })

    kinds = {item.get("event_type") for item in evidence}
    has_trigger = any(item.get("trigger_ref") or item.get("trigger_type") for item in evidence)
    has_policy = "agent_policy_evaluated" in kinds
    has_delegation = "agent_delegated_task" in kinds
    has_outcome = bool(kinds.intersection({"agent_task_completed", "agent_task_failed", "agent_outcome_recorded"}))
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "deployment_id": deployment_id,
        "run_id": run_id,
        "source_status": "available" if rows else "empty",
        "evidence_count": len(evidence),
        "evidence_truncated": len(evidence) >= limit,
        "evidence": evidence,
        "coverage": {
            "trigger_evidence": "observed" if has_trigger else "not_observed",
            "policy_evaluation": "observed" if has_policy else "not_observed",
            "delegation": "observed" if has_delegation else "not_observed",
            "outcome": "observed" if has_outcome else "not_observed",
        },
        "explanation_boundary": (
            "Observed event references establish sequence and attribution only. "
            "They do not establish hidden model reasoning or independently verify "
            "source-reported policy, delegation, or outcome claims."
        ),
    }).to_dict()


@kyber_router.post("/graph-projection/drain")
async def drain_agent_graph_projection(
    request: Request,
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """Drain one bounded batch of tenant agent-graph projections."""
    _require_kyber_enabled()
    _require_perm(request, "admin")
    if not settings.external_agent_telemetry.graph_enabled:
        raise BadRequestError("Agent graph projection is disabled")
    from actions.agent_marketplace.projection import AgentMarketplaceGraphOutboxWorker

    summary = await AgentMarketplaceGraphOutboxWorker().drain_once(
        tenant_id=tenant_id, limit=limit
    )
    metrics.increment(
        "agent_marketplace_graph_projection_drain_triggered_total",
        value=summary.get("processed", 0),
    )
    return APIResponse(data=summary).to_dict()


@kyber_router.get("/graph-projection/reconcile")
async def reconcile_agent_graph_projection(
    request: Request,
    tenant_id: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(default=500, ge=1, le=1000),
):
    """Report queue coverage, pending retries, and dead letters for one tenant."""
    _require_kyber_enabled()
    _require_perm(request, "admin")
    from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox

    report = await AgentMarketplaceGraphProjectionOutbox().reconcile(
        tenant_id, limit=limit
    )
    return APIResponse(data=report).to_dict()


@kyber_router.post("/graph-projection/repair")
async def repair_agent_graph_projection(
    request: Request,
    tenant_id: str = Query(..., min_length=1, max_length=256),
    enqueue_missing: bool = Query(default=True),
    replay_dead_letters: bool = Query(default=True),
    replay_persisted: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=1000),
):
    """Re-enqueue missing source projections or replay terminal outbox rows."""
    _require_kyber_enabled()
    _require_perm(request, "admin")
    from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox

    result = await AgentMarketplaceGraphProjectionOutbox().repair(
        tenant_id,
        enqueue_missing=enqueue_missing,
        replay_dead_letters=replay_dead_letters,
        replay_persisted=replay_persisted,
        limit=limit,
    )
    return APIResponse(data=result).to_dict()


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
