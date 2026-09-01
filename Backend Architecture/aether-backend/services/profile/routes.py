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

import uuid
from datetime import datetime, timezone
from typing import Optional

from dependencies.providers import get_cache, get_graph
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
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
from shared.rights_authority.contracts import ActorRef
from shared.rights_authority.pep import evaluate_rights
from shared.privacy.consent_enforcement import ConsentDeniedError, require_consent

from services.profile.aggregator import Profile360Aggregator
from services.profile.composer import ProfileComposer
from services.profile.intelligence import IntelligenceAggregator
from services.profile.resolver import ProfileResolver
# Capability-family metering seam (§7): durable meter + evidence for
# reconciliation at the profile-family choke point.
from services.metering_evidence.families import meter_family_usage  # noqa: E402

logger = get_logger("aether.service.profile")


class _RightsProfileRoute(APIRoute):
    """Apply one rights read gate to every Profile360 sub-resource route."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            from shared.rights_authority.pep import rights_mode

            if rights_mode() == "off":
                return await original(request)
            tenant = getattr(request.state, "tenant", None)
            if tenant is None:
                return await original(request)
            entity_id = (
                request.path_params.get("user_id")
                or request.path_params.get("entity_id")
                or request.path_params.get("entity_type")
                or request.query_params.get("user_id")
                or request.query_params.get("entity_id")
            )
            entity_id = str(entity_id or "profile")
            envelope_refs = request.query_params.getlist("rights_envelope_ref")
            policy_set_ref = request.query_params.get("rights_policy_set_ref")
            result = await evaluate_rights(
                action="read",
                tenant_id=tenant.tenant_id,
                actor=ActorRef(
                    kind="tenant_user",
                    id=getattr(tenant, "user_id", None) or tenant.tenant_id,
                    tenant_id=tenant.tenant_id,
                ),
                purpose="profile360_read",
                artifacts=[{
                    "kind": "profile360",
                    "id": entity_id,
                    "tenant_id": tenant.tenant_id,
                }],
                envelope_refs=envelope_refs,
                policy_set_ref=policy_set_ref,
                metadata={"surface": request.url.path},
            )
            request.state.profile_rights_result = result
            if not result.proceed:
                return JSONResponse(status_code=403, content={
                    "code": "rights_profile_read_blocked",
                    "detail": "Profile360 read blocked by the rights authority",
                    "rights": {
                        "decision_id": result.decision.decision_id if result.decision else None,
                        "outcome": result.decision.outcome if result.decision else "unavailable",
                        "reasons": list(result.reason_codes),
                    },
                })
            return await original(request)

        return handler


router = APIRouter(
    prefix="/v1/profile", tags=["Profile 360"], route_class=_RightsProfileRoute,
)
profile360_router = APIRouter(
    prefix="/v1/profile360", tags=["Profile360 Kyber"], route_class=_RightsProfileRoute,
)

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


# ── Read-completeness metadata ───────────────────────────────────────────
# Capped list reads return a bare list, so a truncated result is otherwise
# indistinguishable from "this is everything" (false certainty). These
# build a small additive `meta` block for the existing APIResponse
# envelope so callers can tell. Keep in sync with the lake/intelligence
# copies. Endpoints that delegate their fetch entirely to Profile360Aggregator
# / IntelligenceAggregator / ProfileComposer / AgentProfile360Composer (all
# defined outside this file) are intentionally not covered here — the
# capped fetch itself is not visible/adjustable from this router.

def _probe_completeness(limit: int, fetched: int) -> dict:
    """Exact completeness meta from an over-fetch relative to `limit`.

    Call with `fetched` = the row count returned when the underlying query
    already retrieved (or was asked to retrieve) more than `limit` rows —
    typically a `limit + 1` probe. `has_more` is a fact, not a guess: the
    fetch would only return more than `limit` rows if more than `limit`
    rows actually exist.
    """
    has_more = fetched > limit
    return {"limit": limit, "returned": min(fetched, limit), "truncated": has_more, "has_more": has_more}


def _heuristic_completeness(limit: int, returned: int) -> dict:
    """Conservative completeness meta when a limit+1 probe isn't feasible
    (e.g. the underlying repository call enforces a fixed internal cap with
    no adjustable limit parameter).

    We cannot distinguish "exactly `limit` rows exist" from "more rows
    exist beyond `limit`", so we conservatively assume truncation whenever
    the result exactly fills the limit. This can over-report truncation but
    never under-report it — never imply completeness when truncation is
    possible.
    """
    truncated = limit > 0 and returned == limit
    return {"limit": limit, "returned": returned, "truncated": truncated, "has_more": truncated}


async def _profile_rights(
    request: Request,
    tenant_id: str,
    entity_id: str,
    envelope_refs: Optional[list[str]] = None,
    policy_set_ref: Optional[str] = None,
):
    """Authorize Profile360 before composing graph, lake, or model sections."""
    existing = getattr(getattr(request, "state", None), "profile_rights_result", None)
    if existing is not None:
        decision = existing
    else:
        decision = await evaluate_rights(
            action="read",
            tenant_id=tenant_id,
            actor=ActorRef(
                kind="tenant_user",
                id=getattr(request.state.tenant, "user_id", None) or tenant_id,
                tenant_id=tenant_id,
            ),
            purpose="profile360_read",
            artifacts=[{"kind": "profile360", "id": entity_id, "tenant_id": tenant_id}],
            envelope_refs=envelope_refs or (),
            policy_set_ref=policy_set_ref,
            metadata={"surface": "profile360"},
        )
    payload = {
        "mode": decision.mode,
        "proceed": decision.proceed,
        "decision_id": decision.decision.decision_id if decision.decision else None,
        "outcome": decision.decision.outcome if decision.decision else None,
        "reasons": list(decision.reason_codes),
        "envelope_refs": decision.decision.envelope_refs if decision.decision else list(envelope_refs or []),
        "policy_set_ref": decision.decision.policy_set_ref if decision.decision else policy_set_ref,
    }
    return decision, payload


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
    rights_envelope_ref: Optional[list[str]] = Query(default=None),
    rights_policy_set_ref: Optional[str] = Query(default=None),
):
    """
    Full holistic profile view — everything Aether knows about this entity.

    Composes: identity, identifiers, consent, timeline, graph, intelligence, lake data.
    All data includes provenance. Respects tenant scoping.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    rights, rights_payload = await _profile_rights(
        request, tenant.tenant_id, user_id, rights_envelope_ref, rights_policy_set_ref,
    )
    if not rights.proceed:
        return APIResponse(data={
            "user_id": user_id,
            "state": "suppressed",
            "rights": rights_payload,
            "sections": {},
        }).to_dict()

    result = await composer.get_full_profile(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        include_timeline=include_timeline,
        include_graph=include_graph,
        include_intelligence=include_intelligence,
        include_lake=include_lake,
        timeline_limit=timeline_limit,
        rights_decision_id=rights.decision.decision_id if rights.decision else None,
    )

    metrics.increment("profile_360_full_view")
    return APIResponse(data={**result, "rights": rights_payload}).to_dict()


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

    provenance = await composer.get_provenance(
        user_id, tenant_id=request.state.tenant.tenant_id
    )
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
    rights_envelope_ref: Optional[list[str]] = Query(default=None),
    rights_policy_set_ref: Optional[str] = Query(default=None),
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
        rights_decision_id=(
            request.state.profile_rights_result.decision.decision_id
            if getattr(request.state, "profile_rights_result", None)
            and request.state.profile_rights_result.decision
            else None
        ),
    )

    if not resolved:
        raise NotFoundError("No profile found for the given identifier")

    # Family seam: durable meter + evidence (advisory — no entitlement gate).
    await meter_family_usage(
        "profile360", tenant.tenant_id, event_id=str(uuid.uuid4()),
        enforce=False, raise_on_metering_error=False,
    )

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
    rights_envelope_ref: Optional[list[str]] = Query(default=None),
    rights_policy_set_ref: Optional[str] = Query(default=None),
):
    """Normalized internal Profile360 payload for Kyber.

    Kyber is an internal control surface and receives the full tenant-scoped
    Profile360 view plus alignment audit metadata. End-user profile surfaces
    should call a separate redacted endpoint rather than this internal route.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    rights, rights_payload = await _profile_rights(
        request, tenant.tenant_id, entity_id, rights_envelope_ref, rights_policy_set_ref,
    )
    if not rights.proceed:
        return APIResponse(data={
            "entity_id": entity_id,
            "entity_type": entity_type,
            "state": "suppressed",
            "rights": rights_payload,
        }).to_dict()
    result = await composer.get_profile360_surface(
        entity_type=entity_type,
        entity_id=entity_id,
        tenant_id=tenant.tenant_id,
        include=_parse_include(include),
        timeline_limit=timeline_limit,
        graph_limit=graph_limit,
        rights_decision_id=rights.decision.decision_id if rights.decision else None,
    )
    metrics.increment("profile360_kyber_surface_view")
    return APIResponse(data={**result, "rights": rights_payload}).to_dict()


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
    # AgentConfigRepository.list_for_owner() enforces a fixed internal cap
    # (200) with no adjustable limit parameter and no tenant scoping of its
    # own (tenant filtering happens below), so an exact limit+1 probe isn't
    # feasible here. Base truncation on whether the *pre-filter* fetch hit
    # the cap, not on the post-filter count: if the raw fetch came back
    # under 200, every matching row (any tenant) was seen, so this tenant's
    # slice is definitely complete even though it may be far fewer than 200
    # rows — comparing the post-filter count to 200 would falsely call that
    # complete-and-small result "truncated is unknown/false" while also
    # missing real truncation when other tenants' rows fill most of the cap.
    owned_agents_cap = 200
    raw = await _user_agent_repo.list_for_owner(user_id)
    rows = [r for r in raw if r.get("tenant_id") == request.state.tenant.tenant_id]
    truncated = len(raw) == owned_agents_cap
    return APIResponse(
        data={"user_id": user_id, "agents": rows, "count": len(rows)},
        meta={"limit": owned_agents_cap, "returned": len(rows), "truncated": truncated, "has_more": truncated},
    ).to_dict()


@router.get("/{entity_id}/external-deployments")
async def get_external_deployments(entity_id: str, request: Request):
    """External agent deployments operated by this (agent) entity.

    Sourced from the External Agent Telemetry deployment registry; hidden
    (not-found) unless the profile360 rollout flag is enabled.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from config.settings import settings
    if not settings.external_agent_telemetry.profile360_enabled:
        raise NotFoundError("External deployment activity")
    from services.profile.deployment_activity import get_external_deployment_activity
    data = await get_external_deployment_activity(tenant.tenant_id, entity_id)
    return APIResponse(data=data).to_dict()


