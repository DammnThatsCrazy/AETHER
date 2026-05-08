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
from dependencies.providers import get_cache, get_graph
from repositories.repos import (
    AgentConfigRepository,
    AgentExecutionRepository,
    AnalyticsRepository,
    BehaviorProfileRepository,
    ConsentRepository,
    DelegationRepository,
    IdentityRepository,
    TransferRepository,
)
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


# ── Profile 360 sub-resources (additive) ──────────────────────────────
#
# These endpoints layer Profile 360 dimensions onto the existing entity
# (user_id) URL space. They reuse the new repositories directly so they
# work in both the in-memory dev mode and production. Existing endpoints
# above are unchanged.

_user_agent_repo = AgentConfigRepository()
_user_exec_repo = AgentExecutionRepository()
_transfer_repo = TransferRepository()
_behavior_repo = BehaviorProfileRepository()
_delegation_repo: Optional[DelegationRepository] = None


def _get_delegation_repo(cache: CacheClient = Depends(get_cache)) -> DelegationRepository:
    global _delegation_repo
    if _delegation_repo is None:
        _delegation_repo = DelegationRepository(cache=cache)
    return _delegation_repo


@router.get("/{user_id}/agents")
async def get_owned_agents(user_id: str, request: Request):
    """User/org-owned LLM agents whose owner_entity_id matches this profile."""
    request.state.tenant.require_permission("read")
    rows = await _user_agent_repo.list_for_owner(user_id)
    rows = [r for r in rows if r.get("tenant_id") == request.state.tenant.tenant_id]
    return APIResponse(data={"user_id": user_id, "agents": rows, "count": len(rows)}).to_dict()


@router.get("/{user_id}/delegations")
async def get_delegations(
    user_id: str,
    request: Request,
    role: str = Query("both", description="grantor | grantee | both"),
    active: bool = Query(True),
    repo: DelegationRepository = Depends(_get_delegation_repo),
):
    """Delegations granted by, or received by, this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    granted: list = []
    received: list = []
    if role in ("grantor", "both"):
        granted = await repo.find_many(
            filters={"grantor_entity_id": user_id}, limit=200,
        )
        granted = [r for r in granted if r.get("tenant_id") == tenant.tenant_id]
    if role in ("grantee", "both"):
        received = (
            await repo.active_for(user_id) if active
            else await repo.find_many(filters={"grantee_entity_id": user_id}, limit=200)
        )
        received = [r for r in received if r.get("tenant_id") == tenant.tenant_id]
    return APIResponse(data={
        "user_id": user_id,
        "granted": granted,
        "received": received,
    }).to_dict()


@router.get("/{user_id}/flows")
async def get_flows(
    user_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    """Asset transfers in or out of this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await _transfer_repo.list_for_entity(user_id, limit=limit)
    rows = [r for r in rows if r.get("tenant_id") == tenant.tenant_id]
    return APIResponse(data={
        "user_id": user_id,
        "transfers": rows,
        "count": len(rows),
    }).to_dict()


@router.get("/{user_id}/behavior")
async def get_behavior(user_id: str, request: Request):
    """Latest derived behavior snapshot (automation_ratio, decision_latency, ...)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _behavior_repo.find_by_id(user_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        # Return an empty-but-shaped response rather than 404 — derived data
        # may simply not have been computed yet.
        return APIResponse(data={
            "user_id": user_id,
            "snapshot": None,
            "computed": False,
        }).to_dict()
    return APIResponse(data={
        "user_id": user_id,
        "snapshot": record,
        "computed": True,
    }).to_dict()


@router.get("/{user_id}/predictions")
async def get_predictions(user_id: str, request: Request):
    """Next-likely-action and risk-flag projections (derived).

    Reads from the behavior_profiles snapshot's predicted_next + anomaly_flags.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _behavior_repo.find_by_id(user_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        return APIResponse(data={
            "user_id": user_id,
            "predicted_next": None,
            "risk_flags": [],
            "risk_score": 0.0,
        }).to_dict()
    return APIResponse(data={
        "user_id": user_id,
        "predicted_next": record.get("predicted_next") or {},
        "risk_flags": record.get("anomaly_flags") or [],
        "risk_score": record.get("risk_score") or 0.0,
    }).to_dict()


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
