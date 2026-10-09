"""
Aether Service — Identity Resolution
Admin routes for managing resolution config, pending decisions, clusters,
batch jobs, and audit trails.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.common.common import APIResponse, ConflictError, ForbiddenError, NotFoundError
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_graph, get_producer
from repositories.repos import IdentityRepository

from .models import ResolutionConfigUpdate
from .repository import ResolutionRepository
from .rules import ResolutionConfig, ResolutionRulesEngine
from .signals import default_signals
from .engine import IdentityResolutionEngine

logger = get_logger("aether.service.resolution")
router = APIRouter(prefix="/v1/resolution", tags=["Identity Resolution"])


def _legacy_graph_unavailable() -> None:
    """Fail closed while this legacy graph surface lacks tenant isolation."""
    raise HTTPException(
        status_code=503,
        detail="Legacy identity graph resolution is unavailable",
    )


# ── Module-level singletons (initialised lazily) ─────────────────────

_config: ResolutionConfig = ResolutionConfig()
_resolution_repo: Optional[ResolutionRepository] = None
_identity_repo: Optional[IdentityRepository] = None
_engine: Optional[IdentityResolutionEngine] = None


def _get_resolution_repo(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> ResolutionRepository:
    global _resolution_repo
    if _resolution_repo is None:
        _resolution_repo = ResolutionRepository(graph, cache)
    return _resolution_repo


def _get_identity_repo(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> IdentityRepository:
    global _identity_repo
    if _identity_repo is None:
        _identity_repo = IdentityRepository(graph, cache)
    return _identity_repo


def _get_engine(
    resolution_repo: ResolutionRepository = Depends(_get_resolution_repo),
    identity_repo: IdentityRepository = Depends(_get_identity_repo),
    producer: EventProducer = Depends(get_producer),
) -> IdentityResolutionEngine:
    global _engine
    if _engine is None:
        rules = ResolutionRulesEngine(_config)
        _engine = IdentityResolutionEngine(
            config=_config,
            signals=default_signals(),
            rules_engine=rules,
            repository=resolution_repo,
            identity_repo=identity_repo,
            producer=producer,
        )
    return _engine


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/cluster/{user_id}")
async def get_cluster(
    user_id: str,
    request: Request,
):
    """Unavailable until the legacy graph cluster read is tenant scoped."""
    _legacy_graph_unavailable()


@router.get("/pending")
async def list_pending_resolutions(
    request: Request,
    limit: int = 50,
    repo: ResolutionRepository = Depends(_get_resolution_repo),
):
    """List pending resolution decisions awaiting admin review."""
    tenant = request.state.tenant
    pending = await repo.get_pending_resolutions(tenant.tenant_id, limit=limit)
    return APIResponse(data=pending).to_dict()


@router.post("/pending/{decision_id}/approve")
async def approve_resolution(
    decision_id: str,
    request: Request,
):
    """Unavailable until approval uses a tenant-safe graph mutation path."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    _legacy_graph_unavailable()


@router.post("/pending/{decision_id}/reject")
async def reject_resolution(
    decision_id: str,
    request: Request,
    repo: ResolutionRepository = Depends(_get_resolution_repo),
    producer: EventProducer = Depends(get_producer),
):
    """Admin rejects a pending identity merge."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    existing = await repo._pending.find_by_id(decision_id)
    if not existing:
        raise NotFoundError("Resolution decision")
    if existing.get("tenant_id") != tenant.tenant_id:
        raise ForbiddenError("Resolution decision belongs to a different tenant")
    if existing.get("status") != "pending":
        raise ConflictError(f"Resolution decision is already {existing.get('status')}")

    record = await repo.reject_resolution(decision_id)

    await producer.publish(Event(
        topic=Topic.RESOLUTION_REJECTED,
        tenant_id=tenant.tenant_id,
        source_service="resolution",
        payload={
            "decision_id": decision_id,
            "rejected_at": record.get("resolved_at", ""),
        },
    ))

    return APIResponse(data=record).to_dict()


@router.get("/audit/{decision_id}")
async def get_audit_trail(
    decision_id: str,
    request: Request,
    repo: ResolutionRepository = Depends(_get_resolution_repo),
):
    """Get the audit trail for a resolution decision."""
    tenant = request.state.tenant
    records = await repo.get_audit(tenant.tenant_id, decision_id)
    if not records:
        raise NotFoundError("Audit trail")
    return APIResponse(data=records).to_dict()


@router.get("/config")
async def get_resolution_config(request: Request):
    """Get the current resolution engine configuration."""
    return APIResponse(data={
        "auto_merge_threshold": _config.auto_merge_threshold,
        "review_threshold": _config.review_threshold,
        "max_cluster_size": _config.max_cluster_size,
        "cooldown_hours": _config.cooldown_hours,
        "require_deterministic_for_auto": _config.require_deterministic_for_auto,
        "allow_probabilistic_auto_merge": _config.allow_probabilistic_auto_merge,
    }).to_dict()


@router.put("/config")
async def update_resolution_config(
    body: ResolutionConfigUpdate,
    request: Request,
):
    """Update resolution engine configuration thresholds. Requires admin — config is global."""
    tenant = request.state.tenant
    tenant.require_permission("admin")

    global _config, _engine

    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        if hasattr(_config, key):
            setattr(_config, key, value)

    # Reset engine so it picks up the new config
    _engine = None

    logger.info(f"Resolution config updated by tenant {tenant.tenant_id}: {updates}")

    return APIResponse(data={
        "auto_merge_threshold": _config.auto_merge_threshold,
        "review_threshold": _config.review_threshold,
        "max_cluster_size": _config.max_cluster_size,
        "cooldown_hours": _config.cooldown_hours,
        "require_deterministic_for_auto": _config.require_deterministic_for_auto,
        "allow_probabilistic_auto_merge": _config.allow_probabilistic_auto_merge,
        "updated_fields": list(updates.keys()),
    }).to_dict()


@router.post("/batch")
async def trigger_batch_job(
    request: Request,
):
    """Unavailable until batch matching uses tenant-safe graph reads."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    _legacy_graph_unavailable()
