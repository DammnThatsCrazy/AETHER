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

import asyncio
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
from repositories.repos import EntityRepository
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.agent.deployments.routes")

deployments_router = APIRouter(prefix="/v1/agent/deployments", tags=["Agent Deployments"])
lineage_router = APIRouter(prefix="/v1/agent/agents", tags=["Agent Lineage"])
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
_CANONICAL_AGENT_BINDING_LIST_LIMIT = 100


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Correlation-ID", "")


def _actor_id(request: Request) -> str:
    tenant = request.state.tenant
    return getattr(tenant, "user_id", None) or getattr(tenant, "tenant_id", "operator")


def _require_registry_enabled() -> None:
    cfg = settings.external_agent_telemetry
    if not (cfg.enabled or cfg.registry_enabled):
        raise BadRequestError("External agent deployment registry is not enabled")


def _require_marketplace_catalog_route_enabled() -> None:
    cfg = settings.external_agent_telemetry
    if not (cfg.marketplace_catalog_enabled or cfg.registry_enabled):
        raise BadRequestError("External agent marketplace catalog is not enabled")


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
    agent_source_namespace: Optional[str] = Field(default=None, max_length=64)
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


class AgentIdentityBindingRequest(BaseModel):
    canonical_agent_entity_id: str = Field(..., min_length=1, max_length=256)


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


@deployments_router.put("/{deployment_id}/identity-binding")
async def bind_deployment_agent_identity(
    deployment_id: str,
    body: AgentIdentityBindingRequest,
    request: Request,
):
    """Bind a namespaced deployment source ref to a canonical tenant Agent.

    This is a tenant-admin assertion persisted by Aether. SDK events cannot
    create or change the binding; the target Agent must already exist in this
    tenant. A source ref without this binding remains unresolved.
    """
    _require_registry_enabled()
    tenant = _tenant(request)
    deployment = await _repo().get(tenant.tenant_id, deployment_id)
    source_namespace = str(deployment.get("agent_source_namespace") or "")
    source_agent_ref = str(deployment.get("agent_id") or "")
    if not source_namespace or not source_agent_ref:
        raise BadRequestError(
            "Deployment requires agent_source_namespace and agent_id before identity binding"
        )

    entity = await EntityRepository().find_by_id(body.canonical_agent_entity_id)
    if (
        not entity
        or entity.get("tenant_id") != tenant.tenant_id
        or entity.get("entity_type") != "agent"
        or entity.get("entity_id") != body.canonical_agent_entity_id
    ):
        raise BadRequestError(
            "canonical_agent_entity_id must identify an Agent entity in this tenant"
        )

    from actions.agent_marketplace.identity_binding import (
        AgentDeploymentIdentityBindingRepository,
    )

    record = await AgentDeploymentIdentityBindingRepository().bind(
        tenant_id=tenant.tenant_id,
        source_namespace=source_namespace,
        source_agent_ref=source_agent_ref,
        canonical_agent_entity_id=body.canonical_agent_entity_id,
        bound_by=_actor_id(request),
        source_deployment_id=deployment_id,
    )
    if not settings.external_agent_telemetry.graph_enabled:
        record["graph_projection_status"] = "disabled"
    else:
        try:
            from actions.agent_marketplace.identity_binding import (
                build_agent_deployment_identity_mutations,
            )
            from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox

            queued = await AgentMarketplaceGraphProjectionOutbox().enqueue_mutations(
                tenant.tenant_id,
                deployment_id,
                build_agent_deployment_identity_mutations(deployment, record),
            )
            record["graph_projection_status"] = (
                queued.get("graph_projection_status") or "failed"
            )
        except Exception as exc:
            logger.warning(
                "agent identity graph enqueue failed",
                extra={"tenant_id": tenant.tenant_id, "deployment_id": deployment_id,
                       "error": type(exc).__name__},
            )
            record["graph_projection_status"] = "failed"
    return APIResponse(data=record).to_dict()


