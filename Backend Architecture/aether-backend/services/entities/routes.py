"""
Aether Service — Entities (Profile 360)

First-class multi-entity identity for the Profile 360 system. Models humans,
agents, organizations, and system actors as a unified Entity, with identity
clusters that support multiple identifiers per entity.

This service is purely additive — existing /v1/identity/* endpoints continue
to operate unchanged on the IdentityRepository (user-centric profiles).

Endpoints:
    POST   /v1/entities                              Create entity
    GET    /v1/entities                              List tenant entities
    GET    /v1/entities/{entity_id}                  Read entity
    PATCH  /v1/entities/{entity_id}                  Update entity metadata
    POST   /v1/entities/{entity_id}/identifiers      Link identifier
    DELETE /v1/entities/{entity_id}/identifiers/{cluster_id}  Unlink identifier
    GET    /v1/entities/{entity_id}/identifiers      List identifiers
    POST   /v1/entities/{entity_id}/membership       Add organization membership
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_graph, get_producer
from repositories.repos import EntityRepository, IdentityClusterRepository

logger = get_logger("aether.service.entities")
router = APIRouter(prefix="/v1/entities", tags=["Profile 360 / Entities"])

_entities = EntityRepository()
_identifiers = IdentityClusterRepository()


# ── Request models ─────────────────────────────────────────────────────

class EntityCreate(BaseModel):
    entity_id: str = ""
    entity_type: str = Field(..., pattern="^(human|agent|organization|system)$")
    display_name: str = ""
    parent_entity_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityUpdate(BaseModel):
    display_name: Optional[str] = None
    parent_entity_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class IdentifierLink(BaseModel):
    identifier_type: str = Field(..., min_length=1, max_length=64)
    identifier_value: str = Field(..., min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MembershipAdd(BaseModel):
    organization_entity_id: str
    role: str = "member"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ──────────────────────────────────────────────────────────

@router.post("")
async def create_entity(
    body: EntityCreate,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    """Create a new entity (human, agent, organization, or system)."""
    tenant = request.state.tenant
    tenant.require_permission("write")

    entity_id = body.entity_id or str(uuid.uuid4())
    record = await _entities.create_entity(
        entity_id=entity_id,
        tenant_id=tenant.tenant_id,
        entity_type=body.entity_type,
        display_name=body.display_name,
        parent_entity_id=body.parent_entity_id,
        metadata=body.metadata,
    )

    # Project to graph as a typed vertex.
    vertex_type = {
        "organization": VertexType.ORGANIZATION,
        "agent": VertexType.AGENT,
    }.get(body.entity_type, VertexType.ENTITY)
    await graph.upsert_vertex(Vertex(
        vertex_type=vertex_type,
        vertex_id=entity_id,
        properties={
            "tenant_id": tenant.tenant_id,
            "entity_type": body.entity_type,
            "display_name": body.display_name,
        },
    ))

    if body.parent_entity_id:
        await graph.add_edge(Edge(
            edge_type=EdgeType.MEMBER_OF,
            from_vertex_id=entity_id,
            to_vertex_id=body.parent_entity_id,
            properties={"tenant_id": tenant.tenant_id, "role": "child"},
        ))

    await producer.publish(Event(
        topic=Topic.ENTITY_CREATED,
        tenant_id=tenant.tenant_id,
        source_service="entities",
        payload={"entity_id": entity_id, "entity_type": body.entity_type},
    ))
    metrics.increment("entity_created", labels={"type": body.entity_type})
    return APIResponse(data=record).to_dict()


@router.get("")
async def list_entities(
    request: Request,
    entity_type: Optional[str] = None,
    limit: int = 100,
):
    """List entities for the calling tenant."""
    tenant = request.state.tenant
    tenant.require_permission("read")
    rows = await _entities.list_by_tenant(
        tenant.tenant_id, entity_type=entity_type, limit=min(limit, 500),
    )
    return APIResponse(data={"entities": rows, "count": len(rows)}).to_dict()


@router.get("/{entity_id}")
async def get_entity(entity_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    record = await _entities.find_by_id(entity_id)
    if record is None or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Entity")
    return APIResponse(data=record).to_dict()


@router.patch("/{entity_id}")
async def update_entity(
    entity_id: str,
    body: EntityUpdate,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    existing = await _entities.find_by_id(entity_id)
    if existing is None or existing.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Entity")
    patch = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    updated = await _entities.update(entity_id, patch)
    await producer.publish(Event(
        topic=Topic.ENTITY_UPDATED,
        tenant_id=tenant.tenant_id,
        source_service="entities",
        payload={"entity_id": entity_id, "fields": list(patch.keys())},
    ))
    return APIResponse(data=updated).to_dict()


@router.post("/{entity_id}/identifiers")
async def link_identifier(
    entity_id: str,
    body: IdentifierLink,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    """Attach an identifier (wallet, email, device, etc.) to an entity."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    entity = await _entities.find_by_id(entity_id)
    if entity is None or entity.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Entity")

    cluster_id = str(uuid.uuid4())
    record = await _identifiers.link(
        cluster_id=cluster_id,
        entity_id=entity_id,
        tenant_id=tenant.tenant_id,
        identifier_type=body.identifier_type,
        identifier_value=body.identifier_value,
        confidence=body.confidence,
        provenance=body.provenance,
    )
    await producer.publish(Event(
        topic=Topic.ENTITY_IDENTIFIER_LINKED,
        tenant_id=tenant.tenant_id,
        source_service="entities",
        payload={
            "entity_id": entity_id,
            "cluster_id": cluster_id,
            "identifier_type": body.identifier_type,
        },
    ))
    metrics.increment("entity_identifier_linked", labels={"type": body.identifier_type})
    return APIResponse(data=record).to_dict()


