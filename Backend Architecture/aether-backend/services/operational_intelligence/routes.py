"""Operational intelligence graph API — real traversal implementation.

Routes are backed by GraphTraversalEngine, which performs BFS over the
pluggable GraphClient (Neptune in production, in-memory in local dev).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, Request

from dependencies.providers import get_graph
from shared.common.common import APIResponse, ForbiddenError
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.traversal import GraphTraversalEngine, TraversalResult
from shared.logger.logger import metrics
from services.data_quality.service import drift_service, intelligence_quality_service
from services.operational_intelligence.models import (
    ExplainabilityMetadata,
    GraphEdge,
    GraphFilterRequest,
    GraphNode,
    GraphOverlay,
    GraphOverlayRequest,
    GraphQueryFilter,
    GraphResult,
    GraphTraversalRequest,
    ShortestPathRequest,
    TemporalGraphRequest,
)

router = APIRouter(prefix="/v1/graph", tags=["Operational Intelligence / Graph"])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_read(request: Request, tenant_id: str) -> None:
    tenant = request.state.tenant
    tenant.require_permission("read")
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


def _vertex_to_node(v: Vertex) -> GraphNode:
    return GraphNode(
        id=v.vertex_id,
        kind=v.vertex_type.lower(),  # type: ignore[arg-type]
        label=v.properties.get("display_name") or v.properties.get("label"),
        properties={**v.properties, "createdAt": v.created_at},
    )


def _edge_to_graph_edge(e: Edge) -> GraphEdge:
    return GraphEdge(
        id=f"{e.from_vertex_id}:{e.edge_type}:{e.to_vertex_id}",
        type=e.edge_type,
        **{"from": e.from_vertex_id},
        to=e.to_vertex_id,
        directed=True,
        validFrom=e.created_at or None,
        properties=e.properties or None,
    )


def _result_to_graph_result(
    r: TraversalResult,
    *,
    overlays: list[GraphOverlay] | None = None,
) -> GraphResult:
    return GraphResult(
        nodes=[_vertex_to_node(v) for v in r.nodes],
        edges=[_edge_to_graph_edge(e) for e in r.edges],
        overlays=overlays,
    )


def _filter_result(result: TraversalResult, f: GraphQueryFilter) -> TraversalResult:
    """Apply GraphQueryFilter to an in-memory TraversalResult."""
    nodes = list(result.nodes)
    edges = list(result.edges)

    if f.kinds:
        allowed = {k.lower() for k in f.kinds}
        nodes = [n for n in nodes if n.vertex_type.lower() in allowed]
        node_ids = {n.vertex_id for n in nodes}
        edges = [e for e in edges if e.from_vertex_id in node_ids and e.to_vertex_id in node_ids]

    if f.edgeTypes:
        allowed_et = set(f.edgeTypes)
        edges = [e for e in edges if e.edge_type in allowed_et]

    if f.time:
        if f.time.from_:
            edges = [e for e in edges if not e.created_at or e.created_at >= f.time.from_]
        if f.time.to:
            edges = [e for e in edges if not e.created_at or e.created_at <= f.time.to]

    if f.properties:
        filtered: list[Vertex] = []
        for n in nodes:
            if all(str(n.properties.get(k, "")) == str(v) for k, v in f.properties.items()):
                filtered.append(n)
        node_ids = {n.vertex_id for n in filtered}
        edges = [e for e in edges if e.from_vertex_id in node_ids and e.to_vertex_id in node_ids]
        nodes = filtered

    return TraversalResult(nodes=nodes, edges=edges)


def _overlay_stubs(ids: Iterable[str] | None) -> list[GraphOverlay] | None:
    if not ids:
        return None
    return [GraphOverlay(id=oid, name=oid, dimensions=[]) for oid in ids]


# Maps overlay name → the IntelligenceDimensions it annotates
_OVERLAY_DIMENSIONS: dict[str, list] = {
    "contamination":  ["relationship", "operational"],
    "identity":       ["demographic", "device", "wallet"],
    "graph":          ["relationship", "coordination", "attribution"],
    "trust":          ["behavioral", "temporal", "coordination"],
    "risk":           ["behavioral", "economic", "chain"],
    "attribution":    ["attribution", "governance"],
    "agent":          ["agent", "operational"],
    "wallet":         ["wallet", "chain", "economic"],
}

# Maps overlay name → the data-quality route key for score lookup
_OVERLAY_SCORE_KEY: dict[str, str] = {
    "contamination":  "graph",
    "identity":       "identity",
    "graph":          "graph",
    "trust":          "events",
    "risk":           "events",
    "attribution":    "schema",
    "agent":          "graph",
    "wallet":         "identity",
}


async def _build_overlays(overlay_ids: list[str], tenant_id: str) -> list[GraphOverlay]:
    """Return GraphOverlay objects with real quality-score dimensions."""
    result = []
    for oid in overlay_ids:
        dims = _OVERLAY_DIMENSIONS.get(oid, ["operational"])
        score_key = _OVERLAY_SCORE_KEY.get(oid, "graph")
        report = intelligence_quality_service.dimension_report(score_key, tenant_id)
        score_value = report.get("quality_score", 0.8)
        overlay = GraphOverlay(
            id=oid,
            name=oid.replace("_", " ").title(),
            dimensions=dims,  # type: ignore[arg-type]
            nodeFilter=None,
            edgeFilter=None,
        )
        # Embed score metadata as extra attributes on the overlay via model extras
        result.append(overlay)
        # Store score in a side-channel dict attached to the overlay object so
        # callers can inspect it; GraphOverlay doesn't have a scores field.
        overlay.__dict__["_score"] = score_value
    return result


@router.post("/traverse", response_model=GraphResult)
async def traverse_graph(
    body: GraphTraversalRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphResult:
    """Bounded neighbourhood BFS traversal from a start entity."""
    _require_read(request, body.tenantId)
    metrics.increment("graph_traverse")

    engine = GraphTraversalEngine(graph)
    edge_types = body.filter.edgeTypes if body.filter else None
    result = await engine.bfs(
        start_id=body.start.id,
        depth=body.depth,
        direction=body.direction or "both",
        edge_types=edge_types,
        limit=body.limit,
    )

    if body.filter:
        result = _filter_result(result, body.filter)

    start_vertex = await graph.get_vertex(body.start.id)
    start_node = _vertex_to_node(start_vertex) if start_vertex else GraphNode(
        id=body.start.id, kind=body.start.kind, label=body.start.label,
        properties={"tenantId": body.tenantId, "role": "start", "contractStage": "skeleton"},
    )
    if start_node.properties is not None and "contractStage" not in start_node.properties:
        start_node.properties["contractStage"] = "skeleton"
    seen_ids = {start_node.id}
    extra_nodes = [_vertex_to_node(v) for v in result.nodes if v.vertex_id not in seen_ids]

    overlays = await _build_overlays(body.overlays, body.tenantId) if body.overlays else None

    return GraphResult(
        nodes=[start_node] + extra_nodes,
        edges=[_edge_to_graph_edge(e) for e in result.edges],
        overlays=overlays,
        explainability=ExplainabilityMetadata(
            summary="Graph traversal: live data returned when graph is populated",
        ),
    )


@router.post("/path", response_model=GraphResult)
async def shortest_path(
    body: ShortestPathRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphResult:
    """BFS shortest path between two entities."""
    _require_read(request, body.tenantId)
    metrics.increment("graph_path")

    engine = GraphTraversalEngine(graph)
    result = await engine.shortest_path(
        from_id=body.from_.id,
        to_id=body.to.id,
        max_depth=body.maxDepth,
    )

    if not result.nodes:
        from_v = await graph.get_vertex(body.from_.id)
        to_v = await graph.get_vertex(body.to.id)
        anchors = []
        if from_v:
            anchors.append(_vertex_to_node(from_v))
        else:
            anchors.append(GraphNode(id=body.from_.id, kind=body.from_.kind, label=body.from_.label, properties={"role": "from"}))
        if to_v:
            anchors.append(_vertex_to_node(to_v))
        else:
            anchors.append(GraphNode(id=body.to.id, kind=body.to.kind, label=body.to.label, properties={"role": "to"}))
        return GraphResult(nodes=anchors, edges=[])

    return _result_to_graph_result(result)


@router.post("/temporal", response_model=GraphResult)
async def temporal_graph(
    body: TemporalGraphRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphResult:
    """Temporal graph reconstruction restricted to edges/vertices created at or before asOf."""
    _require_read(request, body.tenantId)
    metrics.increment("graph_temporal")

    engine = GraphTraversalEngine(graph)
    result = await engine.temporal_bfs(
        start_id=body.anchor.id,
        as_of=body.asOf,
        depth=body.depth,
        direction="both",
        limit=100,
    )

    anchor_v = await graph.get_vertex(body.anchor.id)
    anchor_node = _vertex_to_node(anchor_v) if anchor_v else GraphNode(
        id=body.anchor.id, kind=body.anchor.kind, label=body.anchor.label,
        properties={"tenantId": body.tenantId, "asOf": body.asOf},
    )
    seen_ids = {anchor_node.id}
    extra_nodes = [_vertex_to_node(v) for v in result.nodes if v.vertex_id not in seen_ids]

    return GraphResult(
        nodes=[anchor_node] + extra_nodes,
        edges=[_edge_to_graph_edge(e) for e in result.edges],
    )


@router.post("/overlay", response_model=GraphResult)
async def graph_overlay(
    body: GraphOverlayRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphResult:
    """Apply overlay metadata (risk/trust/attribution) to a graph view."""
    _require_read(request, body.tenantId)
    metrics.increment("graph_overlay")

    all_verts = await graph.get_all_vertices(limit=body.limit)
    result = TraversalResult(nodes=all_verts, edges=[])
    if body.graph:
        result = _filter_result(result, body.graph)

    overlays = await _build_overlays(body.overlays, body.tenantId) if body.overlays else None

    # Compute overall graph quality score and active contamination events for explainability.
    graph_report = intelligence_quality_service.dimension_report("graph", body.tenantId)
    graph_score = graph_report.get("quality_score", 0.0)
    open_drift = await drift_service.list(tenant_id=body.tenantId, status="open")
    contamination_events = [d for d in open_drift if d.get("drift_type") == "tenant_data_contamination"]

    summary = (
        f"Graph quality score: {graph_score:.3f} | "
        f"Open drift events: {len(open_drift)} | "
        f"Open contamination events: {len(contamination_events)}"
    )

    return GraphResult(
        nodes=[_vertex_to_node(v) for v in result.nodes],
        edges=[],
        overlays=overlays,
        explainability=ExplainabilityMetadata(
            summary=summary,
            features={
                "graph_quality_score": graph_score,
                "open_drift_count": float(len(open_drift)),
                "contamination_count": float(len(contamination_events)),
            },
        ),
    )


@router.post("/filter", response_model=GraphResult)
async def graph_filter(
    body: GraphFilterRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphResult:
    """Filter graph nodes/edges by kind, edge type, time range, or properties."""
    _require_read(request, body.tenantId)
    metrics.increment("graph_filter")

    all_verts = await graph.get_all_vertices(limit=body.limit)
    all_edges: list = []
    for v in all_verts:
        all_edges.extend(await graph.get_edges(v.vertex_id, direction="out"))

    result = _filter_result(TraversalResult(nodes=all_verts, edges=all_edges), body.filter)
    return GraphResult(
        nodes=[_vertex_to_node(v) for v in result.nodes],
        edges=[_edge_to_graph_edge(e) for e in result.edges],
    )


@router.get("/contracts")
async def graph_contracts() -> dict:
    """Expose the active graph contract route family for diagnostics."""
    return APIResponse(
        data={
            "version": "v1",
            "routes": ["traverse", "path", "temporal", "overlay", "filter"],
            "status": "traversal_engine_active",
        }
    ).to_dict()
