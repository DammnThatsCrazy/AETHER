"""
Aether Service — Identity Resolution API
Full production identity graph endpoints.

Routes:
    POST   /v1/identity/resolve                     Resolve identity from event/signals
    GET    /v1/identity/entities/{entity_id}        Get canonical entity
    GET    /v1/identity/entities/{entity_id}/aliases     Entity aliases (redacted)
    GET    /v1/identity/entities/{entity_id}/graph       Identity graph neighborhood
    GET    /v1/identity/entities/{entity_id}/audit       Audit / history
    GET    /v1/identity/conflicts                   Conflict / candidate queue
    POST   /v1/identity/merge                       Operator merge
    POST   /v1/identity/split                       Operator split / rollback
    POST   /v1/identity/recompute                   Recompute identity
    GET    /v1/identity/health                       Resolver health
    # Legacy profile routes (backwards-compatible)
    GET    /v1/identity/profiles/{user_id}
    PUT    /v1/identity/profiles/{user_id}
    GET    /v1/identity/profiles/{user_id}/graph
    # SIWX session binding (unchanged)
    POST   /v1/identity/siwx/bind
    GET    /v1/identity/siwx/status/{session_id}
    DELETE /v1/identity/siwx/{session_id}
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_graph, get_producer
from repositories.repos import IdentityRepository

from .audit import IdentityAuditWriter
from .conflicts import IdentityConflictManager
from .exceptions import CrossTenantError, UnauthorizedOperatorAction
from .graph_writer import IdentityGraphWriter
from .metrics import IdentityMetrics
from .repository import IdentityResolutionRepository
from .resolver import IdentityResolutionService
from .schemas import (
    IdentityConflictResponse,
    IdentityFragmentSplitRequest,
    IdentityFragmentSplitResponse,
    IdentityGraphResponse,
    IdentityHealthResponse,
    IdentityMergeRequest,
    IdentityMergeResponse,
    IdentityRecomputeRequest,
    IdentityRecomputeResponse,
    IdentityResolveRequest,
    IdentityResolveResponse,
    IdentitySplitPreviewRequest,
    IdentitySplitPreviewResponse,
    IdentitySplitRequest,
    IdentitySplitResponse,
    IdentitySuppressRequest,
    IdentitySuppressResponse,
    IdentityUnsuppressResponse,
)

logger = get_logger("aether.service.identity")
router = APIRouter(prefix="/v1/identity", tags=["Identity"])

# ── Singleton service instances ───────────────────────────────────────────────

_resolution_repo: Optional[IdentityResolutionRepository] = None
_resolver: Optional[IdentityResolutionService] = None
_identity_repo: Optional[IdentityRepository] = None


def _get_identity_repo(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> IdentityRepository:
    global _identity_repo
    if _identity_repo is None:
        _identity_repo = IdentityRepository(graph, cache)
    return _identity_repo


def _get_resolver() -> IdentityResolutionService:
    global _resolution_repo, _resolver
    if _resolver is None:
        _resolution_repo = IdentityResolutionRepository()
        metrics = IdentityMetrics()
        graph_writer = IdentityGraphWriter(_resolution_repo, metrics)
        audit_writer = IdentityAuditWriter(_resolution_repo)
        conflict_manager = IdentityConflictManager(_resolution_repo)
        _resolver = IdentityResolutionService(
            repo=_resolution_repo,
            graph_writer=graph_writer,
            audit_writer=audit_writer,
            conflict_manager=conflict_manager,
            metrics=metrics,
        )
    return _resolver


def get_identity_resolver() -> IdentityResolutionService:
    """Public accessor used by the ingestion pipeline and other services."""
    return _get_resolver()


def _get_resolution_repo() -> IdentityResolutionRepository:
    _get_resolver()  # ensure initialized
    assert _resolution_repo is not None
    return _resolution_repo


# ── Identity Resolution API ───────────────────────────────────────────────────

@router.post("/resolve", response_model=IdentityResolveResponse)
async def resolve_identity(
    body: IdentityResolveRequest,
    request: Request,
) -> dict:
    """
    Resolve identity from a direct signal payload.
    Returns canonical entity ID, confidence, and audit trail reference.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()

    # Build a synthetic event dict from the request body
    event = {
        "event_id": body.event_id,
        "tenant_id": tenant.tenant_id,
        "user_id": body.user_id,
        "anonymous_id": body.anonymous_id,
        "session_id": body.session_id,
        "context": {
            **(body.context or {}),
            "consent": body.consent_snapshot,
            "orgId": body.org_id,
            "actorId": body.agent_id,
            "actorKind": "agent" if body.agent_id else None,
        },
        "properties": {
            **(body.properties or {}),
            "email": body.email,
            "phone": body.phone,
            "wallet_address": body.wallet_address,
            "wallet_signature_verified": body.wallet_signature_verified,
            "external_id": body.external_id,
        },
        "source": "api",
    }

    decision = await resolver.resolve_event(event, tenant.tenant_id)

    return APIResponse(data=IdentityResolveResponse(
        tenant_id=decision.tenant_id,
        canonical_entity_id=decision.canonical_entity_id,
        decision=decision.decision.value,
        confidence=decision.confidence,
        confidence_tier=decision.confidence_tier.value,
        reason_codes=decision.reason_codes,
        linked_aliases=decision.linked_aliases,
        candidate_entity_ids=decision.candidate_entity_ids,
        conflict_id=decision.conflict_id,
        source_event_ids=decision.source_event_ids,
        graph_edges_written=decision.graph_edges_written,
        blocked_reason=decision.blocked_reason,
        audit_id=decision.audit_id,
        is_new_entity=decision.is_new_entity,
    ).model_dump()).to_dict()


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, request: Request) -> dict:
    """Get a canonical identity entity by ID.

    A merged (secondary) entity id follows its merge tombstone to the surviving
    entity instead of returning a stale frozen record; the response carries
    additive ``resolved_entity_id`` + ``redirected``.
    """
    tenant = request.state.tenant
    repo = _get_resolution_repo()
    from services.identity.redirects import resolve_entity_redirect

    resolved_id, redirected = await resolve_entity_redirect(repo, tenant.tenant_id, entity_id)
    subject = await repo.get_subject_by_canonical_entity_id(tenant.tenant_id, resolved_id)
    if not subject:
        raise NotFoundError("IdentityEntity")
    return APIResponse(
        data={**subject, "resolved_entity_id": resolved_id, "redirected": redirected}
    ).to_dict()


