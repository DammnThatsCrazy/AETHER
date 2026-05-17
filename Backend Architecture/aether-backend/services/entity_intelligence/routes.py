"""Entity intelligence routes — profile dimensions, timeline, and relationship queries.

Extends the existing /v1/entities/* CRUD surface with intelligence query endpoints:
    POST /v1/entities/profile            Entity profile with requested dimensions
    POST /v1/entities/timeline/query     Cursor-based entity timeline
    POST /v1/entities/relationships/query Scored relationship edges

These routes compose graph traversal, lake data, and scoring to return typed
responses matching the packages/shared/operational-intelligence.ts contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from dependencies.providers import get_graph
from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.graph.graph import GraphClient
from shared.graph.traversal import GraphTraversalEngine
from shared.logger.logger import get_logger, metrics
from services.operational_intelligence.models import (
    EntityRef,
    GraphEdge,
    GraphNode,
    IntelligenceDimension,
    IntelligenceScore,
    OperationalEntityKind,
    PageInfo,
    PageRequest,
    TenantScopedRequest,
)

logger = get_logger("aether.service.entity_intelligence")

router = APIRouter(prefix="/v1/entities", tags=["Entity Intelligence"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_read(request: Request, tenant_id: str) -> None:
    tenant = request.state.tenant
    tenant.require_permission("read")
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


# ── Request / Response models ─────────────────────────────────────────────────

class EntityProfileRequest(TenantScopedRequest):
    entity: EntityRef
    dimensions: Optional[list[IntelligenceDimension]] = None
    consistency: Optional[str] = "cache"


class EntityProfileResponse(BaseModel):
    entity: EntityRef
    kind: OperationalEntityKind
    displayName: Optional[str] = None
    dimensions: dict[str, Any] = Field(default_factory=dict)
    scores: list[IntelligenceScore] = Field(default_factory=list)
    updatedAt: str


class TimelineQuery(TenantScopedRequest, PageRequest):
    entity: EntityRef
    fromTime: Optional[str] = None
    toTime: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)


class TimelineItem(BaseModel):
    eventId: str
    eventType: str
    occurredAt: str
    relatedEntities: list[EntityRef] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)


class TimelineResponse(BaseModel):
    entity: EntityRef
    items: list[TimelineItem]
    page: PageInfo


class RelationshipsQuery(TenantScopedRequest, PageRequest):
    entity: EntityRef
    relationshipTypes: Optional[list[str]] = None
    minScore: Optional[float] = None
    depth: int = Field(default=1, ge=1, le=5)
    limit: int = Field(default=50, ge=1, le=200)


class ScoredRelationship(BaseModel):
    from_entity: EntityRef = Field(alias="from")
    to_entity: EntityRef = Field(alias="to")
    type: str
    score: Optional[float] = None
    properties: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class RelationshipsResponse(BaseModel):
    entity: EntityRef
    relationships: list[ScoredRelationship]
    page: PageInfo


# ── Helpers ───────────────────────────────────────────────────────────────────

def _node_to_entity_ref(node_id: str, vertex_type: str, props: dict) -> EntityRef:
    return EntityRef(
        kind=vertex_type.lower(),  # type: ignore[arg-type]
        id=node_id,
        label=props.get("display_name") or props.get("label"),
    )


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/profile", response_model=EntityProfileResponse)
async def entity_profile(
    body: EntityProfileRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> EntityProfileResponse:
    """
    Retrieve an entity profile with requested intelligence dimensions.

    Returns graph-sourced dimension data (device, behavioral, relationship,
    wallet, geographic etc.) and composite scores. Dimensions not yet
    implemented return empty dicts; all requested dimension keys are present.
    """
    _require_read(request, body.tenantId)
    metrics.increment("entity_profile_read")

    vertex = await graph.get_vertex(body.entity.id)
    if vertex is None:
        raise NotFoundError(f"Entity {body.entity.id!r} not found")

    requested_dims = body.dimensions or []
    dimensions: dict[str, Any] = {}

    # Relationship dimension — 1-hop neighbours summary
    if not requested_dims or "relationship" in requested_dims:
        edges = await graph.get_edges(body.entity.id, direction="both")
        in_count = sum(1 for e in edges if e.to_vertex_id == body.entity.id)
        out_count = sum(1 for e in edges if e.from_vertex_id == body.entity.id)
        edge_type_counts: dict[str, int] = {}
        for e in edges:
            edge_type_counts[e.edge_type] = edge_type_counts.get(e.edge_type, 0) + 1
        dimensions["relationship"] = {
            "inbound_count": in_count,
            "outbound_count": out_count,
            "total_edges": len(edges),
            "edge_type_distribution": edge_type_counts,
        }

    # Behavioural dimension — placeholder from vertex properties
    if not requested_dims or "behavioral" in requested_dims:
        dimensions["behavioral"] = {
            k: v for k, v in vertex.properties.items()
            if k in ("session_count", "event_count", "last_active", "activity_score")
        }

    # All other requested dimensions — return structured placeholder
    for dim in requested_dims:
        if dim not in dimensions:
            dimensions[dim] = {}

    # Trust/risk composite from stored vertex properties
    scores: list[IntelligenceScore] = []
    for score_kind in ("trust", "risk", "anomaly", "confidence"):
        raw = vertex.properties.get(f"{score_kind}_score")
        if raw is not None:
            scores.append(IntelligenceScore(
                kind=score_kind,  # type: ignore[arg-type]
                value=float(raw),
                computedAt=vertex.created_at or _utc_now(),
            ))

    return EntityProfileResponse(
        entity=body.entity,
        kind=vertex.vertex_type.lower(),  # type: ignore[arg-type]
        displayName=vertex.properties.get("display_name") or vertex.properties.get("name"),
        dimensions=dimensions,
        scores=scores,
        updatedAt=vertex.created_at or _utc_now(),
    )


@router.post("/timeline/query", response_model=TimelineResponse)
async def entity_timeline(
    body: TimelineQuery,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> TimelineResponse:
    """
    Cursor-based entity timeline — events linked to the entity via graph edges.

    Returns TRIGGERED_EVENT, HAS_SESSION, and ACTION_RECORD edges in reverse
    chronological order, optionally bounded by fromTime/toTime.
    """
    _require_read(request, body.tenantId)
    metrics.increment("entity_timeline_query")

    event_edge_types = {"TRIGGERED_EVENT", "HAS_SESSION", "PERFORMED_ACTION", "ACTION_RECORD"}
    edges = await graph.get_edges(body.entity.id, direction="out")
    edges = [e for e in edges if e.edge_type in event_edge_types]

    if body.fromTime:
        edges = [e for e in edges if not e.created_at or e.created_at >= body.fromTime]
    if body.toTime:
        edges = [e for e in edges if not e.created_at or e.created_at <= body.toTime]

    edges.sort(key=lambda e: e.created_at or "", reverse=True)
    page_edges = edges[:body.limit]

    items: list[TimelineItem] = []
    for edge in page_edges:
        target_vertex = await graph.get_vertex(edge.to_vertex_id)
        items.append(TimelineItem(
            eventId=edge.to_vertex_id,
            eventType=edge.edge_type,
            occurredAt=edge.created_at or _utc_now(),
            relatedEntities=[
                _node_to_entity_ref(
                    edge.to_vertex_id,
                    target_vertex.vertex_type if target_vertex else "event",
                    target_vertex.properties if target_vertex else {},
                )
            ],
            properties=edge.properties or {},
        ))

    has_more = len(edges) > body.limit
    return TimelineResponse(
        entity=body.entity,
        items=items,
        page=PageInfo(
            hasNextPage=has_more,
            hasPreviousPage=False,
            totalEstimate=len(edges),
        ),
    )


@router.post("/relationships/query", response_model=RelationshipsResponse)
async def entity_relationships(
    body: RelationshipsQuery,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> RelationshipsResponse:
    """
    Query scored relationship edges for an entity.

    Returns both inbound and outbound edges up to the requested depth, optionally
    filtered by relationship type and minimum score. Scores are sourced from edge
    properties (relationship_score) when present; edges without scores are included
    unless minScore is specified.
    """
    _require_read(request, body.tenantId)
    metrics.increment("entity_relationships_query")

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(
        start_id=body.entity.id,
        depth=body.depth,
        direction="both",
        edge_types=body.relationshipTypes,
        limit=body.limit,
    )

    relationships: list[ScoredRelationship] = []
    for edge in result.edges:
        score_raw = edge.properties.get("relationship_score") if edge.properties else None
        score = float(score_raw) if score_raw is not None else None

        if body.minScore is not None and (score is None or score < body.minScore):
            continue

        from_v = await graph.get_vertex(edge.from_vertex_id)
        to_v = await graph.get_vertex(edge.to_vertex_id)

        from_ref = _node_to_entity_ref(
            edge.from_vertex_id,
            from_v.vertex_type if from_v else "unknown",
            from_v.properties if from_v else {},
        )
        to_ref = _node_to_entity_ref(
            edge.to_vertex_id,
            to_v.vertex_type if to_v else "unknown",
            to_v.properties if to_v else {},
        )

        relationships.append(ScoredRelationship(
            **{"from": from_ref},
            to=to_ref,
            type=edge.edge_type,
            score=score,
            properties=edge.properties or {},
        ))

    return RelationshipsResponse(
        entity=body.entity,
        relationships=relationships,
        page=PageInfo(
            hasNextPage=False,
            hasPreviousPage=False,
            totalEstimate=len(relationships),
        ),
    )