@router.get("/{entity_id}/payment-rails")
async def get_payment_rails_summary(entity_id: str, request: Request):
    """Observed funding-session rollup for this entity (user/agent/org).

    Counts per provider/rail/status/reconciliation state and per-currency
    native totals — mixed currencies are never merged into one scalar.
    Hidden (not-found) unless payment rails are enabled.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from config.settings import settings
    if not settings.payment_rails.enabled:
        raise NotFoundError("Payment rail activity")
    from services.integrations.providers.payment_rails.profile_summary import (
        get_payment_rails_profile_summary,
    )
    data = await get_payment_rails_profile_summary(tenant.tenant_id, entity_id)
    return APIResponse(data=data).to_dict()


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
    # DelegationRepository has no adjustable-limit read for either side —
    # both enforce a fixed internal cap (200) — so this is heuristic-only,
    # reported per list since granted/received are independently capped.
    delegations_cap = 200
    granted: list = []
    received: list = []
    granted_truncated = False
    received_truncated = False
    if role in ("grantor", "both"):
        granted = await repo.find_many(
            filters={"grantor_entity_id": user_id, "tenant_id": tenant.tenant_id}, limit=delegations_cap,
        )
        granted_truncated = len(granted) == delegations_cap
    if role in ("grantee", "both"):
        if active:
            # active_for() further filters to active-only after its own
            # internal 200-row fetch, so the post-filter count is a weaker
            # signal than usual — still the best available without touching
            # DelegationRepository (out of scope for this change).
            received = await repo.active_for(user_id, tenant.tenant_id)
        else:
            received = await repo.find_many(filters={"grantee_entity_id": user_id, "tenant_id": tenant.tenant_id}, limit=delegations_cap)
        received_truncated = len(received) == delegations_cap
    return APIResponse(
        data={
            "user_id": user_id,
            "granted": granted,
            "received": received,
        },
        meta={
            "granted": {"limit": delegations_cap, "returned": len(granted), "truncated": granted_truncated, "has_more": granted_truncated},
            "received": {"limit": delegations_cap, "returned": len(received), "truncated": received_truncated, "has_more": received_truncated},
        },
    ).to_dict()


@router.get("/{user_id}/flows")
async def get_flows(
    user_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=500),
):
    """Asset transfers in or out of this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    # list_for_entity() applies `limit` as its own final slice (after
    # merging+deduping from/to matches across ALL tenants — it has no
    # tenant scoping of its own), so probing with limit+1 tells us whether
    # the *global* window was full. Tenant filtering happens below, so
    # has_more must account for both: our own tenant-scoped rows already
    # exceeding `limit` within the probe, OR the global probe window
    # itself being full (meaning rows beyond it — possibly ours — were
    # never examined at all). Either way, never claim completeness.
    probe = await _transfer_repo.list_for_entity(user_id, limit=limit + 1)
    probe_window_full = len(probe) > limit
    fetched = [r for r in probe if r.get("tenant_id") == tenant.tenant_id]
    rows = fetched[:limit]
    has_more = len(fetched) > limit or probe_window_full
    return APIResponse(
        data={
            "user_id": user_id,
            "transfers": rows,
            "count": len(rows),
        },
        meta={"limit": limit, "returned": len(rows), "truncated": has_more, "has_more": has_more},
    ).to_dict()


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


