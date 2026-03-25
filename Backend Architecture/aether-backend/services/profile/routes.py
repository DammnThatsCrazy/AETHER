"""
Aether Service — Profile 360 API

Holistic user/entity profile view composing data from all Aether subsystems.
Every response includes provenance, respects tenant scoping, and does not
duplicate logic from existing services.

Endpoints:
    GET /v1/profile/{user_id}                    Full profile (omniview)
    GET /v1/profile/{user_id}/timeline           Event timeline
    GET /v1/profile/{user_id}/graph              Graph relationships
    GET /v1/profile/{user_id}/intelligence       Risk + features + model outputs
    GET /v1/profile/{user_id}/identifiers        All linked identifiers
    GET /v1/profile/{user_id}/provenance         Source attribution for all data
    GET /v1/profile/resolve                      Resolve any identifier to profile
    GET /v1/profile/{user_id}/lake/{domain}      Lake data by domain
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request, Query

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_registry, get_cache, get_graph
from repositories.repos import IdentityRepository, AnalyticsRepository, ConsentRepository
from repositories.lake import gold_identity, gold_market, gold_onchain, gold_social
from services.profile.resolver import ProfileResolver
from services.profile.composer import ProfileComposer

logger = get_logger("aether.service.profile")
router = APIRouter(prefix="/v1/profile", tags=["Profile 360"])

# Lazy-initialized singleton
_composer: Optional[ProfileComposer] = None
_resolver: Optional[ProfileResolver] = None


def _get_composer(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> ProfileComposer:
    global _composer, _resolver
    if _composer is None:
        identity_repo = IdentityRepository(graph, cache)
        analytics_repo = AnalyticsRepository(cache)
        consent_repo = ConsentRepository()
        _resolver = ProfileResolver(graph, cache)
        _composer = ProfileComposer(
            identity_repo=identity_repo,
            analytics_repo=analytics_repo,
            consent_repo=consent_repo,
            graph=graph,
            cache=cache,
            resolver=_resolver,
        )
    return _composer


def _get_resolver(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> ProfileResolver:
    global _resolver
    if _resolver is None:
        _resolver = ProfileResolver(graph, cache)
    return _resolver


# ── Full Profile ──────────────────────────────────────────────────────

@router.get("/{user_id}")
async def get_full_profile(
    user_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
    include_timeline: bool = Query(True, description="Include event timeline"),
    include_graph: bool = Query(True, description="Include graph relationships"),
    include_intelligence: bool = Query(True, description="Include risk/features/models"),
    include_lake: bool = Query(True, description="Include lake Gold data"),
    timeline_limit: int = Query(50, ge=1, le=500),
):
    """
    Full holistic profile view — everything Aether knows about this entity.

    Composes: identity, identifiers, consent, timeline, graph, intelligence, lake data.
    All data includes provenance. Respects tenant scoping.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    result = await composer.get_full_profile(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        include_timeline=include_timeline,
        include_graph=include_graph,
        include_intelligence=include_intelligence,
        include_lake=include_lake,
        timeline_limit=timeline_limit,
    )

    metrics.increment("profile_360_full_view")
    return APIResponse(data=result).to_dict()


# ── Timeline ──────────────────────────────────────────────────────────

@router.get("/{user_id}/timeline")
async def get_timeline(
    user_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
    limit: int = Query(100, ge=1, le=1000),
    event_type: Optional[str] = Query(None),
):
    """Paginated event timeline for a user."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    events = await composer.get_timeline(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        limit=limit,
        event_type=event_type,
    )

    return APIResponse(data={"user_id": user_id, "events": events, "count": len(events)}).to_dict()


# ── Graph ─────────────────────────────────────────────────────────────

@router.get("/{user_id}/graph")
async def get_graph_context(
    user_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
):
    """Graph relationships around the user."""
    request.state.tenant.require_permission("read")

    graph_data = await composer._compose_graph(user_id)
    return APIResponse(data={"user_id": user_id, **graph_data}).to_dict()


# ── Intelligence ──────────────────────────────────────────────────────

@router.get("/{user_id}/intelligence")
async def get_intelligence(
    user_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
):
    """Risk scores, features, and model outputs for a user."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    intel = await composer._compose_intelligence(user_id, tenant.tenant_id)
    return APIResponse(data={"user_id": user_id, **intel}).to_dict()


# ── Identifiers ───────────────────────────────────────────────────────

@router.get("/{user_id}/identifiers")
async def get_identifiers(
    user_id: str,
    request: Request,
    resolver: ProfileResolver = Depends(_get_resolver),
):
    """All linked identifiers (wallets, emails, devices, sessions, social)."""
    request.state.tenant.require_permission("read")

    tenant = request.state.tenant
    identifiers = await resolver.get_all_identifiers(user_id, tenant_id=tenant.tenant_id)
    return APIResponse(data={"user_id": user_id, "identifiers": identifiers}).to_dict()


# ── Provenance ────────────────────────────────────────────────────────

@router.get("/{user_id}/provenance")
async def get_provenance(
    user_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
):
    """Source attribution for all data associated with this user."""
    request.state.tenant.require_permission("read")

    provenance = await composer.get_provenance(user_id)
    return APIResponse(data=provenance).to_dict()


# ── Resolve ───────────────────────────────────────────────────────────

@router.get("/resolve")
async def resolve_identifier(
    request: Request,
    resolver: ProfileResolver = Depends(_get_resolver),
    wallet: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    device: Optional[str] = Query(None),
    session: Optional[str] = Query(None),
    social: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
):
    """
    Resolve any identifier to a canonical profile ID.

    Pass exactly one identifier type. Returns the resolved user_id
    or 404 if not resolvable.
    """
    request.state.tenant.require_permission("read")

    tenant = request.state.tenant
    resolved = await resolver.resolve(
        tenant_id=tenant.tenant_id,
        wallet_address=wallet,
        email=email,
        device_id=device,
        session_id=session,
        social_handle=social,
        customer_id=customer,
    )

    if not resolved:
        raise NotFoundError("No profile found for the given identifier")

    return APIResponse(data={"resolved_user_id": resolved}).to_dict()


# ── Lake Data by Domain ──────────────────────────────────────────────

@router.get("/{user_id}/lake/{domain}")
async def get_lake_data(
    user_id: str,
    domain: str,
    request: Request,
):
    """Query Gold-tier lake data for a user in a specific domain."""
    request.state.tenant.require_permission("read")

    domain_repos = {
        "identity": gold_identity,
        "market": gold_market,
        "onchain": gold_onchain,
        "social": gold_social,
    }

    repo = domain_repos.get(domain)
    if not repo:
        raise BadRequestError(f"Unknown domain: {domain}. Available: {list(domain_repos.keys())}")

    records = await repo.get_metrics(user_id)
    return APIResponse(data={
        "user_id": user_id,
        "domain": domain,
        "records": records,
        "count": len(records),
    }).to_dict()
