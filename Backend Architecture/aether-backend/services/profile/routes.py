"""
Aether Service — Profile 360 API

Holistic user/entity profile view composing data from all Aether subsystems.
Every response includes provenance, respects tenant scoping, and does not
duplicate logic from existing services.

Endpoints:
    GET /v1/profile/{user_id}                             Full profile (omniview)
    GET /v1/profile/{user_id}/timeline                    Event timeline
    GET /v1/profile/{user_id}/graph                       Graph relationships
    GET /v1/profile/{user_id}/intelligence                Risk + features + model outputs
    GET /v1/profile/{user_id}/identifiers                 All linked identifiers
    GET /v1/profile/{user_id}/provenance                  Source attribution for all data
    GET /v1/profile/resolve                               Resolve any identifier to profile
    GET /v1/profile/{user_id}/lake/{domain}               Lake data by domain

    New sub-resource endpoints (all support ?window=30d|60d|90d|lifetime):
    GET /v1/profile/{user_id}/tier                        Tier + percentile rank
    GET /v1/profile/{user_id}/asset-composition           Asset composition by category
    GET /v1/profile/{user_id}/pnl                         Realized + unrealized PNL
    GET /v1/profile/{user_id}/trading-profile             On-chain trading behavior
    GET /v1/profile/{user_id}/location-history            City-level location history
    GET /v1/profile/{user_id}/temporal-heatmap            24x7 activity heatmap + streaks
    GET /v1/profile/{user_id}/social-intelligence         Cross-platform social aggregation
    GET /v1/profile/{user_id}/journey-economics           Per-journey ROAS/CPA/LTV/retarget
    GET /v1/profile/{user_id}/device-performance          Conversion rate per device type
    GET /v1/profile/{user_id}/funnel                      Staged conversion funnel
    GET /v1/profile/{user_id}/time-to-convert             Stage-by-stage median times
    GET /v1/profile/{user_id}/retarget-recommendations    Pending analyst-review recommendations
    GET /v1/profile/{user_id}/web2                        TradFi + credit + bank accounts
    GET /v1/profile/{user_id}/protocol-metrics            Protocol TVL/volume/fees (onchain entities)
    GET /v1/profile/{user_id}/governance-activity         Governance proposals + votes
"""

from __future__ import annotations

from typing import Optional

from dependencies.providers import get_cache, get_graph
from fastapi import APIRouter, Depends, Query, Request
from repositories.lake import gold_identity, gold_market, gold_onchain, gold_social
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
from shared.cache.cache import CacheClient
from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger, metrics

from services.profile.aggregator import Profile360Aggregator
from services.profile.composer import ProfileComposer
from services.profile.intelligence import IntelligenceAggregator
from services.profile.resolver import ProfileResolver

logger = get_logger("aether.service.profile")
router = APIRouter(prefix="/v1/profile", tags=["Profile 360"])
profile360_router = APIRouter(prefix="/v1/profile360", tags=["Profile360 Kyber"])

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

    tenant = request.state.tenant
    graph_data = await composer._compose_graph(user_id, tenant_id=tenant.tenant_id)
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


# ── Profile360 normalized Kyber surfaces ────────────────────────────

def _parse_include(include: str) -> list[str]:
    return [part.strip() for part in include.split(",") if part.strip()]


@profile360_router.get("/{entity_type}/{entity_id}")
async def get_profile360_surface(
    entity_type: str,
    entity_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
    include: str = Query(
        "identity,system,financial,graph,timeline,analytics,debug",
        description="Comma-separated Kyber Profile360 sections to include",
    ),
    timeline_limit: int = Query(250, ge=1, le=1000),
    graph_limit: int = Query(750, ge=1, le=1000),
):
    """Normalized internal Profile360 payload for Kyber.

    Kyber is an internal control surface and receives the full tenant-scoped
    Profile360 view plus alignment audit metadata. End-user profile surfaces
    should call a separate redacted endpoint rather than this internal route.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    result = await composer.get_profile360_surface(
        entity_type=entity_type,
        entity_id=entity_id,
        tenant_id=tenant.tenant_id,
        include=_parse_include(include),
        timeline_limit=timeline_limit,
        graph_limit=graph_limit,
    )
    metrics.increment("profile360_kyber_surface_view")
    return APIResponse(data=result).to_dict()


@profile360_router.get("/{entity_type}/{entity_id}/graph")
async def get_profile360_graph(
    entity_type: str,
    entity_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
    limit: int = Query(750, ge=1, le=1000),
):
    """Tenant-scoped Profile360 graph chunk normalized for Kyber."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    graph = await composer._compose_graph(entity_id, tenant_id=tenant.tenant_id, limit=limit)
    return APIResponse(data={
        "entity_id": entity_id,
        "entity_type": entity_type,
        "tenant_id": tenant.tenant_id,
        "surface": "kyber_internal",
        **graph,
    }).to_dict()