@deployments_router.get("/{deployment_id}/identity-binding")
async def get_deployment_agent_identity_binding(
    deployment_id: str,
    request: Request,
):
    """Return this tenant deployment's validated canonical identity mapping."""
    _require_registry_enabled()
    tenant = _tenant(request)
    deployment = await _repo().get(tenant.tenant_id, deployment_id)
    source_namespace = str(deployment.get("agent_source_namespace") or "").strip().lower()
    source_agent_ref = str(deployment.get("agent_id") or "").strip()
    base = {
        "tenant_id": tenant.tenant_id,
        "deployment_id": deployment_id,
        "source_namespace": source_namespace or None,
        "source_agent_ref": source_agent_ref or None,
    }
    if not source_namespace or not source_agent_ref:
        return APIResponse(data={
            **base,
            "status": "unresolved",
            "reason": "deployment_source_reference_missing",
        }).to_dict()

    from actions.agent_marketplace.identity_binding import (
        AgentDeploymentIdentityBindingRepository,
    )

    try:
        bindings = await AgentDeploymentIdentityBindingRepository().find_for_source(
            tenant.tenant_id, source_namespace, source_agent_ref,
        )
    except Exception as exc:
        return APIResponse(data={
            **base,
            "status": "unavailable",
            "reason": "identity_binding_authority_unavailable",
            "error_type": type(exc).__name__,
        }).to_dict()

    if len(bindings) > 1:
        return APIResponse(data={
            **base,
            "status": "ambiguous",
            "reason": "multiple_active_identity_bindings",
        }).to_dict()
    if not bindings:
        return APIResponse(data={
            **base,
            "status": "unresolved",
            "reason": "identity_binding_not_found",
        }).to_dict()

    binding = bindings[0]
    canonical_id = str(binding.get("canonical_agent_entity_id") or "")
    if (
        binding.get("tenant_id") != tenant.tenant_id
        or binding.get("source_namespace") != source_namespace
        or binding.get("source_agent_ref") != source_agent_ref
        or binding.get("status") != "active"
        or binding.get("binding_authority") != "tenant_admin_explicit"
        or not canonical_id
    ):
        return APIResponse(data={
            **base,
            "status": "unresolved",
            "reason": "identity_binding_record_invalid",
        }).to_dict()

    try:
        entity = await EntityRepository().find_by_id(canonical_id)
    except Exception as exc:
        return APIResponse(data={
            **base,
            "status": "unavailable",
            "reason": "canonical_agent_authority_unavailable",
            "error_type": type(exc).__name__,
        }).to_dict()
    if (
        not entity
        or entity.get("tenant_id") != tenant.tenant_id
        or entity.get("entity_type") != "agent"
        or entity.get("entity_id") != canonical_id
    ):
        return APIResponse(data={
            **base,
            "status": "unresolved",
            "reason": "canonical_agent_entity_not_found_in_tenant",
        }).to_dict()

    return APIResponse(data={
        **base,
        "status": "matched",
        "reason": "tenant_admin_explicit_binding",
        "binding_authority": "tenant_admin_explicit",
        "canonical_agent_entity_id": canonical_id,
        **({"bound_at": binding["bound_at"]} if isinstance(binding.get("bound_at"), str) else {}),
    }).to_dict()


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
    deployment_repo = _repo()
    records = await deployment_repo.list(
        tenant.tenant_id, status=status, platform=platform, agent_id=agent_id
    )
    identity_binding_lookup = {
        "status": "not_requested" if not agent_id else "unresolved",
        "bindings_scanned": 0,
        "truncated": False,
    }
    if agent_id:
        try:
            canonical_entity = await EntityRepository().find_by_id(agent_id)
        except Exception:
            canonical_entity = None
            identity_binding_lookup["status"] = "unavailable"
        if (
            canonical_entity
            and canonical_entity.get("tenant_id") == tenant.tenant_id
            and canonical_entity.get("entity_type") == "agent"
            and canonical_entity.get("entity_id") == agent_id
        ):
            from actions.agent_marketplace.identity_binding import (
                AgentDeploymentIdentityBindingRepository,
            )

            try:
                bindings = await AgentDeploymentIdentityBindingRepository().find_many(
                    filters={
                        "tenant_id": tenant.tenant_id,
                        "canonical_agent_entity_id": agent_id,
                        "binding_authority": "tenant_admin_explicit",
                        "status": "active",
                    },
                    limit=_CANONICAL_AGENT_BINDING_LIST_LIMIT + 1,
                )
            except Exception:
                bindings = []
                identity_binding_lookup["status"] = "unavailable"
            else:
                identity_binding_lookup["truncated"] = (
                    len(bindings) > _CANONICAL_AGENT_BINDING_LIST_LIMIT
                )
                bindings = bindings[:_CANONICAL_AGENT_BINDING_LIST_LIMIT]
                identity_binding_lookup["bindings_scanned"] = len(bindings)
                matched_count = 0
                try:
                    for binding in bindings:
                        namespace = str(binding.get("source_namespace") or "").strip().lower()
                        source_ref = str(binding.get("source_agent_ref") or "").strip()
                        source_deployment_id = str(binding.get("source_deployment_id") or "").strip()
                        if (
                            binding.get("tenant_id") != tenant.tenant_id
                            or binding.get("canonical_agent_entity_id") != agent_id
                            or binding.get("binding_authority") != "tenant_admin_explicit"
                            or binding.get("status") != "active"
                            or not namespace
                            or not source_ref
                            or not source_deployment_id
                        ):
                            continue
                        deployment = await deployment_repo.get_record(
                            tenant.tenant_id, source_deployment_id,
                        )
                        if (
                            not deployment
                            or deployment.get("tenant_id") != tenant.tenant_id
                            or deployment.get("id") != source_deployment_id
                            or str(deployment.get("agent_source_namespace") or "").lower() != namespace
                            or deployment.get("agent_id") != source_ref
                            or (status and deployment.get("status") != status)
                            or (platform and deployment.get("external_platform") != platform)
                        ):
                            continue
                        matched_count += 1
                        if not any(row.get("id") == source_deployment_id for row in records):
                            records.append(deployment)
                except Exception:
                    identity_binding_lookup["status"] = "unavailable"
                else:
                    if identity_binding_lookup["status"] != "unavailable":
                        identity_binding_lookup["status"] = (
                            "partial" if identity_binding_lookup["truncated"] else (
                                "matched" if matched_count else "unresolved"
                            )
                        )
        elif identity_binding_lookup["status"] != "unavailable":
            identity_binding_lookup["status"] = "unresolved"

    records.sort(key=lambda row: row.get("updated_at", ""), reverse=True)
    return APIResponse(data={
        "deployments": records,
        "count": len(records),
        "identity_binding_lookup": identity_binding_lookup,
    }).to_dict()