@router.get("/{user_id}/semantic")
async def get_semantic(user_id: str, request: Request):
    """Profile360 semantic dimension — the entity's durable weighted semantic state.

    Surfaces active topics, stance/intent distribution, summary, confidence,
    freshness, model/taxonomy mix and reducer provenance from the semantic
    Gold-tier reducer. Returns an empty-but-shaped response (not 404) when no
    semantic observations exist yet.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    from services.semantic_intelligence.service import get_semantic_service

    state = await get_semantic_service().entity_state(tenant.tenant_id, user_id)
    payload = state.model_dump(mode="json")
    computed = state.semantic_summary != "insufficient_data"
    return APIResponse(
        data={
            "user_id": user_id,
            "semantic": payload,
            "computed": computed,
            "provenance": {"sources": ["semantic_gold_state"]},
        }
    ).to_dict()


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


_credit_consent_repo: Optional[ConsentRepository] = None


def _get_consent_repo() -> ConsentRepository:
    global _credit_consent_repo
    if _credit_consent_repo is None:
        _credit_consent_repo = ConsentRepository()
    return _credit_consent_repo


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


@router.get("/{user_id}/unified-journey")
async def get_unified_journey(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
    limit: int = Query(50, ge=1, le=200),
    family: Optional[str] = Query(None, description="Filter by activity family: web2,web3,campaign,commerce,agent,x402,outcome"),
    after: Optional[str] = Query(None, description="ISO8601 timestamp — only steps after this time"),
    before: Optional[str] = Query(None, description="ISO8601 timestamp — only steps before this time"),
):
    """Unified canonical journey — interleaved Web2/Web3/campaign/agent/x402 steps.

    Sources from journey_steps produced by JourneyCompiler v2.0. Returns a
    not_provisioned state when no canonical journey has been compiled yet.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    return APIResponse(
        data=await agg.unified_journey(
            user_id, tenant.tenant_id,
            steps_limit=limit,
            family=family,
            after=after,
            before=before,
        )
    ).to_dict()


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


# ── Card-linked payment rail activity (Economic Activity → Payment Rails) ──

def _card_linked_filters(request: Request) -> dict:
    """Extract card-linked filters from query params (shared filter set)."""
    from services.card_linked_payments.profile_summary import FILTERABLE_FIELDS
    params = request.query_params
    filters = {name: params.get(name) for name in FILTERABLE_FIELDS}
    for extra in ("volume_min", "volume_max", "since", "until"):
        filters[extra] = params.get(extra)
    return filters