@router.get("/entities/{entity_id}/aliases")
async def get_entity_aliases(entity_id: str, request: Request) -> dict:
    """Get aliases for a canonical entity. Sensitive values are redacted."""
    tenant = request.state.tenant
    repo = _get_resolution_repo()

    subject = await repo.get_subject_by_canonical_entity_id(tenant.tenant_id, entity_id)
    if not subject:
        raise NotFoundError("IdentityEntity")

    aliases = await repo.get_entity_aliases(tenant.tenant_id, entity_id)
    # Return redacted display values only — never raw values or hashes
    safe_aliases = [
        {
            "id": a["id"],
            "alias_type": a["alias_type"],
            "alias_display_value_redacted": a.get("alias_display_value_redacted", ""),
            "source": a.get("source", ""),
            "confidence": a.get("confidence", 0.0),
            "confidence_tier": a.get("confidence_tier", ""),
            "first_seen_at": a.get("first_seen_at", ""),
            "last_seen_at": a.get("last_seen_at", ""),
            "revoked_at": a.get("revoked_at"),
        }
        for a in aliases
    ]
    return APIResponse(data={"entity_id": entity_id, "aliases": safe_aliases}).to_dict()


@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(entity_id: str, request: Request) -> dict:
    """Get identity graph neighborhood for an entity (tenant-scoped)."""
    tenant = request.state.tenant
    repo = _get_resolution_repo()

    subject = await repo.get_subject_by_canonical_entity_id(tenant.tenant_id, entity_id)
    if not subject:
        raise NotFoundError("IdentityEntity")

    edges = await repo.get_entity_graph(tenant.tenant_id, entity_id)
    # Sanitize: remove any raw hashes from public response
    safe_edges = [
        {
            "id": e["id"],
            "source_entity_id": e["source_entity_id"],
            "target_entity_id": e["target_entity_id"],
            "edge_type": e["edge_type"],
            "confidence": e.get("confidence", 0.0),
            "confidence_tier": e.get("confidence_tier", ""),
            "reason_codes": e.get("reason_codes", []),
            "created_at": e.get("created_at", ""),
            "revoked_at": e.get("revoked_at"),
        }
        for e in edges
    ]
    return APIResponse(data={
        "entity_id": entity_id,
        "tenant_id": tenant.tenant_id,
        "edges": safe_edges,
    }).to_dict()