@deployments_router.get("/marketplace/catalog")
async def public_marketplace_catalog(
    request: Request,
    limit: int = Query(default=100, ge=1, le=250),
):
    """Read the public-source catalog snapshot under the active tenant scope.

    Public listing facts are shared observations, not tenant-owned deployment
    data. Authentication and ``agent:manage`` still gate access to the route;
    the response deliberately excludes marketplace configuration and private
    bot content.
    """
    _require_marketplace_catalog_route_enabled()
    tenant = _tenant(request)
    from actions.agent_marketplace.catalog import MarketplaceCatalogRepository

    repository = MarketplaceCatalogRepository()
    status = await repository.status()
    listings = await repository.list_listings(limit=limit)
    if not settings.external_agent_telemetry.marketplace_catalog_enabled:
        source_status = "disabled"
    else:
        source_status = str(status.get("source_status") or "never_observed")
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "listings": listings,
        "observed_at": status.get("observed_at"),
        "source_status": source_status,
        "last_success_at": status.get("last_success_at"),
        "listing_count": status.get("listing_count", len(listings)),
        "graph_projection_status": status.get("graph_projection_status", "not_started"),
    }).to_dict()


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


@lineage_router.get("/{root_agent_ref}/lineage")
async def agent_spawn_lineage(
    root_agent_ref: str,
    request: Request,
    max_depth: int = Query(default=8, ge=1, le=8),
):
    """Orchestrator -> sub-agent tree with per-agent tool/outcome rollups.

    Tenant-scoped and source-reported: the tree says which agent references
    spawned which, never who controls them.
    """
    _require_registry_enabled()
    tenant = _tenant(request)
    from actions.agent.lineage import read_lineage_facts, source_is_truncated

    try:
        from dependencies.providers import get_cache
        from repositories.repos import AnalyticsRepository

        facts = await read_lineage_facts(
            AnalyticsRepository(get_cache()),
            tenant_id=tenant.tenant_id,
            root_agent_ref=root_agent_ref,
            max_depth=max_depth,
        )
        shape = facts["shape"]
        if source_is_truncated(shape):
            # A capped read can drop an older root's edges or an agent's older
            # activity, so an empty or small tree is not proof of absence.
            shape["source_status"] = "incomplete"
        else:
            shape["source_status"] = "available" if shape["totals"]["agent_count"] > 1 else "empty"
    except Exception as exc:
        logger.warning(
            "agent spawn lineage unavailable",
            extra={"tenant_id": tenant.tenant_id, "error": type(exc).__name__},
        )
        shape = {
            "tenant_id": tenant.tenant_id,
            "root_agent_ref": root_agent_ref,
            "source_status": "unavailable",
            "tree": None,
        }
    return APIResponse(data=shape).to_dict()


BEHAVIOR_FACT_LIMIT = 1000