@router.get("/{user_id}/card-linked-activity")
async def get_card_linked_activity(user_id: str, request: Request):
    """Card-linked activity for an entity — story, flows, filters, provenance.

    Flag-gated (404 when Card-Linked Payment Rails or its Profile360
    surface is disabled). Bases stay separated: top-up is never spend.
    """
    from config.settings import settings as _settings
    flags = _settings.card_linked_payment_rails
    if not (flags.enabled and flags.profile360_enabled):
        raise NotFoundError("Card-linked payment rails Profile360 surface is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.card_linked_payments.profile_summary import get_card_linked_profile_summary
    data = await get_card_linked_profile_summary(
        tenant.tenant_id, user_id, _card_linked_filters(request),
    )
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/economic/card-linked")
async def get_economic_card_linked(user_id: str, request: Request):
    """Economic-activity alias for the card-linked summary."""
    return await get_card_linked_activity(user_id, request)


@router.get("/{user_id}/drill/card-linked/{object_id}")
async def drill_card_linked(user_id: str, object_id: str, request: Request):
    """Evidence/provenance drill into one card-linked flow."""
    from config.settings import settings as _settings
    flags = _settings.card_linked_payment_rails
    if not (flags.enabled and flags.profile360_enabled):
        raise NotFoundError("Card-linked payment rails Profile360 surface is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.card_linked_payments.profile_summary import get_card_linked_drilldown
    data = await get_card_linked_drilldown(tenant.tenant_id, user_id, object_id)
    if data is None:
        raise NotFoundError(f"card-linked/{object_id} not found in tenant scope")
    return APIResponse(data=data).to_dict()


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

    # GoldRepository.get_metrics() enforces a fixed internal cap (200) with
    # no adjustable limit parameter, so an exact limit+1 probe isn't
    # feasible here — heuristic completeness only.
    gold_metrics_cap = 200
    records = await repo.get_metrics(user_id, tenant_id=request.state.tenant.tenant_id)
    return APIResponse(
        data={
            "user_id": user_id,
            "domain": domain,
            "records": records,
            "count": len(records),
        },
        meta=_heuristic_completeness(gold_metrics_cap, len(records)),
    ).to_dict()


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
    consent_repo: ConsentRepository = Depends(_get_consent_repo),
):
    """TradFi portfolio, bank accounts, credit signals, and income estimates (requires 'credit' consent)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        await require_consent(consent_repo, tenant.tenant_id, user_id, "credit")
    except ConsentDeniedError:
        raise HTTPException(status_code=403, detail="Credit consent required for this resource")
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
    fetched = await repo.list_for_tenant(tenant.tenant_id, limit=limit + 1, entity_id=user_id)
    items = fetched[:limit]
    return APIResponse(
        data={"entity_id": user_id, "items": items, "count": len(items)},
        meta=_probe_completeness(limit, len(fetched)),
    ).to_dict()


@router.get("/{user_id}/outcomes")
async def get_profile_outcomes(user_id: str, request: Request, limit: int = Query(default=20, ge=1, le=100)):
    """Outcome history linked to this Profile360 entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.intelligence.repositories import OutcomeRepository
    repo = OutcomeRepository()
    fetched = await repo.list_for_tenant(tenant.tenant_id, limit=limit + 1, entity_id=user_id)
    items = fetched[:limit]
    return APIResponse(
        data={"entity_id": user_id, "items": items, "count": len(items)},
        meta=_probe_completeness(limit, len(fetched)),
    ).to_dict()


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
    decisions: list[dict] = []
    for rec_id in rec_ids:
        batch = await DecisionRepository().find_many({"tenant_id": tenant.tenant_id, "recommendation_id": rec_id}, limit=limit)
        decisions.extend(batch)
    decision_ids = {d.get("decision_id") for d in decisions}
    actions: list[dict] = []
    for dec_id in decision_ids:
        batch = await ActionFeedbackRepository().find_many({"tenant_id": tenant.tenant_id, "decision_id": dec_id}, limit=limit)
        actions.extend(batch)
    outcomes = await OutcomeRepository().list_for_tenant(tenant.tenant_id, limit=limit, entity_id=user_id)
    feedback: list[dict] = []
    for rec_id in rec_ids:
        batch = await RecommendationFeedbackRepository().find_many({"tenant_id": tenant.tenant_id, "recommendation_id": rec_id}, limit=limit)
        feedback.extend(batch)
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
    """Identity merge history from the event-sourced ``identity_merge_events``
    store — every merge this entity was a party to (survivor-redirected).

    Reads the same append-only events identity resolution writes, not graph
    ``RESOLVED_AS`` edges (identity writes ``SAME_AS`` edges + event rows, so
    the old graph read was always empty).
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.identity.redirects import resolve_entity_redirect
    from services.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    resolved_id, redirected = await resolve_entity_redirect(repo, tenant.tenant_id, user_id)
    # get_merge_history() applies `limit` as its own final slice (after
    # deduping from/into matches), so probing with limit+1 is exact.
    fetched = await repo.get_merge_history(tenant.tenant_id, resolved_id, limit=limit + 1)
    events = fetched[:limit]
    items = [
        {
            "merge_event_id": e.get("id"),
            "from_entity_id": e.get("from_entity_id"),
            "into_entity_id": e.get("into_entity_id"),
            "resulting_entity_id": e.get("resulting_entity_id"),
            "confidence": e.get("confidence"),
            "confidence_tier": e.get("confidence_tier"),
            "reason_codes": e.get("reason_codes") or [],
            "actor_type": e.get("actor_type"),
            "merged_at": e.get("created_at"),
        }
        for e in events
    ]
    return APIResponse(
        data={
            "entity_id": user_id,
            "resolved_entity_id": resolved_id,
            "redirected": redirected,
            "items": items,
            "count": len(items),
            "source_status": await _event_source_status(items),
        },
        meta=_probe_completeness(limit, len(fetched)),
    ).to_dict()


@router.get("/{user_id}/split-history")
async def get_split_history(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Identity split history from the event-sourced ``identity_split_events``
    store — every split originating from this entity (survivor-redirected)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.identity.redirects import resolve_entity_redirect
    from services.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    resolved_id, redirected = await resolve_entity_redirect(repo, tenant.tenant_id, user_id)
    # get_split_history() passes `limit` straight through to a single
    # tenant+entity-scoped find_many(), so probing with limit+1 is exact.
    fetched = await repo.get_split_history(tenant.tenant_id, resolved_id, limit=limit + 1)
    events = fetched[:limit]
    items = [
        {
            "split_event_id": e.get("id"),
            "original_entity_id": e.get("original_entity_id"),
            "resulting_entity_ids": e.get("resulting_entity_ids") or [],
            "reason": e.get("reason"),
            "actor_type": e.get("actor_type"),
            "source_merge_event_id": e.get("source_merge_event_id"),
            "split_at": e.get("created_at"),
        }
        for e in events
    ]
    return APIResponse(
        data={
            "entity_id": user_id,
            "resolved_entity_id": resolved_id,
            "redirected": redirected,
            "items": items,
            "count": len(items),
            "source_status": await _event_source_status(items),
        },
        meta=_probe_completeness(limit, len(fetched)),
    ).to_dict()


async def _event_source_status(items: list) -> str:
    """Classify why a result set is what it is, without guessing.

    Three outcomes that must stay distinct, because collapsing them is how a
    surface reports confidence it has not earned:

    - ``missing``   — the store could not be consulted, so nothing is known.
    - ``empty``     — the store answered, and the entity genuinely has no events.
    - ``available`` — the store answered with events.

    The identity event stores return ``[]`` for both of the first two cases, so
    reachability is established via the pool rather than inferred from an empty
    list. Reporting ``empty`` for an unreachable store asserts that the entity
    has no merge or split history — a claim nobody checked.
    """
    if items:
        return "available"
    try:
        from repositories.repos import get_pool
        reachable = await get_pool() is not None
    except Exception:
        reachable = False
    return "empty" if reachable else "missing"


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


@router.get("/{user_id}/data-status")
async def get_data_status(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Canonical per-dimension data-status (dimension-state contract).

    Each dimension reports a `DimensionEnvelope` — state (ready / empty / stale /
    insufficient_data / degraded / error), reason code, freshness, and count —
    plus a worst-wins `overall_state`, so a surface can say why a slice is empty
    or degraded instead of rendering a blank that reads as no activity.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.reconciliation.dimension_status import compute_data_status

    data = await compute_data_status(agg, user_id, tenant.tenant_id)
    return APIResponse(data=data).to_dict()


@router.get("/{user_id}/reconciliation")
async def get_profile_reconciliation(
    user_id: str,
    request: Request,
    agg: Profile360Aggregator = Depends(_get_aggregator),
):
    """Per-dimension expectation-vs-actual reconciliation.

    For each registered dimension, reports the declared expectation (minimum
    volume, freshness SLA) against the actual reading and whether it is met, so
    an operator can see exactly which dimensions fall short and why.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.reconciliation.dimension_status import compute_reconciliation

    data = await compute_reconciliation(agg, user_id, tenant.tenant_id)
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
    consent_repo: ConsentRepository = Depends(_get_consent_repo),
):
    """TradFi portfolio and Web2 financial signals (requires 'credit' consent)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        await require_consent(consent_repo, tenant.tenant_id, user_id, "credit")
    except ConsentDeniedError:
        raise HTTPException(status_code=403, detail="Credit consent required for this resource")
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
    # Fan-out across (possibly several) agent_ids, each independently
    # capped at `limit`, concatenated and re-sliced to `limit` — an exact
    # limit+1 probe would need to bump every fan-out fetch, so this is
    # heuristic. Note the heuristic still catches the common overshoot
    # case for free: whenever concatenation across >1 agent_ids exceeds
    # `limit`, the post-slice length below is exactly `limit`, which is
    # precisely the condition the heuristic treats as "truncated".
    try:
        from repositories.repos import AgentConfigRepository, AgentExecutionRepository
        config_repo = AgentConfigRepository()
        configs = await config_repo.find_many(
            {"tenant_id": tenant.tenant_id, "owner_entity_id": user_id}, limit=200
        )
        agent_ids = list({
            *(c.get("agent_id") or c.get("id")
              for c in configs
              if c.get("tenant_id") == tenant.tenant_id and (c.get("agent_id") or c.get("id"))),
            user_id,  # include the profiled entity itself in case it is an agent
        })
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
    return APIResponse(
        data={
            "entity_id": user_id,
            "items": items,
            "count": len(items),
            "source_status": await _event_source_status(items),
        },
        meta=_heuristic_completeness(limit, len(items)),
    ).to_dict()


# ── Actions & Events ───────────────────────────────────────────────

@router.get("/{user_id}/actions")
async def get_profile_actions(
    user_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Entity-level actions (decisions executed, operations initiated).

    Response uses the sibling envelope ({entity_id, items, count,
    source_status}) — this was the only sibling without one, so a failed
    recommendation/decision read was indistinguishable from an entity that
    genuinely executed no actions.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    # Two truncation layers: `recs` itself is capped at `limit` (some
    # recommendations may never be looked at), and the concatenated
    # decisions list is separately re-sliced to `limit`. An exact limit+1
    # probe would need to bump both fan-out layers, so this is heuristic —
    # but it checks both layers (using data already fetched) rather than
    # only the final slice, so a recs-side cap is not silently missed.
    truncated = False
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
        truncated = len(recs) == limit or len(items) == limit
        degraded = False
    except Exception as exc:
        logger.warning("profile actions unavailable: %s", exc)
        items = []
        degraded = True
    return APIResponse(
        data={
            "entity_id": user_id,
            "items": items,
            "count": len(items),
            "source_status": (
                "missing" if degraded else ("available" if items else "empty")
            ),
        },
        meta={"limit": limit, "returned": len(items), "truncated": truncated, "has_more": truncated},
    ).to_dict()


@router.get("/{user_id}/events")
async def get_profile_events(
    user_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    event_type: str | None = Query(default=None),
    composer: ProfileComposer = Depends(_get_composer),
):
    """Raw event stream for this entity (alias to timeline with event_type filter).

    Response uses the sibling envelope ({entity_id, items, count, source_status})
    so a failed read is distinguishable from an entity with no events. The one
    frontend consumer of this route reads it with an unpinned schema, so the
    envelope change breaks no pinned contract; /timeline retains its original
    shape for the consumers that pin `events`.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        items = await composer.get_timeline(
            user_id, tenant.tenant_id, limit=limit, event_type=event_type
        )
        degraded = False
    except Exception as exc:
        logger.warning("profile events unavailable: %s", exc)
        items = []
        degraded = True
    return APIResponse(data={
        "entity_id": user_id,
        "items": items,
        "count": len(items),
        "source_status": (
            "missing" if degraded else ("available" if items else "empty")
        ),
    }).to_dict()