@router.get("/entities/{entity_id}/audit")
async def get_entity_audit(
    entity_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """Get merge/link/split audit history for a canonical entity."""
    tenant = request.state.tenant
    repo = _get_resolution_repo()

    subject = await repo.get_subject_by_canonical_entity_id(tenant.tenant_id, entity_id)
    if not subject:
        raise NotFoundError("IdentityEntity")

    audit_records = await repo.get_entity_audit(tenant.tenant_id, entity_id, limit=limit)
    merge_history = await repo.get_merge_history(tenant.tenant_id, entity_id, limit=limit)
    split_history = await repo.get_split_history(tenant.tenant_id, entity_id, limit=limit)

    return APIResponse(data={
        "entity_id": entity_id,
        "audit_records": audit_records,
        "merge_history": merge_history,
        "split_history": split_history,
    }).to_dict()


@router.get("/conflicts")
async def list_conflicts(
    request: Request,
    status: Optional[str] = Query(None, description="Filter by status: open|resolved"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List identity conflict/candidate queue for this tenant."""
    tenant = request.state.tenant
    repo = _get_resolution_repo()
    conflicts = await repo.get_conflicts(tenant.tenant_id, status=status, limit=limit)
    return APIResponse(data={"conflicts": conflicts, "total": len(conflicts)}).to_dict()


@router.post("/merge", response_model=IdentityMergeResponse)
async def merge_identities(
    body: IdentityMergeRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """
    Operator-approved merge of two canonical entities.
    Requires write permission.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()
    decision = await resolver.operator_merge(
        tenant_id=tenant.tenant_id,
        primary_entity_id=body.primary_entity_id,
        secondary_entity_id=body.secondary_entity_id,
        actor_id=getattr(tenant, "user_id", "operator") or "operator",
        actor_type="operator",
        reason=body.reason,
    )

    await producer.publish(Event(
        topic=Topic.IDENTITY_MERGED,
        tenant_id=tenant.tenant_id,
        source_service="identity",
        payload={
            "primary_entity_id": body.primary_entity_id,
            "secondary_entity_id": body.secondary_entity_id,
            "canonical_entity_id": decision.canonical_entity_id,
            "reason": body.reason,
        },
    ))

    return APIResponse(data=IdentityMergeResponse(
        canonical_entity_id=decision.canonical_entity_id,
        decision=decision.decision.value,
        confidence=decision.confidence,
        confidence_tier=decision.confidence_tier.value,
        reason_codes=decision.reason_codes,
        audit_id=decision.audit_id,
        graph_edges_written=decision.graph_edges_written,
    ).model_dump()).to_dict()


@router.post("/split", response_model=IdentitySplitResponse)
async def split_identity(
    body: IdentitySplitRequest,
    request: Request,
) -> dict:
    """
    Operator-approved split / rollback of an incorrectly merged entity.
    Requires write permission.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()
    result = await resolver.operator_split(
        tenant_id=tenant.tenant_id,
        original_entity_id=body.original_entity_id,
        actor_id=getattr(tenant, "user_id", "operator") or "operator",
        actor_type="operator",
        reason=body.reason,
        source_merge_event_id=body.source_merge_event_id,
    )

    return APIResponse(data=IdentitySplitResponse(**result).model_dump()).to_dict()


@router.post("/split/preview", response_model=IdentitySplitPreviewResponse)
async def preview_fragment_split(
    body: IdentitySplitPreviewRequest,
    request: Request,
) -> dict:
    """
    NON-MUTATING impact analysis for a fragment-aware identity split.

    Reports which aliases would be reassigned, observations relinked, and
    SAME_AS edges revoked, plus risk notes. When the split is not permitted
    (cross-tenant fragment, identity cycle, campaign-only sameness, …) the
    response carries ``allowed=False`` and a typed ``rejection_reason`` — it
    never mutates state and never surfaces a raw 500.
    """
    tenant = request.state.tenant
    tenant.require_permission("read")

    resolver = _get_resolver()
    result = await resolver.preview_fragment_split(
        tenant_id=tenant.tenant_id,
        entity_id=body.entity_id,
        fragments=body.fragments.model_dump(),
        mode=body.mode,
        actor_id=getattr(tenant, "user_id", "operator") or "operator",
        actor_type="operator",
        reason=body.reason,
        target_entity_id=body.target_entity_id,
        source_merge_event_id=body.source_merge_event_id,
    )
    return APIResponse(data=IdentitySplitPreviewResponse(**result).model_dump()).to_dict()


@router.post("/split/execute", response_model=IdentityFragmentSplitResponse)
async def execute_fragment_split(
    body: IdentityFragmentSplitRequest,
    request: Request,
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """
    Execute a fragment-aware identity split (operator-gated, audited).

    Reassigns the named aliases/observations onto a new / restored / existing
    entity and revokes the SAME_AS edges tying the fragment to the original.
    The immutable split event (``create_split_event``) is the durable audit
    record — mirroring the existing ``/split`` route. A blocked split returns
    ``allowed=False`` + a typed ``rejection_reason`` rather than raising, so
    callers never see a raw 500.

    On an applied split we publish ``IDENTITY_SPLIT`` so the measurement plane
    re-derives journeys/attribution for BOTH the original and the fragment's
    new home — a split reassigns touchpoints between entities exactly as a
    merge does, so it must trigger the same recompute.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()
    result = await resolver.fragment_split(
        tenant_id=tenant.tenant_id,
        entity_id=body.entity_id,
        fragments=body.fragments.model_dump(),
        mode=body.mode,
        actor_id=getattr(tenant, "user_id", "operator") or "operator",
        actor_type="operator",
        reason=body.reason,
        target_entity_id=body.target_entity_id,
        source_merge_event_id=body.source_merge_event_id,
    )

    if result.get("allowed"):
        await producer.publish(Event(
            topic=Topic.IDENTITY_SPLIT,
            tenant_id=tenant.tenant_id,
            source_service="identity",
            payload={
                "original_entity_id": body.entity_id,
                "resulting_entity_id": result.get("resulting_entity_id"),
                "split_event_id": result.get("split_event_id"),
                "mode": body.mode,
                "reason": body.reason,
            },
        ))

    return APIResponse(data=IdentityFragmentSplitResponse(**result).model_dump()).to_dict()


@router.post("/recompute", response_model=IdentityRecomputeResponse)
async def recompute_identity(
    body: IdentityRecomputeRequest,
    request: Request,
) -> dict:
    """
    Operator-triggered identity recompute for an entity or event range.
    Requires write permission.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()
    result = await resolver.recompute(
        tenant_id=tenant.tenant_id,
        entity_id=body.entity_id,
        event_ids=body.event_ids,
        reason=body.reason,
    )
    return APIResponse(data=IdentityRecomputeResponse(**result).model_dump()).to_dict()


@router.post("/suppress", response_model=IdentitySuppressResponse)
async def suppress_identifier(body: IdentitySuppressRequest, request: Request) -> dict:
    """
    Create a suppression rule blocking an identifier hash from being used in identity linking.
    Requires write permission.
    """
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()
    result = await resolver.suppress_identifier(
        tenant_id=tenant.tenant_id,
        identifier_type=body.identifier_type,
        identifier_hash=body.identifier_hash,
        reason=body.reason,
        subject_id=body.subject_id,
        actor_id=getattr(tenant, "user_id", "operator") or "operator",
        expires_at=body.expires_at,
    )
    return APIResponse(data=IdentitySuppressResponse(**result).model_dump()).to_dict()


@router.delete("/suppress/{suppression_id}", response_model=IdentityUnsuppressResponse)
async def unsuppress_identifier(suppression_id: str, request: Request) -> dict:
    """Revoke a suppression rule. Requires write permission."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    resolver = _get_resolver()
    result = await resolver.unsuppress_identifier(
        tenant_id=tenant.tenant_id,
        suppression_id=suppression_id,
        actor_id=getattr(tenant, "user_id", "operator") or "operator",
    )
    return APIResponse(data=IdentityUnsuppressResponse(**result).model_dump()).to_dict()


@router.get("/suppressions")
async def list_suppressions(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """List active suppression rules for this tenant."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    repo = _get_resolution_repo()
    rules = await repo.get_suppressions(tenant.tenant_id, limit=limit)
    return APIResponse(data={"suppressions": rules, "total": len(rules)}).to_dict()


@router.get("/health", response_model=IdentityHealthResponse)
async def identity_health(request: Request) -> dict:
    """Identity resolver health check — returns operational metrics."""
    tenant = request.state.tenant
    repo = _get_resolution_repo()

    db_alive = await repo.ping()
    health_data: dict = {}
    if db_alive:
        try:
            health_data = await repo.get_identity_health(tenant.tenant_id)
        except Exception:
            db_alive = False

    status = "healthy" if db_alive else "degraded"
    return APIResponse(data=IdentityHealthResponse(
        status=status,
        resolver_enabled=db_alive,
        total_entities=health_data.get("total_subjects", 0),
        total_aliases=health_data.get("total_aliases", 0),
        total_clusters=health_data.get("total_clusters", 0),
        open_conflicts=health_data.get("open_conflicts", 0),
        recent_merges=health_data.get("recent_merges", 0),
        recent_splits=health_data.get("recent_splits", 0),
        blocked_consent=health_data.get("blocked_consent", 0),
        blocked_cross_tenant=health_data.get("blocked_cross_tenant", 0),
        blocked_fingerprint_only=health_data.get("blocked_fingerprint_only", 0),
        tenant_id=tenant.tenant_id,
    ).model_dump()).to_dict()


# ── Legacy profile routes (backwards-compatible) ──────────────────────────────

class ProfileUpdate(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    company_id: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


@router.get("/profiles/{user_id}")
async def get_profile(
    user_id: str,
    request: Request,
    repo: IdentityRepository = Depends(_get_identity_repo),
) -> dict:
    """Get a user profile by ID (legacy endpoint)."""
    tenant = request.state.tenant
    profile = await repo.get_profile(tenant.tenant_id, user_id)
    if not profile:
        raise NotFoundError("Profile")
    return APIResponse(data=profile).to_dict()


@router.put("/profiles/{user_id}")
async def upsert_profile(
    user_id: str,
    body: ProfileUpdate,
    request: Request,
    repo: IdentityRepository = Depends(_get_identity_repo),
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Create or update a user profile (legacy endpoint)."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    profile = await repo.upsert_profile(
        tenant.tenant_id, user_id, body.model_dump(exclude_none=True)
    )
    await producer.publish(Event(
        topic=Topic.PROFILE_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="identity",
        payload={"user_id": user_id, "fields_updated": list(body.model_dump(exclude_none=True).keys())},
    ))
    return APIResponse(data=profile).to_dict()


@router.get("/profiles/{user_id}/graph")
async def get_profile_graph(
    user_id: str,
    request: Request,
    repo: IdentityRepository = Depends(_get_identity_repo),
) -> dict:
    """Get graph neighborhood for a user (legacy endpoint, tenant-scoped)."""
    tenant = request.state.tenant
    profile = await repo.get_profile(tenant.tenant_id, user_id)
    if not profile:
        raise NotFoundError("Profile")
    connections = await repo.get_graph_neighbors(user_id)
    return APIResponse(data={"user_id": user_id, "connections": connections}).to_dict()


# ── SIWX Session Binding (unchanged) ─────────────────────────────────────────

class SIWXBindRequest(BaseModel):
    session_id: str
    wallet_address: str
    chain_id: str = "eip155:8453"
    signature: str
    message: str
    holder_id: Optional[str] = None
    holder_type: str = "user"
    ttl_seconds: int = 3600


class SIWXSessionRecord(BaseModel):
    session_id: str
    tenant_id: str
    wallet_address: str
    chain_id: str
    holder_id: str
    holder_type: str
    bound_at: str
    expires_at: str
    active: bool = True


@router.post("/siwx/bind")
async def bind_siwx_session(body: SIWXBindRequest, request: Request) -> dict:
    """Bind a SIWX session to an identity for entitlement reuse."""
    import uuid as _uuid
    from datetime import datetime, timedelta, timezone

    tenant = request.state.tenant
    tenant.require_permission("write")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=body.ttl_seconds)
    holder_id = body.holder_id or getattr(tenant, "user_id", "") or body.wallet_address

    record = SIWXSessionRecord(
        session_id=body.session_id,
        tenant_id=tenant.tenant_id,
        wallet_address=body.wallet_address,
        chain_id=body.chain_id,
        holder_id=holder_id,
        holder_type=body.holder_type,
        bound_at=now.isoformat(),
        expires_at=expires.isoformat(),
        active=True,
    )

    from services.x402.idempotency import get_idempotency_store
    store = get_idempotency_store()
    await store.record(tenant.tenant_id, f"siwx:{body.session_id}", record.model_dump())

    logger.info(
        "SIWX session bound: session=%s wallet=%s tenant=%s",
        body.session_id, body.wallet_address, tenant.tenant_id,
    )
    return APIResponse(data=record.model_dump()).to_dict()


@router.get("/siwx/status/{session_id}")
async def siwx_session_status(session_id: str, request: Request) -> dict:
    """Check status of a SIWX session binding."""
    from datetime import datetime, timezone
    tenant = request.state.tenant
    from services.x402.idempotency import get_idempotency_store
    store = get_idempotency_store()
    record = await store.lookup(tenant.tenant_id, f"siwx:{session_id}")
    if record is None:
        raise NotFoundError("SIWXSession")
    now = datetime.now(timezone.utc).isoformat()
    active = record.get("active", True) and record.get("expires_at", "") > now
    return APIResponse(data={**record, "active": active}).to_dict()


@router.delete("/siwx/{session_id}")
async def revoke_siwx_session(session_id: str, request: Request) -> dict:
    """Revoke a SIWX session binding."""
    from services.x402.idempotency import get_idempotency_store
    tenant = request.state.tenant
    tenant.require_permission("write")
    store = get_idempotency_store()
    record = await store.lookup(tenant.tenant_id, f"siwx:{session_id}")
    if record is None:
        raise NotFoundError("SIWXSession")
    record["active"] = False
    await store.record(tenant.tenant_id, f"siwx:{session_id}", record)
    logger.info("SIWX session revoked: session=%s tenant=%s", session_id, tenant.tenant_id)
    return APIResponse(data={"session_id": session_id, "revoked": True}).to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# Identity Assurance — Verification API (additive)
#
#   POST /v1/identity/verification/email/challenges
#   POST /v1/identity/verification/email/challenges/{challenge_id}/verify
#   GET  /v1/identity/verification/email/callback           (non-consuming)
#   POST /v1/identity/verification/email/challenges/{challenge_id}/consume
#   POST /v1/identity/verification/oidc
#   GET  /v1/identity/entities/{canonical_entity_id}/evidence   (redacted)
#   POST /v1/identity/evidence/{evidence_id}/revoke
# ═══════════════════════════════════════════════════════════════════════════

from shared.common.common import BadRequestError  # noqa: E402

from .evidence import EvidenceService  # noqa: E402
from .verification import EmailVerificationService  # noqa: E402

# ── Verification service singletons ────────────────────────────────────────

_evidence_service: Optional[EvidenceService] = None
_email_verification_service: Optional[EmailVerificationService] = None


def _get_evidence_service() -> EvidenceService:
    global _evidence_service
    if _evidence_service is None:
        _evidence_service = EvidenceService()
    return _evidence_service


def _get_email_verification_service() -> EmailVerificationService:
    global _email_verification_service
    if _email_verification_service is None:
        _email_verification_service = EmailVerificationService(
            evidence_service=_get_evidence_service()
        )
    return _email_verification_service


# ── Request models ─────────────────────────────────────────────────────────

class VerificationEmailChallengeRequest(BaseModel):
    email: str
    method: str = Field(default="email_otp")
    purpose: str = Field(default="identity_verification")
    consent_snapshot: Optional[dict] = None


class VerificationOTPVerifyRequest(BaseModel):
    code: str


class VerificationOIDCRequest(BaseModel):
    # A RAW provider ID token — the service verifies its RS256 signature against
    # the issuer's JWKS and enforces iss/aud/exp/nonce. Never accept a
    # pre-decoded claims dict from the client.
    id_token: str
    issuer_allowlist: list[str] = Field(default_factory=list)
    audience: str
    nonce: Optional[str] = None
    consent_snapshot: Optional[dict] = None


class EvidenceRevokeRequest(BaseModel):
    reason: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/verification/email/challenges")
async def issue_email_verification_challenge(
    body: VerificationEmailChallengeRequest,
    request: Request,
) -> dict:
    """Issue an email OTP / magic-link ownership-verification challenge."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    service = _get_email_verification_service()
    try:
        result = await service.issue_email_challenge(
            tenant_id=tenant.tenant_id,
            email=body.email,
            method=body.method,
            purpose=body.purpose,
            consent_snapshot=body.consent_snapshot,
        )
    except ValueError:
        # Never echo the raw email back into the error.
        raise BadRequestError("Invalid email address")
    return APIResponse(data=result).to_dict()


@router.post("/verification/email/challenges/{challenge_id}/verify")
async def verify_email_verification_otp(
    challenge_id: str,
    body: VerificationOTPVerifyRequest,
    request: Request,
) -> dict:
    """Verify an OTP code for a challenge; issues evidence on success."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    service = _get_email_verification_service()
    result = await service.verify_email_otp(
        tenant_id=tenant.tenant_id,
        challenge_id=challenge_id,
        code=body.code,
    )
    return APIResponse(data=result).to_dict()


@router.get("/verification/email/callback")
async def verify_email_magic_link_callback(
    request: Request,
    cid: str = Query(..., description="Challenge id"),
    t: str = Query(..., description="Magic-link token"),
) -> dict:
    """GET landing for a magic link. NON-CONSUMING and scanner-safe: validates
    the token but never consumes the challenge or issues evidence."""
    tenant = request.state.tenant
    service = _get_email_verification_service()
    result = await service.validate_magic_link(
        tenant_id=tenant.tenant_id,
        challenge_id=cid,
        token=t,
    )
    return APIResponse(data=result).to_dict()


@router.post("/verification/email/challenges/{challenge_id}/consume")
async def consume_email_magic_link(
    challenge_id: str,
    request: Request,
) -> dict:
    """Consume a previously validated magic link; issues evidence on success."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    service = _get_email_verification_service()
    result = await service.consume_magic_link(
        tenant_id=tenant.tenant_id,
        challenge_id=challenge_id,
    )
    return APIResponse(data=result).to_dict()


@router.post("/verification/oidc")
async def verify_oidc_trusted_claim(
    body: VerificationOIDCRequest,
    request: Request,
) -> dict:
    """Accept a raw OIDC/SSO ID token, verify it server-side (RS256 signature
    against the issuer JWKS + iss/aud/exp/nonce), and, when trusted, issue
    authoritative email-ownership evidence."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    service = _get_email_verification_service()
    result = await service.verify_trusted_claim(
        tenant_id=tenant.tenant_id,
        id_token=body.id_token,
        issuer_allowlist=body.issuer_allowlist,
        expected_audience=body.audience,
        expected_nonce=body.nonce,
        consent_snapshot=body.consent_snapshot,
    )
    return APIResponse(data=result).to_dict()


@router.get("/entities/{canonical_entity_id}/evidence")
async def list_entity_verification_evidence(
    canonical_entity_id: str,
    request: Request,
) -> dict:
    """List REDACTED verification evidence bound to a canonical entity (§56)."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    service = _get_evidence_service()
    rows = await service.list_for_entity(tenant.tenant_id, canonical_entity_id)
    return APIResponse(data={
        "canonical_entity_id": canonical_entity_id,
        "evidence": rows,
        "total": len(rows),
    }).to_dict()


@router.post("/evidence/{evidence_id}/revoke")
async def revoke_verification_evidence(
    evidence_id: str,
    body: EvidenceRevokeRequest,
    request: Request,
) -> dict:
    """Revoke a verification evidence row (operator action)."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    service = _get_evidence_service()
    row = await service.revoke_evidence(
        tenant.tenant_id, evidence_id, reason=body.reason
    )
    if row is None:
        raise NotFoundError("VerificationEvidence")
    return APIResponse(data={
        "evidence_id": evidence_id,
        "status": row.get("status"),
        "revoked_at": row.get("revoked_at"),
    }).to_dict()