@router.delete("/{entity_id}/identifiers/{cluster_id}")
async def unlink_identifier(
    entity_id: str,
    cluster_id: str,
    request: Request,
    producer: EventProducer = Depends(get_producer),
):
    tenant = request.state.tenant
    tenant.require_permission("write")
    record = await _identifiers.find_by_id(cluster_id)
    if record is None or record.get("entity_id") != entity_id \
            or record.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Identifier cluster")
    await _identifiers.unlink(cluster_id)
    await producer.publish(Event(
        topic=Topic.ENTITY_IDENTIFIER_UNLINKED,
        tenant_id=tenant.tenant_id,
        source_service="entities",
        payload={"entity_id": entity_id, "cluster_id": cluster_id},
    ))
    return APIResponse(data={"entity_id": entity_id, "cluster_id": cluster_id, "unlinked": True}).to_dict()


@router.get("/{entity_id}/identifiers")
async def list_identifiers(entity_id: str, request: Request):
    tenant = request.state.tenant
    tenant.require_permission("read")
    entity = await _entities.find_by_id(entity_id)
    if entity is None or entity.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Entity")
    rows = await _identifiers.list_for_entity(entity_id)
    return APIResponse(data={"entity_id": entity_id, "identifiers": rows, "count": len(rows)}).to_dict()


@router.post("/{entity_id}/membership")
async def add_membership(
    entity_id: str,
    body: MembershipAdd,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
):
    """Record that an entity is a MEMBER_OF an organization entity."""
    tenant = request.state.tenant
    tenant.require_permission("write")
    entity = await _entities.find_by_id(entity_id)
    org = await _entities.find_by_id(body.organization_entity_id)
    if entity is None or org is None or entity.get("tenant_id") != tenant.tenant_id \
            or org.get("tenant_id") != tenant.tenant_id:
        raise NotFoundError("Entity or organization")
    if org.get("entity_type") != "organization":
        raise BadRequestError("Target entity must be of type 'organization'")

    await graph.add_edge(Edge(
        edge_type=EdgeType.MEMBER_OF,
        from_vertex_id=entity_id,
        to_vertex_id=body.organization_entity_id,
        properties={
            "tenant_id": tenant.tenant_id,
            "role": body.role,
            **body.metadata,
        },
    ))
    await producer.publish(Event(
        topic=Topic.ENTITY_MEMBERSHIP_ADDED,
        tenant_id=tenant.tenant_id,
        source_service="entities",
        payload={
            "entity_id": entity_id,
            "organization_entity_id": body.organization_entity_id,
            "role": body.role,
        },
    ))
    return APIResponse(data={
        "entity_id": entity_id,
        "organization_entity_id": body.organization_entity_id,
        "role": body.role,
    }).to_dict()
