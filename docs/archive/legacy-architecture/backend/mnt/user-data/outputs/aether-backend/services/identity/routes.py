"""
Aether Service — Identity
Identity resolution, profile management, merge operations.
Tech: Node.js (Fastify) + Neptune client in prod.
Scaling: Read replicas for query load.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from repositories.repos import IdentityRepository
from shared.cache.cache import CacheClient
from shared.common.common import APIResponse
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import GraphClient
from shared.logger.logger import get_logger

logger = get_logger("aether.service.identity")
router = APIRouter(prefix="/v1/identity", tags=["Identity"])

# Dependencies
_graph = GraphClient()
_cache = CacheClient()
_repo = IdentityRepository(_graph, _cache)
_producer = EventProducer()


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
async def get_profile(user_id: str, request: Request):
    """Get a user profile by ID."""
    tenant = request.state.tenant
    profile = await _repo.get_profile(tenant.tenant_id, user_id)
    if not profile:
        from shared.common.common import NotFoundError
        raise NotFoundError("Profile")
    return APIResponse(data=profile).to_dict()


@router.put("/profiles/{user_id}")
async def upsert_profile(user_id: str, body: ProfileUpdate, request: Request):
    """Create or update a user profile."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    profile = await _repo.upsert_profile(
        tenant.tenant_id, user_id, body.model_dump(exclude_none=True)
    )

    await _producer.publish(Event(
        topic=Topic.PROFILE_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="identity",
        payload={"user_id": user_id, "fields_updated": list(body.model_dump(exclude_none=True).keys())},
    ))

    return APIResponse(data=profile).to_dict()


@router.post("/merge")
async def merge_identities(body: MergeRequest, request: Request):
    """Merge two user identities into one."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    merged = await _repo.merge_identities(
        tenant.tenant_id, body.primary_user_id, body.secondary_user_id
    )

    await _producer.publish(Event(
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
async def get_profile_graph(user_id: str, request: Request):
    """Get the graph neighborhood for a user (sessions, devices, events)."""
    neighbors = await _graph.get_neighbors(user_id, direction="out")
    return APIResponse(data={
        "user_id": user_id,
        "connections": [
            {"id": v.vertex_id, "type": v.vertex_type, "properties": v.properties}
            for v in neighbors
        ],
    }).to_dict()