@profile360_router.get("/{entity_type}/{entity_id}/timeline")
async def get_profile360_timeline(
    entity_type: str,
    entity_id: str,
    request: Request,
    composer: ProfileComposer = Depends(_get_composer),
    limit: int = Query(250, ge=1, le=1000),
    type: Optional[str] = Query(None),
):
    """Tenant-scoped normalized Profile360 event timeline for Kyber."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    events = await composer.get_timeline(
        user_id=entity_id,
        tenant_id=tenant.tenant_id,
        limit=limit,
        event_type=type,
    )
    return APIResponse(data={
        "entity_id": entity_id,
        "entity_type": entity_type,
        "tenant_id": tenant.tenant_id,
        "surface": "kyber_internal",
        "events": events,
        "count": len(events),
    }).to_dict()


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


# ── Profile 360 Aggregation Layer (drill-down endpoints) ────────────
#
# These endpoints are powered by Profile360Aggregator and return the
# normalized "frontend-ready" shape documented in
# docs/PROFILE-360-AGGREGATION.md. They are additive: existing routes above
# are unchanged. Frontends should prefer these routes when building a
# Profile 360 view because they pre-compute counts, summaries, and drill
# refs so the UI does not need to join across services.

_aggregator: Optional[Profile360Aggregator] = None


def _get_aggregator(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> Profile360Aggregator:
    global _aggregator
    if _aggregator is None:
        from repositories.repos import (
            AnalyticsRepository as _AR,
        )
        from repositories.repos import (
            DelegationRepository as _DR,
        )
        from repositories.repos import (
            IdentityRepository as _IR,
        )
        _aggregator = Profile360Aggregator(
            delegation_repo=_DR(cache=cache),
            analytics_repo=_AR(cache),
            identity_repo=_IR(graph, cache),
            graph=graph,
        )
    return _aggregator


_intel_agg: Optional[IntelligenceAggregator] = None


def _get_intel_agg() -> IntelligenceAggregator:
    global _intel_agg
    if _intel_agg is None:
        _intel_agg = IntelligenceAggregator()
    return _intel_agg


@router.get("/{user_id}/summary")
async def get_profile_summary(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Dashboard-ready concise snapshot.

    One call to power an entire profile header / tile bank. Pre-computes
    counts, financial rollups, latest behavior, and drill links for every
    Profile 360 dimension. Frontends should call this first and lazy-load
    individual drill endpoints on demand.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.summary(entity_id=user_id, tenant_id=tenant.tenant_id)
    metrics.increment("profile_360_summary")
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/wallets")
async def get_profile_wallets(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(100, ge=1, le=500),
):
    """Wallets owned by this entity (across all chains)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.wallets(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/sessions")
async def get_profile_sessions(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(100, ge=1, le=500),
):
    """Recent sessions with platform / device / event-count rollups."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.sessions(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/devices")
async def get_profile_devices(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(100, ge=1, le=500),
):
    """Devices linked deterministically (identity cluster) or observed in events."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.devices(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/platforms")
async def get_profile_platforms(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(50, ge=1, le=200),
):
    """Platform attribution breakdown from the event stream."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.platforms(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/protocols")
async def get_profile_protocols(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(50, ge=1, le=200),
):
    """Protocol interactions from the event stream and economic graph."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.protocols(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/journeys")