# ── Silver-backed Profile360 sub-resources ─────────────────────────────────────
# Each endpoint reads from the corresponding silver_*_facts table.
# Requires: consent enforcement for the relevant purpose.
# Returns: {entity_id, items, count, source_status}

def _silver_response(
    entity_id: str,
    items: list,
    source: str = "silver",
    *,
    degraded: bool = False,
    limit: int,
    fetched: int,
) -> dict:
    """Envelope for the Silver-backed sub-resources.

    ``degraded=True`` means the Silver store could not be consulted — the
    caller's read raised — so the response reports ``missing`` rather than
    asserting the entity genuinely has no facts (``empty``). Collapsing a
    failed read into ``empty`` is how a store outage reads as confirmed
    no-activity.

    ``limit``/``fetched`` back the ``meta`` completeness block: callers
    probe with ``limit + 1`` and pass the raw fetched row count (0 on a
    degraded read) so ``truncated``/``has_more`` are exact, not guessed.
    """
    return APIResponse(
        data={
            "entity_id": entity_id,
            "items": items,
            "count": len(items),
            "source": source,
            "source_status": (
                "missing" if degraded else ("available" if items else "empty")
            ),
        },
        meta=_probe_completeness(limit, fetched),
    ).to_dict()


@router.get("/{user_id}/exposures")
async def get_entity_exposures(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    content_type: str | None = Query(default=None),
):
    """Content and recommendation exposure facts for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        filters: dict = {"tenant_id": tenant.tenant_id, "user_id": user_id}
        if content_type:
            filters["content_type"] = content_type
        fetched = await repo.query_silver("silver_exposure_facts", filters, limit=limit + 1)
        items = fetched[:limit]
        degraded = False
    except Exception as exc:
        logger.warning("entity exposures unavailable: %s", exc)
        items = []
        fetched = []
        degraded = True
    return _silver_response(user_id, items, degraded=degraded, limit=limit, fetched=len(fetched))


@router.get("/{user_id}/revenue")
async def get_entity_revenue(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    revenue_type: str | None = Query(default=None),
):
    """Revenue and subscription facts for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        filters: dict = {"tenant_id": tenant.tenant_id, "user_id": user_id}
        if revenue_type:
            filters["revenue_type"] = revenue_type
        fetched = await repo.query_silver("silver_revenue_facts", filters, limit=limit + 1)
        items = fetched[:limit]
        degraded = False
    except Exception as exc:
        logger.warning("entity revenue unavailable: %s", exc)
        items = []
        fetched = []
        degraded = True
    return _silver_response(user_id, items, degraded=degraded, limit=limit, fetched=len(fetched))