async def _behavior_facts(tenant_id: str, agent_ref: str) -> tuple[list[Any], bool]:
    """Bounded tenant-scoped Silver facts for one agent and its spawn edges."""
    from dependencies.providers import get_cache
    from intelligence.agent_behavior.facts import normalize_rows
    from repositories.repos import AnalyticsRepository

    analytics = AnalyticsRepository(get_cache())
    rows = await analytics.query_silver(
        "silver_agent_execution_facts", {"tenant_id": tenant_id, "agent_id": agent_ref},
        limit=BEHAVIOR_FACT_LIMIT + 1,
    )
    truncated = len(rows) > BEHAVIOR_FACT_LIMIT
    spawns = await analytics.query_silver(
        "silver_agent_execution_facts",
        {"tenant_id": tenant_id, "source_event_type": "agent_subagent_spawned"}, limit=BEHAVIOR_FACT_LIMIT,
    )
    return normalize_rows(rows[:BEHAVIOR_FACT_LIMIT] + spawns, tenant_id), truncated


@lineage_router.get("/{agent_ref}/behavior")
async def agent_behavior_read_model(agent_ref: str, request: Request):
    """Agent360 behavior read model: rebuildable, evidence-qualified, with what
    Aether cannot see. Source-reported agent refs; not an identity resolution."""
    _require_registry_enabled()
    tenant = _tenant(request)
    from intelligence.agent_behavior.read_models import agent360_behavior

    try:
        facts, truncated = await _behavior_facts(tenant.tenant_id, agent_ref)
        data = agent360_behavior(facts, agent_ref, truncated=truncated)
    except Exception as exc:
        logger.warning("agent behavior read model unavailable",
                       extra={"tenant_id": tenant.tenant_id, "error": type(exc).__name__})
        data = {"agent_ref": agent_ref, "source_status": "unavailable", "sections": None}
    return APIResponse(data=data).to_dict()


@lineage_router.get("/{agent_ref}/decisions/{decision_id}")
async def agent_decision_detail(agent_ref: str, decision_id: str, request: Request):
    """One reconstructed DecisionEnvelope with attribution, responsibility roles
    and a labelled counterfactual."""
    _require_registry_enabled()
    tenant = _tenant(request)
    from intelligence.agent_behavior.read_models import decision_detail
    from repositories.repos import DelegationRepository

    facts, _ = await _behavior_facts(tenant.tenant_id, agent_ref)
    grants = await DelegationRepository().active_for(agent_ref, tenant.tenant_id)
    detail = decision_detail(facts, decision_id, grants=grants)
    if detail is None or detail["envelope"]["decision_actor"].get("value") != agent_ref:
        raise NotFoundError("decision not found")
    return APIResponse(data=detail).to_dict()


