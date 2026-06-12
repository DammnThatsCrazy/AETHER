"""
Aether Service — Identity
Identity resolution, profile management, merge operations.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger
from dependencies.providers import get_cache, get_graph, get_producer
from repositories.repos import IdentityRepository

logger = get_logger("aether.service.identity")
router = APIRouter(prefix="/v1/identity", tags=["Identity"])


_repo: Optional[IdentityRepository] = None


def _get_repo(
    graph: GraphClient = Depends(get_graph),
    cache: CacheClient = Depends(get_cache),
) -> IdentityRepository:
    global _repo
    if _repo is None:
        _repo = IdentityRepository(graph, cache)
    return _repo


# ── Models ────────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    company_id: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class MergeRequest(BaseModel):
    primary_user_id: str
    secondary_user_id: str
    reason: str = "manual_merge"


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/profiles/{user_id}")
async def get_profile(
    user_id: str,
    request: Request,
    repo: IdentityRepository = Depends(_get_repo),
):
    """Get a user profile by ID."""
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
    repo: IdentityRepository = Depends(_get_repo),
    producer: EventProducer = Depends(get_producer),
):
    """Create or update a user profile."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    profile = await repo.upsert_profile(
        tenant.tenant_id, user_id, body.model_dump(exclude_none=True)
    )

    await producer.publish(Event(
        topic=Topic.PROFILE_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="identity",
        payload={
            "user_id": user_id,
            "fields_updated": list(body.model_dump(exclude_none=True).keys()),
        },
    ))

    return APIResponse(data=profile).to_dict()


@router.post("/merge")
async def merge_identities(
    body: MergeRequest,
    request: Request,
    repo: IdentityRepository = Depends(_get_repo),
    producer: EventProducer = Depends(get_producer),
):
    """Merge two user identities into one."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    merged = await repo.merge_identities(
        tenant.tenant_id, body.primary_user_id, body.secondary_user_id
    )

    await producer.publish(Event(
        topic=Topic.IDENTITY_MERGED,
        tenant_id=tenant.tenant_id,
        source_service="identity",
        payload={
            "primary_id": body.primary_user_id,
            "secondary_id": body.secondary_user_id,
            "reason": body.reason,
        },
    ))

    return APIResponse(data=merged).to_dict()


@router.get("/profiles/{user_id}/graph")
async def get_profile_graph(
    user_id: str,
    request: Request,
    repo: IdentityRepository = Depends(_get_repo),
):
    """Get the graph neighborhood for a user (sessions, devices, events)."""
    tenant = request.state.tenant
    # Verify the profile belongs to this tenant before returning graph data
    profile = await repo.get_profile(tenant.tenant_id, user_id)
    if not profile:
        raise NotFoundError("Profile")
    connections = await repo.get_graph_neighbors(user_id)
    return APIResponse(data={
        "user_id": user_id,
        "connections": connections,
    }).to_dict()


# ── SIWX Session Binding ──────────────────────────────────────────────────────


class SIWXBindRequest(BaseModel):
    """Bind a SIWX session to a caller identity for entitlement reuse."""
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
async def bind_siwx_session(body: SIWXBindRequest, request: Request):
    """
    Bind a SIWX (Sign-In With X) session to an identity for entitlement reuse.
    Once bound, the entitlement service can reuse active entitlements for this
    session without requiring a new payment.
    """
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

    # Persist via the x402 IdempotencyStore — session_id acts as the key so
    # the entitlement service can look it up during preflight checks.
    from services.x402.idempotency import get_idempotency_store
    store = get_idempotency_store()
    await store.record(tenant.tenant_id, f"siwx:{body.session_id}", record.model_dump())

    logger.info(
        f"SIWX session bound: session={body.session_id} "
        f"wallet={body.wallet_address} holder={holder_id} tenant={tenant.tenant_id}"
    )
    return APIResponse(data=record.model_dump()).to_dict()


@router.get("/siwx/status/{session_id}")
async def siwx_session_status(session_id: str, request: Request):
    """
    Check the status of a SIWX session binding.
    Returns the session record if active, or a not-found response if expired/unbound.
    """
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
async def revoke_siwx_session(session_id: str, request: Request):
    """Revoke a SIWX session binding, preventing further entitlement reuse."""
    from services.x402.idempotency import get_idempotency_store
    tenant = request.state.tenant
    tenant.require_permission("write")

    store = get_idempotency_store()
    record = await store.lookup(tenant.tenant_id, f"siwx:{session_id}")
    if record is None:
        raise NotFoundError("SIWXSession")

    record["active"] = False
    await store.record(tenant.tenant_id, f"siwx:{session_id}", record)
    logger.info(f"SIWX session revoked: session={session_id} tenant={tenant.tenant_id}")
    return APIResponse(data={"session_id": session_id, "revoked": True}).to_dict()
