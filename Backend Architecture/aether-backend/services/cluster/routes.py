"""Cluster360 API — full cluster intelligence surface.

Routes:
    GET /v1/clusters                         List clusters for a tenant
    GET /v1/clusters/{cluster_id}            Full cluster record (Cluster360 overview)
    GET /v1/clusters/{cluster_id}/members    Paginated member entities
    GET /v1/clusters/{cluster_id}/timeline   Merge/split/growth events
    GET /v1/clusters/{cluster_id}/graph      Cluster subgraph (BFS from cluster vertex)
    GET /v1/clusters/{cluster_id}/economic   Economic summary for cluster members
    GET /v1/clusters/{cluster_id}/campaigns  Campaign attribution summary
    GET /v1/clusters/{cluster_id}/risk       Risk summary and evidence
    GET /v1/clusters/{cluster_id}/geography  Geographic distribution of members
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.graph.graph import EdgeType, GraphClient, Vertex, VertexType
from shared.graph.traversal import GraphTraversalEngine
from shared.logger.logger import get_logger
from dependencies.providers import get_graph

logger = get_logger("aether.service.cluster")
router = APIRouter(prefix="/v1/clusters", tags=["Cluster360"])

# ── Supported cluster vertex types ────────────────────────────────────────────

CLUSTER_VERTEX_TYPES = frozenset({
    VertexType.IDENTITY_CLUSTER,
    VertexType.HOUSEHOLD_CLUSTER,
    VertexType.ORG_CLUSTER,
    VertexType.DEVICE_CLUSTER,
    VertexType.WALLET_CLUSTER,
    VertexType.BEHAVIORAL_CLUSTER,
    VertexType.GEOGRAPHIC_CLUSTER,
    VertexType.ECONOMIC_SEGMENT,
    VertexType.ECONOMIC_CLUSTER,
    VertexType.CAMPAIGN_COHORT,
    VertexType.JOURNEY_CLUSTER,
    VertexType.FRAUD_NETWORK_CLUSTER,
    VertexType.RISK_CLUSTER,
    VertexType.DORMANT_COHORT,
    VertexType.REACTIVATED_COHORT,
    VertexType.UNRESOLVED_CLUSTER,
})

# Member-edge types that link entities to clusters (from entity or to entity)
MEMBER_EDGE_TYPES = frozenset({
    EdgeType.MEMBER_OF_CLUSTER,
    EdgeType.MEMBER_OF,
})


# ── Models ────────────────────────────────────────────────────────────────────

class ClusterMember(BaseModel):
    entity_id: str
    entity_type: str
    label: str
    membership_confidence: float = 1.0
    joined_at: Optional[str] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ClusterTimelineEvent(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClusterRecord(BaseModel):
    cluster_id: str
    cluster_type: str
    label: str
    tenant_id: str
    member_count: int
    formation_reason: Optional[str] = None
    confidence: float = 1.0
    lifecycle_state: str = "active"
    created_at: str
    updated_at: Optional[str] = None
    risk_score: Optional[float] = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ClusterEconomicSummary(BaseModel):
    cluster_id: str
    total_revenue: float = 0.0
    total_spend: float = 0.0
    ltv_estimate: float = 0.0
    transaction_count: int = 0
    currency: str = "USD"
    value_tier: str = "unknown"
    member_economic_summaries: list[dict[str, Any]] = Field(default_factory=list)


class ClusterCampaignSummary(BaseModel):
    cluster_id: str
    attributed_campaigns: list[dict[str, Any]] = Field(default_factory=list)
    total_attributed_revenue: float = 0.0
    top_acquisition_channel: Optional[str] = None
    conversion_rate: Optional[float] = None


class ClusterRiskSummary(BaseModel):
    cluster_id: str
    aggregate_risk_score: float = 0.0
    risk_tier: str = "low"
    fraud_network_id: Optional[str] = None
    fraud_network_type: Optional[str] = None
    alert_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    high_risk_members: list[str] = Field(default_factory=list)


class ClusterGeographySummary(BaseModel):
    cluster_id: str
    country_distribution: dict[str, int] = Field(default_factory=dict)
    region_distribution: dict[str, int] = Field(default_factory=dict)
    primary_country: Optional[str] = None
    geo_concentration_score: float = 0.0


class ClusterPageMeta(BaseModel):
    total: int
    limit: int
    cursor: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cursor_encode(offset: int) -> str:
    return base64.b64encode(json.dumps({"offset": offset}).encode()).decode()


def _cursor_decode(cursor: str) -> int:
    try:
        return json.loads(base64.b64decode(cursor.encode()).decode()).get("offset", 0)
    except Exception:
        return 0


def _require(request: Request, tenant_id: str) -> None:
    tenant = request.state.tenant
    tenant.require_permission("read")
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


def _vertex_to_record(v: Vertex, tenant_id: str, member_count: int = 0) -> ClusterRecord:
    props = v.properties
    raw_risk = props.get("risk_score")
    return ClusterRecord(
        cluster_id=v.vertex_id,
        cluster_type=v.vertex_type,
        label=props.get("label", f"{v.vertex_type} {v.vertex_id[:6]}"),
        tenant_id=tenant_id,
        member_count=member_count or int(props.get("member_count", 0)),
        formation_reason=props.get("formation_reason"),
        confidence=float(props.get("confidence", 1.0)),
        lifecycle_state=props.get("lifecycle_state", "active"),
        created_at=v.created_at,
        updated_at=props.get("updated_at"),
        risk_score=float(raw_risk) if raw_risk is not None else None,
        properties=props,
    )


async def _get_tenant_cluster_vertices(
    tenant_id: str, graph: GraphClient
) -> list[Vertex]:
    """Return all cluster vertices belonging to the tenant."""
    tenant_verts = await graph.get_vertices_for_tenant(tenant_id, limit=5000)
    return [v for v in tenant_verts if v.vertex_type in CLUSTER_VERTEX_TYPES]


async def _get_cluster_vertex(
    cluster_id: str, tenant_id: str, graph: GraphClient
) -> Vertex:
    """Fetch a single cluster vertex; raises appropriate errors."""
    v = await graph.get_vertex(cluster_id)
    if v is None or v.vertex_type not in CLUSTER_VERTEX_TYPES:
        raise NotFoundError(f"Cluster {cluster_id!r} not found")
    if v.properties.get("tenantId") != tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")
    return v


async def _get_cluster_member_vertices(
    cluster_id: str, tenant_id: str, graph: GraphClient
) -> list[Vertex]:
    """Return entity vertices that are members of the cluster."""
    # Edges stored from entity → cluster (MEMBER_OF_CLUSTER direction="out")
    # or from cluster → entity. Check both directions.
    edges = await graph.get_edges(cluster_id, direction="both")
    member_ids: set[str] = set()
    for e in edges:
        if e.edge_type not in MEMBER_EDGE_TYPES:
            continue
        other_id = e.from_vertex_id if e.to_vertex_id == cluster_id else e.to_vertex_id
        member_ids.add(other_id)

    # Also check edges going *from* each potential member to this cluster
    # (handles cases where edges are indexed by entity vertex)
    scoped_verts = await graph.get_vertices_for_tenant(tenant_id, limit=5000)
    tenant_verts = {
        v.vertex_id: v for v in scoped_verts
        if v.vertex_type not in CLUSTER_VERTEX_TYPES
    }

    # Check outbound edges from each entity vertex pointing to this cluster
    for vid, v in tenant_verts.items():
        if vid in member_ids:
            continue
        vert_edges = await graph.get_edges(vid, direction="out")
        for e in vert_edges:
            if e.edge_type in MEMBER_EDGE_TYPES and e.to_vertex_id == cluster_id:
                member_ids.add(vid)
                break

    return [v for vid, v in tenant_verts.items() if vid in member_ids]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
async def list_clusters(
    request: Request,
    tenant_id: str = Query(...),
    cluster_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: Optional[str] = Query(default=None),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)

    clusters = await _get_tenant_cluster_vertices(tenant_id, graph)
    if cluster_type:
        clusters = [v for v in clusters if v.vertex_type == cluster_type]

    total = len(clusters)
    offset = _cursor_decode(cursor) if cursor else 0
    page = clusters[offset: offset + limit]
    next_cursor = _cursor_encode(offset + limit) if offset + limit < total else None

    records = [_vertex_to_record(v, tenant_id).model_dump() for v in page]
    return APIResponse(data={
        "clusters": records,
        "meta": ClusterPageMeta(total=total, limit=limit, cursor=next_cursor).model_dump(),
    }).to_dict()


@router.get("/{cluster_id}")
async def get_cluster(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    v = await _get_cluster_vertex(cluster_id, tenant_id, graph)
    members = await _get_cluster_member_vertices(cluster_id, tenant_id, graph)
    record = _vertex_to_record(v, tenant_id, member_count=len(members))
    return APIResponse(data=record.model_dump()).to_dict()


@router.get("/{cluster_id}/members")
async def get_cluster_members(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: Optional[str] = Query(default=None),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    await _get_cluster_vertex(cluster_id, tenant_id, graph)

    member_verts = await _get_cluster_member_vertices(cluster_id, tenant_id, graph)
    total = len(member_verts)
    offset = _cursor_decode(cursor) if cursor else 0
    page = member_verts[offset: offset + limit]
    next_cursor = _cursor_encode(offset + limit) if offset + limit < total else None

    members = [
        ClusterMember(
            entity_id=v.vertex_id,
            entity_type=v.vertex_type,
            label=v.properties.get("label", v.properties.get("name", v.vertex_id)),
            membership_confidence=float(v.properties.get("membership_confidence", 1.0)),
            joined_at=v.properties.get("joined_at") or v.created_at,
            properties=v.properties,
        ).model_dump()
        for v in page
    ]
    return APIResponse(data={
        "members": members,
        "meta": ClusterPageMeta(total=total, limit=limit, cursor=next_cursor).model_dump(),
    }).to_dict()


@router.get("/{cluster_id}/timeline")
async def get_cluster_timeline(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    v = await _get_cluster_vertex(cluster_id, tenant_id, graph)

    events: list[dict[str, Any]] = []
    raw_events = v.properties.get("timeline_events")
    if isinstance(raw_events, list):
        for ev in raw_events:
            if isinstance(ev, dict):
                events.append(ClusterTimelineEvent(
                    event_id=ev.get("event_id", str(uuid.uuid4())),
                    event_type=ev.get("event_type", "unknown"),
                    timestamp=ev.get("timestamp", v.created_at),
                    description=ev.get("description", ""),
                    metadata=ev.get("metadata", {}),
                ).model_dump())

    if not events:
        events.append(ClusterTimelineEvent(
            event_id=str(uuid.uuid4()),
            event_type="created",
            timestamp=v.created_at,
            description=f"Cluster {v.vertex_type} formed",
            metadata={"formation_reason": v.properties.get("formation_reason", "unknown")},
        ).model_dump())

    return APIResponse(data={"cluster_id": cluster_id, "events": events}).to_dict()


@router.get("/{cluster_id}/graph")
async def get_cluster_graph(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    depth: int = Query(default=1, ge=1, le=3),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    await _get_cluster_vertex(cluster_id, tenant_id, graph)

    engine = GraphTraversalEngine(graph)
    result = await engine.bfs(
        start_id=cluster_id,
        depth=depth,
        tenant_id=tenant_id,
        limit=200,
    )

    cluster_v = await graph.get_vertex(cluster_id)
    root_node = {
        "id": cluster_v.vertex_id,
        "kind": cluster_v.vertex_type.lower(),
        "label": cluster_v.properties.get("label", cluster_v.vertex_id),
        "properties": cluster_v.properties,
    }
    traversed_ids = {v.vertex_id for v in result.nodes}
    nodes = [root_node] + [
        {
            "id": v.vertex_id,
            "kind": v.vertex_type.lower(),
            "label": v.properties.get("label", v.vertex_id),
            "properties": v.properties,
        }
        for v in result.nodes
        if v.vertex_id != cluster_id
    ]
    edges = [
        {
            "id": f"{e.from_vertex_id}-{e.edge_type}-{e.to_vertex_id}",
            "source": e.from_vertex_id,
            "target": e.to_vertex_id,
            "type": e.edge_type,
            "properties": e.properties,
        }
        for e in result.edges
    ]
    return APIResponse(data={
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }).to_dict()


@router.get("/{cluster_id}/economic")
async def get_cluster_economic(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    v = await _get_cluster_vertex(cluster_id, tenant_id, graph)
    members = await _get_cluster_member_vertices(cluster_id, tenant_id, graph)

    total_revenue = 0.0
    total_spend = 0.0
    member_summaries = []
    for m in members:
        rev = float(m.properties.get("revenue", 0) or 0)
        spd = float(m.properties.get("spend", 0) or 0)
        total_revenue += rev
        total_spend += spd
        member_summaries.append({"entity_id": m.vertex_id, "revenue": rev, "spend": spd})

    ltv = float(v.properties.get("ltv_estimate", total_revenue - total_spend))
    transaction_count = int(v.properties.get("transaction_count", 0))
    if ltv >= 10000:
        value_tier = "high"
    elif ltv >= 1000:
        value_tier = "medium"
    else:
        value_tier = "low"

    summary = ClusterEconomicSummary(
        cluster_id=cluster_id,
        total_revenue=total_revenue,
        total_spend=total_spend,
        ltv_estimate=ltv,
        transaction_count=transaction_count,
        currency=v.properties.get("currency", "USD"),
        value_tier=value_tier,
        member_economic_summaries=member_summaries,
    )
    return APIResponse(data=summary.model_dump()).to_dict()


@router.get("/{cluster_id}/campaigns")
async def get_cluster_campaigns(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    v = await _get_cluster_vertex(cluster_id, tenant_id, graph)
    members = await _get_cluster_member_vertices(cluster_id, tenant_id, graph)

    campaign_revenue: dict[str, float] = {}
    channels: list[str] = []
    for m in members:
        props = m.properties
        cam_id = props.get("attributed_campaign_id")
        if cam_id:
            campaign_revenue[cam_id] = (
                campaign_revenue.get(cam_id, 0.0) + float(props.get("revenue", 0) or 0)
            )
        channel = props.get("acquisition_channel")
        if channel:
            channels.append(channel)

    attributed = [
        {"campaign_id": cid, "attributed_revenue": rev}
        for cid, rev in campaign_revenue.items()
    ]
    top_channel = max(set(channels), key=channels.count) if channels else None
    total_attributed = sum(a["attributed_revenue"] for a in attributed)
    raw_rate = v.properties.get("conversion_rate")

    summary = ClusterCampaignSummary(
        cluster_id=cluster_id,
        attributed_campaigns=attributed,
        total_attributed_revenue=total_attributed,
        top_acquisition_channel=top_channel,
        conversion_rate=float(raw_rate) if raw_rate is not None else None,
    )
    return APIResponse(data=summary.model_dump()).to_dict()


@router.get("/{cluster_id}/risk")
async def get_cluster_risk(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    v = await _get_cluster_vertex(cluster_id, tenant_id, graph)
    members = await _get_cluster_member_vertices(cluster_id, tenant_id, graph)

    member_risks = [float(m.properties.get("risk_score", 0) or 0) for m in members]
    cluster_risk = float(v.properties.get("risk_score", 0) or 0)
    agg_risk = max(member_risks + [cluster_risk]) if member_risks else cluster_risk
    high_risk = [m.vertex_id for m in members if float(m.properties.get("risk_score", 0) or 0) >= 0.7]

    if agg_risk >= 0.7:
        risk_tier = "high"
    elif agg_risk >= 0.4:
        risk_tier = "medium"
    else:
        risk_tier = "low"

    evidence_refs = v.properties.get("evidence_refs", [])
    if not isinstance(evidence_refs, list):
        evidence_refs = []

    summary = ClusterRiskSummary(
        cluster_id=cluster_id,
        aggregate_risk_score=agg_risk,
        risk_tier=risk_tier,
        fraud_network_id=v.properties.get("fraud_network_id"),
        fraud_network_type=v.properties.get("fraud_network_type"),
        alert_count=int(v.properties.get("alert_count", 0)),
        evidence_refs=evidence_refs,
        high_risk_members=high_risk,
    )
    return APIResponse(data=summary.model_dump()).to_dict()


@router.get("/{cluster_id}/geography")
async def get_cluster_geography(
    cluster_id: str,
    request: Request,
    tenant_id: str = Query(...),
    graph: GraphClient = Depends(get_graph),
) -> APIResponse:
    _require(request, tenant_id)
    await _get_cluster_vertex(cluster_id, tenant_id, graph)
    members = await _get_cluster_member_vertices(cluster_id, tenant_id, graph)

    country_dist: dict[str, int] = {}
    region_dist: dict[str, int] = {}
    for m in members:
        props = m.properties
        country = props.get("country") or props.get("geo_country")
        region = props.get("region") or props.get("geo_region")
        if country:
            country_dist[country] = country_dist.get(country, 0) + 1
        if region:
            region_dist[region] = region_dist.get(region, 0) + 1

    primary_country = max(country_dist, key=lambda k: country_dist[k]) if country_dist else None
    total = sum(country_dist.values())
    concentration = (country_dist[primary_country] / total) if primary_country and total > 0 else 0.0

    summary = ClusterGeographySummary(
        cluster_id=cluster_id,
        country_distribution=country_dist,
        region_distribution=region_dist,
        primary_country=primary_country,
        geo_concentration_score=concentration,
    )
    return APIResponse(data=summary.model_dump()).to_dict()