@deployments_router.get("/{deployment_id}/runs")
async def list_agent_runs(
    deployment_id: str,
    request: Request,
    limit: int = Query(default=500, ge=1, le=1000),
):
    """List bounded source-reported run references for one owned deployment."""
    _require_registry_enabled()
    tenant = _tenant(request)
    await _repo().get(tenant.tenant_id, deployment_id)

    try:
        from dependencies.providers import get_cache
        from repositories.repos import AnalyticsRepository

        rows = await AnalyticsRepository(get_cache()).query_silver(
            "silver_agent_execution_facts",
            {"tenant_id": tenant.tenant_id, "deployment_id": deployment_id},
            limit=limit,
        )
    except Exception as exc:
        logger.warning(
            "agent deployment run index unavailable",
            extra={"tenant_id": tenant.tenant_id, "deployment_id": deployment_id,
                   "error": type(exc).__name__},
        )
        return APIResponse(data={
            "tenant_id": tenant.tenant_id,
            "deployment_id": deployment_id,
            "source_status": "unavailable",
            "runs": [],
            "source_rows_scanned": 0,
            "runs_truncated": False,
        }).to_dict()

    runs: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id") or "")
        if (
            not run_id
            or len(run_id) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in run_id)
        ):
            continue
        occurred_at = str(row.get("occurred_at") or "")
        summary = runs.get(run_id)
        if summary is None:
            summary = {
                "run_id": run_id,
                "first_event_at": occurred_at,
                "last_event_at": occurred_at,
                "event_count": 0,
                "event_types": [],
                "run_correlation_source": row.get("run_correlation_source"),
            }
            runs[run_id] = summary
        # query_silver is newest-first: the first row for a run is its latest.
        summary["first_event_at"] = occurred_at or summary["first_event_at"]
        summary["event_count"] += 1
        event_type = str(
            row.get("source_event_type") or row.get("event_name") or row.get("event_type") or ""
        )
        if event_type and event_type not in summary["event_types"] and len(summary["event_types"]) < 12:
            summary["event_types"].append(event_type)

    recent_runs = list(runs.values())
    return APIResponse(data={
        "tenant_id": tenant.tenant_id,
        "deployment_id": deployment_id,
        "source_status": "available" if runs else "empty",
        "runs": recent_runs[:100],
        "source_rows_scanned": len(rows),
        "runs_truncated": len(rows) >= limit or len(recent_runs) > 100,
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
    from actions.agent_marketplace.authority import AgentRunAuthorityResolver

    resolver = AgentRunAuthorityResolver()
    lookup_limit = asyncio.Semaphore(16)

    async def make_evidence(row: dict[str, Any]) -> dict[str, Any]:
        async with lookup_limit:
            resolved = await resolver.resolve(row)
        return {
            "source_event_id": row.get("source_event_id"),
            "event_type": row.get("source_event_type") or row.get("event_name"),
            "occurred_at": row.get("occurred_at"),
            "evidence_authority": "tenant_source_asserted",
            "task_ref": row.get("task_ref"),
            "action_ref": row.get("action_ref"),
            "action_type": row.get("action_type"),
            "resource_ref": row.get("resource_ref"),
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
            "payment_intent_ref": row.get("payment_intent_ref"),
            "settlement_event_ref": row.get("settlement_event_ref"),
            "delegation_resolution": resolved["delegation_resolution"],
            "delegation_authorization": resolved["delegation_authorization"],
            "execution_occurrence": resolved["execution_occurrence"],
            "economic_outcome": resolved["economic_outcome"],
            "tool_name": row.get("tool_name"),
            "status": row.get("status"),
            "outcome_ref": row.get("outcome_ref"),
            "outcome": row.get("outcome"),
            "trace_id": row.get("trace_id"),
            "causation_id": row.get("causation_id"),
        }

    evidence = await asyncio.gather(*(make_evidence(row) for row in rows))

    kinds = {item.get("event_type") for item in evidence}
    has_trigger = any(item.get("trigger_ref") or item.get("trigger_type") for item in evidence)
    has_policy = "agent_policy_evaluated" in kinds
    has_delegation = "agent_delegated_task" in kinds or any(
        item.get("delegation_ref") for item in evidence
    )
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
    cursor: str | None = Query(default=None, max_length=2048),
    outbox_cursor: str | None = Query(default=None, max_length=2048),
):
    """Report queue coverage, pending retries, and dead letters for one tenant."""
    _require_kyber_enabled()
    _require_perm(request, "admin")
    from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox

    try:
        report = await AgentMarketplaceGraphProjectionOutbox().reconcile(
            tenant_id, limit=limit, cursor=cursor, outbox_cursor=outbox_cursor,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    return APIResponse(data=report).to_dict()


@kyber_router.get("/graph-projection/state-check")
async def check_agent_graph_projection_state(
    request: Request,
    tenant_id: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Compare canonical tenant evidence with persisted graph state, read-only.

    This independent check does not consult the projection outbox and never
    mutates graph state. A bounded or unavailable scan is reported as partial.
    """
    _require_kyber_enabled()
    _require_perm(request, "admin")
    from actions.agent_marketplace.authority import AgentRunAuthorityResolver
    from actions.agent_marketplace.graph_state_check import (
        AgentEconomyGraphStateChecker,
        agent_run_authority_extension,
    )

    try:
        checker = AgentEconomyGraphStateChecker(
            authority_extensions=[
                agent_run_authority_extension(AgentRunAuthorityResolver())
            ],
        )
        report = await checker.reconcile(
            tenant_id,
            source_page_size=min(limit, 250),
            max_source_rows=limit,
            graph_edge_limit=limit,
            issue_limit=min(limit, 500),
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    report.update({
        "read_only": True,
        "graph_mutations_applied": False,
        "outbox_consulted": False,
    })
    return APIResponse(data=report).to_dict()


@kyber_router.post("/graph-projection/repair")
async def repair_agent_graph_projection(
    request: Request,
    tenant_id: str = Query(..., min_length=1, max_length=256),
    enqueue_missing: bool = Query(default=True),
    replay_dead_letters: bool = Query(default=True),
    replay_persisted: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=1000),
    cursor: str | None = Query(default=None, max_length=2048),
    outbox_cursor: str | None = Query(default=None, max_length=2048),
):
    """Re-enqueue missing source projections or replay terminal outbox rows."""
    _require_kyber_enabled()
    _require_perm(request, "admin")
    from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox

    try:
        result = await AgentMarketplaceGraphProjectionOutbox().repair(
            tenant_id,
            enqueue_missing=enqueue_missing,
            replay_dead_letters=replay_dead_letters,
            replay_persisted=replay_persisted,
            limit=limit,
            cursor=cursor,
            outbox_cursor=outbox_cursor,
        )
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
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