@router.get("/{user_id}/friction")
async def get_entity_friction(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Friction and UX quality facts for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        fetched = await repo.query_silver(
            "silver_friction_facts",
            {"tenant_id": tenant.tenant_id, "user_id": user_id},
            limit=limit + 1,
        )
        items = fetched[:limit]
        degraded = False
    except Exception as exc:
        logger.warning("entity friction unavailable: %s", exc)
        items = []
        fetched = []
        degraded = True
    return _silver_response(user_id, items, degraded=degraded, limit=limit, fetched=len(fetched))


@router.get("/{user_id}/accounts")
async def get_entity_accounts(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """B2B organization and account activity facts for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        fetched = await repo.query_silver(
            "silver_account_activity_facts",
            {"tenant_id": tenant.tenant_id, "user_id": user_id},
            limit=limit + 1,
        )
        items = fetched[:limit]
        degraded = False
    except Exception as exc:
        logger.warning("entity accounts unavailable: %s", exc)
        items = []
        fetched = []
        degraded = True
    return _silver_response(user_id, items, degraded=degraded, limit=limit, fetched=len(fetched))


@router.get("/{user_id}/communications")
async def get_entity_communications(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    channel: str | None = Query(default=None),
    category: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    message_id: str | None = Query(default=None),
    state: str | None = Query(default=None),
    human_qualified: bool | None = Query(default=None),
    after: str | None = Query(default=None),
    before: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
):
    """Communication facts for this entity (Phase 18).

    Every item carries campaign/message/link references, delivery and
    engagement state, machine-activity classification, confidence, and
    provenance. ``human_qualified=true`` restricts to human-qualified
    engagement (suspected machine activity excluded).
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.comms.repository import CommsFactsRepository

    repo = CommsFactsRepository()
    items, next_cursor = await repo.list_for_entity(
        tenant.tenant_id, user_id,
        channel=channel, category=category, direction=direction,
        campaign_id=campaign_id, external_message_id=message_id,
        state=state, human_qualified=human_qualified,
        after=after, before=before, limit=limit, cursor=cursor,
    )
    summary = await repo.entity_summary(tenant.tenant_id, user_id)
    # list_for_entity() already computes next_cursor from an exact
    # over-fetch (it only sets it when the underlying result exceeded
    # `limit`), so has_more/truncated fall straight out of that — no
    # separate probe needed. This endpoint predates the APIResponse
    # envelope (returns a flat dict), so `meta` is added at the top level
    # rather than nested, to stay additive to the existing shape.
    has_more = next_cursor is not None
    return {
        "entity_id": user_id,
        "items": [_comm_item(row) for row in items],
        "counts": {k: int(v or 0) for k, v in summary.items()},
        "next_cursor": next_cursor,
        "count": len(items),
        "meta": {"limit": limit, "returned": len(items), "truncated": has_more, "has_more": has_more},
    }


def _comm_item(row: dict) -> dict:
    """Normalized communication item envelope — no raw PII, no payload blob."""
    return {
        "communication_fact_id": str(row.get("fact_id") or row.get("idempotency_key") or ""),
        "event_type": row.get("source_event_type") or row.get("comms_type"),
        "channel": row.get("channel"),
        "direction": row.get("direction"),
        "message_category": row.get("message_category"),
        "communication_state": row.get("communication_state") or row.get("deliverability"),
        "journey_role": row.get("journey_role"),
        "provider": row.get("provider"),
        "campaign_id": str(row["campaign_id"]) if row.get("campaign_id") else None,
        "external_message_id": row.get("external_message_id"),
        "external_thread_id": row.get("external_thread_id"),
        "sequence_step": row.get("sequence_step"),
        "variant_id": row.get("variant_id"),
        "link_id": row.get("link_id"),
        "recipient_display": row.get("recipient_display"),
        "bounce_type": row.get("bounce_type"),
        "engagement_type": row.get("engagement_type"),
        "engagement_confidence": _num_or_none(row.get("engagement_confidence")),
        "engagement_strength": row.get("engagement_strength"),
        "suspected_machine_activity": bool(row.get("suspected_machine_activity")),
        "machine_activity_probability": _num_or_none(row.get("machine_activity_probability")),
        "automated_response_kind": row.get("automated_response_kind"),
        "identity_confidence": _num_or_none(row.get("identity_confidence")),
        "campaign_resolution_confidence": _num_or_none(row.get("campaign_resolution_confidence")),
        "consent_snapshot_id": row.get("consent_snapshot_id"),
        "occurred_at": str(row.get("occurred_at")) if row.get("occurred_at") else None,
        "provenance": row.get("provenance"),
        "drill": {
            "campaign": f"/v1/campaigns/{row['campaign_id']}" if row.get("campaign_id") else None,
            "message": (
                f"/v1/campaigns/{row['campaign_id']}/messages/{row['external_message_id']}"
                if row.get("campaign_id") and row.get("external_message_id") else None
            ),
        },
    }


def _num_or_none(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@router.get("/{user_id}/communication-state")
async def get_entity_communication_state(
    user_id: str,
    request: Request,
    channel: str = Query(default="email"),
    scope: str = Query(default="marketing"),
):
    """Current communication state for this entity (Phase 8/18).

    Rebuildable projection: subscription and deliverability status, last
    engagement timestamps, human-qualified engagement counters, bounce and
    complaint counts, and suppression scopes.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")
    from services.comms.state import CommunicationStateService

    service = CommunicationStateService()
    state = await service.get(tenant.tenant_id, user_id, channel=channel, scope=scope)
    if state is None:
        # Derive on first read so the endpoint degrades gracefully for
        # entities whose async rebuild has not run yet.
        state = await service.rebuild_for_entity(
            tenant.tenant_id, user_id, channel=channel, scope=scope,
        )
    state = {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in state.items()}
    return {"entity_id": user_id, "communication_state": state}


@router.get("/{user_id}/integrations")
async def get_entity_integrations(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Server and integration operation facts for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        fetched = await repo.query_silver(
            "silver_server_operation_facts",
            {"tenant_id": tenant.tenant_id, "user_id": user_id},
            limit=limit + 1,
        )
        items = fetched[:limit]
        degraded = False
    except Exception as exc:
        logger.warning("entity integrations unavailable: %s", exc)
        items = []
        fetched = []
        degraded = True
    return _silver_response(user_id, items, degraded=degraded, limit=limit, fetched=len(fetched))


@router.get("/{user_id}/data-quality")
async def get_entity_data_quality(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Data quality and schema completeness observations for this entity."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    try:
        from repositories.repos import AnalyticsRepository
        repo = AnalyticsRepository()
        fetched = await repo.query_silver(
            "silver_data_quality_facts",
            {"tenant_id": tenant.tenant_id, "user_id": user_id},
            limit=limit + 1,
        )
        items = fetched[:limit]
        degraded = False
    except Exception as exc:
        logger.warning("entity data-quality unavailable: %s", exc)
        items = []
        fetched = []
        degraded = True
    return _silver_response(user_id, items, degraded=degraded, limit=limit, fetched=len(fetched))


# ═══════════════════════════════════════════════════════════════════════════
# Economic + cross-chain intelligence sub-resources (v8.12.0)
# Observation-only domains; each gate is the domain's profile360 flag so a
# disabled domain is indistinguishable from an absent one.
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/{user_id}/stablecoin")
async def get_entity_stablecoin_activity(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Stablecoin observations attributed to this entity (as sender or
    recipient via resolved entity refs or wallet ids)."""
    from config.settings import settings as _settings
    if not _settings.stablecoin.profile360_enabled:
        raise HTTPException(status_code=404, detail="Stablecoin Intelligence is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("read")

    from decimal import Decimal as _Decimal

    from repositories.stablecoin_repos import StablecoinObservationRepo

    rows = await StablecoinObservationRepo().find_many(
        {"tenant_id": tenant.tenant_id}, limit=2000,
    )
    matched = []
    for row in rows:
        from_ref = row.get("from_entity_ref") or {}
        to_ref = row.get("to_entity_ref") or {}
        if user_id not in (
            from_ref.get("id"), to_ref.get("id"),
            row.get("from_wallet_id"), row.get("to_wallet_id"),
        ):
            continue
        matched.append({
            key: str(value) if isinstance(value, _Decimal) else value
            for key, value in row.items()
        })
        # Collect one past `limit` so has_more/truncated are exact relative
        # to this 2000-row upstream scan (a true overflow beyond 2000
        # matches is a pre-existing, separate cap this doesn't change).
        if len(matched) > limit:
            break
    items = matched[:limit]
    finalized = [i for i in items if i.get("finality_status") == "finalized"]
    has_more = len(matched) > limit
    return {
        "entity_id": user_id,
        "items": items,
        "summary": {
            "observation_count": len(items),
            "finalized_count": len(finalized),
            "assets": sorted({i.get("canonical_asset_id") for i in items if i.get("canonical_asset_id")}),
        },
        "count": len(items),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {"source": "stablecoin_observations", "surface": "profile360"},
        "meta": {"limit": limit, "returned": len(items), "truncated": has_more, "has_more": has_more},
    }


@router.get("/{user_id}/derivatives")
async def get_entity_derivatives_trading(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Derivatives facts for trading accounts owned by this entity."""
    from config.settings import settings as _settings
    if not _settings.derivatives.profile360_enabled:
        raise HTTPException(status_code=404, detail="Derivatives Intelligence is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("read")

    from decimal import Decimal as _Decimal

    from repositories.derivatives_repos import FillRepo, PositionRepo, TradingAccountRepo

    accounts = await TradingAccountRepo().find_many(
        {"tenant_id": tenant.tenant_id, "owner_entity_id": user_id}, limit=200,
    )
    account_ids = {a["trading_account_id"] for a in accounts}
    items: list[dict] = []
    markets: set[str] = set()
    for repo in (PositionRepo(), FillRepo()):
        if len(items) > limit:
            break
        rows = await repo.find_many({"tenant_id": tenant.tenant_id}, limit=2000)
        for row in rows:
            if row.get("trading_account_id") not in account_ids:
                continue
            markets.add(row.get("canonical_market_id") or "")
            items.append({
                key: str(value) if isinstance(value, _Decimal) else value
                for key, value in row.items()
            })
            # Collect one past `limit` (instead of stopping exactly at it)
            # so has_more/truncated are exact relative to this scan, not
            # dependent on which repo happens to supply the overflow row.
            if len(items) > limit:
                break
    page = items[:limit]
    has_more = len(items) > limit
    return {
        "entity_id": user_id,
        "items": page,
        "summary": {
            "fact_count": len(page),
            "accounts": sorted(account_ids),
            "markets": sorted(m for m in markets if m),
        },
        "count": len(page),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {"source": "derivatives_facts", "surface": "profile360"},
        "meta": {"limit": limit, "returned": len(page), "truncated": has_more, "has_more": has_more},
    }


@router.get("/{user_id}/interoperability")
async def get_entity_interop_activity(
    user_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Cross-network activity attributed to this entity via intents it
    initiated and asset legs touching its wallet addresses."""
    from config.settings import settings as _settings
    if not _settings.interop.profile360_enabled:
        raise HTTPException(status_code=404, detail="Interoperability Intelligence is not enabled")
    tenant = request.state.tenant
    tenant.require_permission("read")

    from decimal import Decimal as _Decimal

    from repositories.interop_repos import InteropAssetLegRepo, InteropIntentRepo

    items: list[dict] = []
    providers: set[str] = set()
    paths: set[str] = set()

    intents = await InteropIntentRepo().find_many({"tenant_id": tenant.tenant_id}, limit=2000)
    for intent in intents:
        initiator = intent.get("initiator_entity_ref") or {}
        if initiator.get("id") != user_id and intent.get("initiator_address") != user_id:
            continue
        providers.add(intent.get("provider_id") or "")
        items.append({
            key: str(value) if isinstance(value, _Decimal) else value
            for key, value in intent.items()
        })

    legs = await InteropAssetLegRepo().find_many({"tenant_id": tenant.tenant_id}, limit=2000)
    for leg in legs:
        if user_id not in (leg.get("from_address"), leg.get("to_address")):
            continue
        items.append({
            key: str(value) if isinstance(value, _Decimal) else value
            for key, value in leg.items()
        })
        # Collect one past `limit` so has_more/truncated are exact relative
        # to this scan — the intents loop above is already unconditional /
        # unbounded by `limit`, so between the two this reflects the true
        # matched total up to each source's 2000-row upstream cap.
        if len(items) > limit:
            break

    page = items[:limit]
    has_more = len(items) > limit
    return {
        "entity_id": user_id,
        "items": page,
        "summary": {
            "fact_count": len(page),
            "providers": sorted(p for p in providers if p),
            "paths": sorted(p for p in paths if p),
        },
        "count": len(page),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {"source": "interop_facts", "surface": "profile360"},
        "meta": {"limit": limit, "returned": len(page), "truncated": has_more, "has_more": has_more},
    }
