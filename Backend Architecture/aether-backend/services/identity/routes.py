"""
Aether Service — Identity
Identity resolution, profile management, merge operations.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, NotFoundError, PaginatedResponse, PaginationMeta
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