async def get_profile_journeys(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(50, ge=1, le=200),
):
    """Cross-session journey chains for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.journeys(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/rewards")
async def get_profile_rewards(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(100, ge=1, le=500),
):
    """Reward events earned by this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.rewards(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/financials")
async def get_profile_financials(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(200, ge=1, le=500),
):
    """Aggregated financial summary: inflows, outflows, settlements, recent transfers."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.financials(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/relationships")
async def get_profile_relationships(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(200, ge=1, le=500),
):
    """Typed normalized relationship list (ownership, delegation, financial flow)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.relationships(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/campaigns")
async def get_profile_campaigns(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(50, ge=1, le=200),
):
    """Campaign attribution derived from the analytics event stream."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await agg.campaigns(user_id, tenant.tenant_id, limit=limit)).to_dict()


@router.get("/{user_id}/drill/{object_type}/{object_id}")
async def drill_into_object(
    user_id: str,
    object_type: str,
    object_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Generic deep drill into any related Profile 360 object.

    Supports object_type in:
        agent, wallet, delegation, transfer, asset, entity,
        journey, payment_intent, settlement, agent_execution
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.drill(
        entity_id=user_id,
        tenant_id=tenant.tenant_id,
        object_type=object_type,
        object_id=object_id,
    )
    if not data.get("found"):
        raise NotFoundError(f"{object_type}/{object_id} not found in tenant scope")
    return APIResponse(data=data).to_dict()


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


# ── Intelligence Extension Routes ────────────────────────────────────
# All new sub-resources support ?window=30d|60d|90d|lifetime
# and return the standard SubResourceEnvelope.

_VALID_WINDOWS = {"30d", "60d", "90d", "lifetime"}


def _validate_window(window: str) -> str:
    if window not in _VALID_WINDOWS:
        raise BadRequestError(f"window must be one of: {sorted(_VALID_WINDOWS)}")
    return window


@router.get("/{user_id}/tier")
async def get_tier(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Entity tier (Whale/Shark/Dolphin/Fish/Shrimp) + percentile rank within tenant population."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.tier(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/asset-composition")
async def get_asset_composition(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """On-chain portfolio composition by asset category (stablecoin/ETH LST/BTC/altcoin/NFT)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.asset_composition(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/pnl")
async def get_pnl(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Realized + unrealized PNL and TVL delta. FIFO cost basis from silver_web3_events + CoinGecko prices."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.pnl(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/trading-profile")
async def get_trading_profile(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """On-chain trading behavior: favorite pairs, protocol loyalty, gas strategy, slippage."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.trading_profile(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/location-history")
async def get_location_history(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    limit: int = Query(default=20, ge=1, le=200),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """City-level location history with classification (primary/secondary/rare/one_time)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.location_history(user_id, tenant.tenant_id, window=window, limit=limit)).to_dict()


@router.get("/{user_id}/temporal-heatmap")
async def get_temporal_heatmap(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """24x7 activity density matrix + streak data in entity's primary timezone."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.temporal_heatmap(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/social-intelligence")
async def get_social_intelligence(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Cross-platform social aggregation: Twitter, Farcaster, Lens, Discord, GitHub."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.social_intelligence(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/journey-economics")
async def get_journey_economics(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    limit: int = Query(default=20, ge=1, le=200),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Per-journey ROAS, CPA, LTV, and retarget score."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.journey_economics(user_id, tenant.tenant_id, window=window, limit=limit)).to_dict()


@router.get("/{user_id}/device-performance")
async def get_device_performance(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Conversion rate and average conversion value per device type."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.device_performance(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/funnel")
async def get_funnel(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    campaign_id: str | None = Query(default=None),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Staged conversion funnel: Impression → Click → Visit → Connect → Swap → Liquidity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.funnel(user_id, tenant.tenant_id, window=window, campaign_id=campaign_id)).to_dict()


@router.get("/{user_id}/time-to-convert")
async def get_time_to_convert(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Median time between each funnel stage conversion."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.time_to_convert(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/retarget-recommendations")
async def get_retarget_recommendations(
    user_id: str,
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Pending and historical retargeting recommendations for analyst review."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(data=await intel.retarget_recommendations(user_id, tenant.tenant_id, status=status, limit=limit)).to_dict()


@router.get("/{user_id}/web2")
async def get_web2(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """TradFi portfolio, bank accounts, credit signals, and income estimates (requires 'credit' consent)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.web2(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/protocol-metrics")
async def get_protocol_metrics(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Protocol TVL history, volume, and fee revenue. Applicable to DAO/Protocol/DEX entity types."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.protocol_metrics(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/governance-activity")
async def get_governance_activity(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    limit: int = Query(default=20, ge=1, le=100),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Governance proposals, votes, and participation rate. Applicable to DAO/Protocol entity types."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.governance_activity(user_id, tenant.tenant_id, window=window, limit=limit)).to_dict()

# ── Decision & Outcome Intelligence subresources (additive) ─────────────

@router.get("/{user_id}/recommendations")
async def get_profile_recommendations(user_id: str, request: Request, limit: int = Query(default=20, ge=1, le=100)):
    """Entity-level recommendations linked to this Profile360 entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.intelligence.repositories import RecommendationRepository
    repo = RecommendationRepository()
    items = await repo.list_for_tenant(tenant.tenant_id, limit=limit, entity_id=user_id)
    return APIResponse(data={"entity_id": user_id, "items": items, "count": len(items)}).to_dict()


@router.get("/{user_id}/outcomes")
async def get_profile_outcomes(user_id: str, request: Request, limit: int = Query(default=20, ge=1, le=100)):
    """Outcome history linked to this Profile360 entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.intelligence.repositories import OutcomeRepository
    repo = OutcomeRepository()
    items = await repo.list_for_tenant(tenant.tenant_id, limit=limit, entity_id=user_id)
    return APIResponse(data={"entity_id": user_id, "items": items, "count": len(items)}).to_dict()


@router.get("/{user_id}/outcome-ledger")
async def get_profile_outcome_ledger(user_id: str, request: Request, limit: int = Query(default=100, ge=1, le=500)):
    """Entity-level outcome ledger linked to this Profile360 entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.intelligence.outcome_ledger import OutcomeLedgerAggregator
    from services.intelligence.repositories import (
        ActionFeedbackRepository,
        DecisionRepository,
        OutcomeRepository,
        RecommendationFeedbackRepository,
        RecommendationRepository,
    )
    recs = await RecommendationRepository().list_for_tenant(tenant.tenant_id, limit=limit, entity_id=user_id)
    rec_ids = {r.get("recommendation_id") or r.get("id") for r in recs}
    decisions = [d for d in await DecisionRepository().find_many({"tenant_id": tenant.tenant_id}, limit=limit) if d.get("recommendation_id") in rec_ids]
    decision_ids = {d.get("decision_id") for d in decisions}
    actions = [a for a in await ActionFeedbackRepository().find_many({"tenant_id": tenant.tenant_id}, limit=limit) if a.get("decision_id") in decision_ids]
    outcomes = await OutcomeRepository().list_for_tenant(tenant.tenant_id, limit=limit, entity_id=user_id)
    feedback = [f for f in await RecommendationFeedbackRepository().find_many({"tenant_id": tenant.tenant_id}, limit=limit) if f.get("recommendation_id") in rec_ids]
    ledger = OutcomeLedgerAggregator().build(recs, decisions, actions, outcomes, feedback)
    return APIResponse(data={"entity_id": user_id, **ledger}).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# AGENT PROFILE 360 ROUTES
# ═══════════════════════════════════════════════════════════════════════════

from services.profile.agent import AgentProfile360Composer  # noqa: E402

_agent_composer: Optional[AgentProfile360Composer] = None


def _get_agent_composer() -> AgentProfile360Composer:
    global _agent_composer
    if _agent_composer is None:
        _agent_composer = AgentProfile360Composer()
    return _agent_composer


@router.get("/{entity_id}/agent")
async def get_agent_profile360(entity_id: str, request: Request):
    """Full Agent Profile360 — all sections composed for the given agent."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    composer = _get_agent_composer()
    profile = await composer.compose(entity_id, tenant.tenant_id)
    return APIResponse(data=profile).to_dict()


@router.get("/{entity_id}/agent/identity")
async def get_agent_identity(entity_id: str, request: Request):
    """Agent identity section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["identity"]}).to_dict()


@router.get("/{entity_id}/agent/delegation")
async def get_agent_delegation(entity_id: str, request: Request):
    """Agent delegation section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["delegation"]}).to_dict()


@router.get("/{entity_id}/agent/subagents")
async def get_agent_subagents(entity_id: str, request: Request):
    """Agent subagent graph section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["subagent_graph"]}).to_dict()


@router.get("/{entity_id}/agent/tasks")
async def get_agent_tasks(entity_id: str, request: Request):
    """Agent task history section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["task_history"]}).to_dict()


@router.get("/{entity_id}/agent/tools")
async def get_agent_tools(entity_id: str, request: Request):
    """Agent tool usage section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["tool_usage"]}).to_dict()


@router.get("/{entity_id}/agent/resources")
async def get_agent_resources(entity_id: str, request: Request):
    """Agent resource usage section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["resource_usage"]}).to_dict()


@router.get("/{entity_id}/agent/x402")
async def get_agent_x402(entity_id: str, request: Request):
    """Agent x402 flows section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["x402_flows"]}).to_dict()


@router.get("/{entity_id}/agent/trust")
async def get_agent_trust(entity_id: str, request: Request):
    """Agent trust section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["trust"]}).to_dict()


@router.get("/{entity_id}/agent/outcomes")
async def get_agent_outcomes(entity_id: str, request: Request):
    """Agent outcomes section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["outcomes"]}).to_dict()


@router.get("/{entity_id}/agent/graph")
async def get_agent_graph(entity_id: str, request: Request):
    """Agent graph section."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    profile = await _get_agent_composer().compose(entity_id, tenant.tenant_id)
    return APIResponse(data={"agent_id": entity_id, **profile["graph"]}).to_dict()# ── Identity Cluster Endpoints ───────────────────────────────────────

@router.get("/{user_id}/cluster")
async def get_profile_cluster(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Primary identity cluster this entity belongs to."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.cluster(user_id, tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/clusters")
async def get_profile_clusters(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """All identity clusters this entity is a member of."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.clusters(user_id, tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/identity-confidence")
async def get_identity_confidence(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Identity confidence score breakdown for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.identity_confidence(user_id, tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/merge-history")
async def get_merge_history(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Identity merge history for this entity. Returns empty envelope when unavailable."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.identity_graph_repository import IdentityGraphRepository
        repo = IdentityGraphRepository()
        items = await repo.get_merge_history(user_id, tenant_id=tenant.tenant_id, limit=limit)
    except Exception:
        items = []
    return APIResponse(data={
        "entity_id": user_id,
        "items": items,
        "count": len(items),
        "source_status": "available" if items else "missing",
    }).to_dict()


@router.get("/{user_id}/split-history")
async def get_split_history(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Identity split history for this entity. Returns empty envelope when unavailable."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.identity_graph_repository import IdentityGraphRepository
        repo = IdentityGraphRepository()
        items = await repo.get_split_history(user_id, tenant_id=tenant.tenant_id, limit=limit)
    except Exception:
        items = []
    return APIResponse(data={
        "entity_id": user_id,
        "items": items,
        "count": len(items),
        "source_status": "available" if items else "missing",
    }).to_dict()


# ── Attribution Endpoint ────────────────────────────────────────────

@router.get("/{user_id}/attribution")
async def get_profile_attribution(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    window: str = Query(default="30d"),
):
    """Multi-touch attribution touchpoints, first/last touch, and conversion chain."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    data = await agg.attribution(user_id, tenant.tenant_id, window=window)
    return APIResponse(data=data).to_dict()


# ── Consent & Activation Endpoints ─────────────────────────────────

@router.get("/{user_id}/consent")
async def get_profile_consent(
    user_id: str,
    request: Request,
):
    """Consent state, activation eligibility, allowed/restricted use cases, DSR state."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import ConsentRepository
        repo = ConsentRepository()
        record = await repo.get_consent(tenant.tenant_id, user_id)
    except Exception:
        record = None
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        return APIResponse(data={
            "entity_id": user_id,
            "consent_status": "unknown",
            "activation_eligibility": "observe_only",
            "allowed_use_cases": [],
            "restricted_use_cases": [],
            "blocked_use_cases": [],
            "consent_sources": [],
            "last_consent_update": None,
            "retention_status": "unknown",
            "redaction_state": "none",
            "dsr_state": "none",
            "source_status": "missing",
        }).to_dict()
    return APIResponse(data={
        "entity_id": user_id,
        **{k: v for k, v in record.items() if k != "tenant_id"},
        "source_status": "available",
    }).to_dict()


@router.get("/{user_id}/activation-eligibility")
async def get_activation_eligibility(
    user_id: str,
    request: Request,
):
    """Whether this entity may be activated for targeting, observation, or is blocked."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import ConsentRepository
        repo = ConsentRepository()
        record = await repo.get_consent(tenant.tenant_id, user_id)
    except Exception:
        record = None
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        return APIResponse(data={
            "entity_id": user_id,
            "activation_eligibility": "observe_only",
            "allowed_use_cases": [],
            "restricted_use_cases": [],
            "blocked_use_cases": [],
            "consent_status": "unknown",
            "source_status": "missing",
        }).to_dict()
    return APIResponse(data={
        "entity_id": user_id,
        "activation_eligibility": record.get("activation_eligibility", "observe_only"),
        "allowed_use_cases": record.get("allowed_use_cases", []),
        "restricted_use_cases": record.get("restricted_use_cases", []),
        "blocked_use_cases": record.get("blocked_use_cases", []),
        "consent_status": record.get("consent_status", "unknown"),
        "source_status": "available",
    }).to_dict()


# ── Profile Quality & Freshness Endpoints ──────────────────────────

@router.get("/{user_id}/quality")
async def get_profile_quality(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Profile quality scorecard: completeness, freshness, confidence, readiness status."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.quality(user_id, tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/data-freshness")
async def get_data_freshness(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Per-dimension data freshness: sources, last update, stale status, warnings."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    data = await agg.data_freshness(user_id, tenant.tenant_id)
    return APIResponse(data=data).to_dict()


# ── Economic Sub-Routes ────────────────────────────────────────────

@router.get("/{user_id}/economic")
async def get_profile_economic(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Unified economic profile: Web2 + Web3 + agentic activity summary."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    financials = await intel.pnl(user_id, tenant.tenant_id, window=window)
    web3 = await intel.asset_composition(user_id, tenant.tenant_id, window=window)
    return APIResponse(data={
        "entity_id": user_id,
        "window": window,
        "financials": financials,
        "web3": web3,
        "computed_at": financials.get("computed_at"),
    }).to_dict()


@router.get("/{user_id}/economic/web2")
async def get_economic_web2(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """TradFi portfolio and Web2 financial signals (requires 'credit' consent)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    return APIResponse(data=await intel.web2(user_id, tenant.tenant_id, window=window)).to_dict()


@router.get("/{user_id}/economic/web3")
async def get_economic_web3(
    user_id: str,
    request: Request,
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """On-chain asset composition, PNL, and trading profile."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    asset_comp = await intel.asset_composition(user_id, tenant.tenant_id, window=window)
    pnl = await intel.pnl(user_id, tenant.tenant_id, window=window)
    trading = await intel.trading_profile(user_id, tenant.tenant_id, window=window)
    return APIResponse(data={
        "entity_id": user_id,
        "window": window,
        "asset_composition": asset_comp,
        "pnl": pnl,
        "trading_profile": trading,
    }).to_dict()


@router.get("/{user_id}/economic/agentic")
async def get_economic_agentic(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Agentic economic identity: delegations, agent spend, settlement summary."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    delegations = await agg.delegations(user_id, tenant.tenant_id)
    agents = await agg.agents(user_id, tenant.tenant_id)
    return APIResponse(data={
        "entity_id": user_id,
        "delegations": delegations,
        "agents": agents,
    }).to_dict()


@router.get("/{user_id}/economic/campaigns")
async def get_economic_campaigns(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    window: str = Query(default="30d"),
    intel: IntelligenceAggregator = Depends(_get_intel_agg),
):
    """Campaign-level economic attribution: ROAS, CPA, LTV per campaign."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    _validate_window(window)
    campaigns = await agg.campaigns(user_id, tenant.tenant_id)
    economics = await intel.journey_economics(user_id, tenant.tenant_id, window=window)
    return APIResponse(data={
        "entity_id": user_id,
        "window": window,
        "campaigns": campaigns,
        "journey_economics": economics,
    }).to_dict()


@router.get("/{user_id}/economic/warnings")
async def get_economic_warnings(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Economic risk warnings: anomalies, source gaps, stale data flags."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    quality = await agg.quality(user_id, tenant.tenant_id)
    freshness = await agg.data_freshness(user_id, tenant.tenant_id)
    warnings = []
    for dim in quality.get("missing_dimensions", []):
        warnings.append({"type": "missing_dimension", "dimension": dim, "severity": "warning"})
    for dim in quality.get("stale_dimensions", []):
        warnings.append({"type": "stale_dimension", "dimension": dim, "severity": "warning"})
    if quality.get("contradiction_count", 0) > 0:
        warnings.append({"type": "data_contradiction", "count": quality["contradiction_count"], "severity": "error"})
    return APIResponse(data={
        "entity_id": user_id,
        "warnings": warnings,
        "warning_count": len(warnings),
        "quality_summary": quality,
        "freshness_summary": freshness,
    }).to_dict()


# ── Agent Executions ───────────────────────────────────────────────

@router.get("/{user_id}/agent-executions")
async def get_agent_executions(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
):
    """Agent execution history for this entity (as owner or participant)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AgentConfigRepository, AgentExecutionRepository
        config_repo = AgentConfigRepository()
        configs = await config_repo.find_many(
            {"tenant_id": tenant.tenant_id, "owner_entity_id": user_id}, limit=200
        )
        agent_ids = [
            c.get("agent_id") or c.get("id")
            for c in configs
            if c.get("tenant_id") == tenant.tenant_id and (c.get("agent_id") or c.get("id"))
        ]
        exec_repo = AgentExecutionRepository()
        items = []
        for agent_id in agent_ids:
            filters: dict = {"tenant_id": tenant.tenant_id, "agent_id": agent_id}
            if status:
                filters["status"] = status
            rows = await exec_repo.find_many(filters, limit=limit)
            items.extend(r for r in rows if r.get("tenant_id") == tenant.tenant_id)
        items = items[:limit]
    except Exception:
        items = []
    return APIResponse(data={
        "entity_id": user_id,
        "items": items,
        "count": len(items),
        "source_status": "available" if items else "missing",
    }).to_dict()


# ── Actions & Events ───────────────────────────────────────────────

@router.get("/{user_id}/actions")
async def get_profile_actions(
    user_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Entity-level actions (decisions executed, operations initiated)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from services.intelligence.repositories import DecisionRepository, RecommendationRepository
        rec_repo = RecommendationRepository()
        recs = await rec_repo.find_many(
            {"tenant_id": tenant.tenant_id, "entity_id": user_id}, limit=limit
        )
        recs = [r for r in recs if r.get("tenant_id") == tenant.tenant_id]
        rec_ids = [r.get("recommendation_id") or r.get("id") for r in recs if r.get("recommendation_id") or r.get("id")]
        dec_repo = DecisionRepository()
        items = []
        for rec_id in rec_ids:
            rows = await dec_repo.find_many(
                {"tenant_id": tenant.tenant_id, "recommendation_id": rec_id}, limit=limit
            )
            items.extend(r for r in rows if r.get("tenant_id") == tenant.tenant_id)
        items = items[:limit]
    except Exception:
        items = []
    return APIResponse(data={
        "entity_id": user_id,
        "items": items,
        "count": len(items),
    }).to_dict()


@router.get("/{user_id}/events")
async def get_profile_events(
    user_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    event_type: str | None = Query(default=None),
    composer: ProfileComposer = Depends(_get_composer),
):
    """Raw event stream for this entity (alias to timeline with event_type filter)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    events = await composer.get_timeline(user_id, tenant.tenant_id, limit=limit, event_type=event_type)
    return APIResponse(data={
        "entity_id": user_id,
        "events": events,
        "count": len(events),
    }).to_dict()
