"""Operational intelligence graph API — real traversal implementation.

Routes are backed by GraphTraversalEngine, which performs BFS over the
pluggable GraphClient (Neptune in production, in-memory in local dev).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, Query, Request

from dependencies.providers import get_graph
from shared.common.common import APIResponse, ForbiddenError
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type, get_layer_stats
from shared.graph.traversal import GraphTraversalEngine, TraversalResult
from shared.logger.logger import metrics
from services.data_quality.service import drift_service, intelligence_quality_service
from services.operational_intelligence.models import (
    ExplainabilityMetadata,
    GraphCompareNodeDiff,
    GraphCompareEdgeDiff,
    GraphCompareRequest,
    GraphCompareResult,
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

_GRAPH_CONTRACT_VERSION = "v1"
_RELATIONSHIP_LAYERS = ["H2H", "H2A", "A2H", "A2A"]


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


def _compute_overlay_scores(
    nodes: list[Vertex],
    edges: list[Edge],
    requested_overlays: list[str] | None,
) -> list[GraphOverlay] | None:
    """Compute deterministic overlay scores from graph data.

    Returns None if no overlays requested. Returns structured overlays with
    real counts; returns status=no_data when the graph has no records.
    """
    if not requested_overlays:
        return None

    layer_counts = get_layer_stats(edges)
    total_edges = sum(layer_counts.values())
    total_nodes = len(nodes)

    overlays: list[GraphOverlay] = []
    for overlay_id in requested_overlays:
        if total_edges == 0 and total_nodes == 0:
            overlays.append(GraphOverlay(
                id=overlay_id,
                name=overlay_id,
                dimensions=[],
                properties={
                    "status": "no_data",
                    "reason": "no graph records found for tenant/time window",
                },
            ))
        elif overlay_id in ("risk", "trust", "attribution", "layer_coverage"):
            classified_edges = sum(layer_counts.values())
            layer_pct = {
                layer: round(count / total_edges * 100, 1) if total_edges > 0 else 0.0
                for layer, count in layer_counts.items()
            }
            overlays.append(GraphOverlay(
                id=overlay_id,
                name=overlay_id,
                dimensions=[],
                properties={
                    "status": "computed",
                    "node_count": total_nodes,
                    "edge_count": total_edges,
                    "classified_edge_count": classified_edges,
                    "layer_counts": layer_counts,
                    "layer_distribution_pct": layer_pct,
                    "layers_present": [l for l, c in layer_counts.items() if c > 0],
                    "computed_at": _utc_now(),
                },
            ))
        else:
            overlays.append(GraphOverlay(
                id=overlay_id,
                name=overlay_id,
                dimensions=[],
                properties={
                    "status": "computed",
                    "node_count": total_nodes,
                    "edge_count": total_edges,
                    "computed_at": _utc_now(),
                },
            ))

    return overlays or None


# Maps overlay name → IntelligenceDimensions it annotates
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

# Maps overlay name → data-quality route key for score lookup
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


async def _build_overlays(
    overlay_ids: list[str], tenant_id: str
) -> tuple[list[GraphOverlay], dict[str, float]]:
    """Return (GraphOverlay list, {overlay_id: score}) with real quality scores.

    Scores are returned separately and surfaced in ExplainabilityMetadata.features
    so they survive Pydantic serialization (GraphOverlay has no scores field).
    """
    overlays = []
    scores: dict[str, float] = {}
    for oid in overlay_ids:
        dims = _OVERLAY_DIMENSIONS.get(oid, ["operational"])
        score_key = _OVERLAY_SCORE_KEY.get(oid, "graph")
        report = intelligence_quality_service.dimension_report(score_key, tenant_id)
        score_value = float(report.get("quality_score", 0.8))
        scores[oid] = score_value
        overlays.append(GraphOverlay(
            id=oid,
            name=oid.replace("_", " ").title(),
            dimensions=dims,  # type: ignore[arg-type]
        ))
    return overlays, scores


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
        tenant_id=body.tenantId,
    )

    if body.filter:
        result = _filter_result(result, body.filter)

    start_vertex = await graph.get_vertex(body.start.id)
    if start_vertex:
        start_node = _vertex_to_node(start_vertex)
    else:
        start_node = GraphNode(
            id=body.start.id, kind=body.start.kind, label=body.start.label,
            properties={"tenantId": body.tenantId, "role": "start"},
        )
    seen_ids = {start_node.id}
    extra_nodes = [_vertex_to_node(v) for v in result.nodes if v.vertex_id not in seen_ids]

    layer_counts = get_layer_stats(result.edges)
    node_count = 1 + len(extra_nodes)
    edge_count = len(result.edges)

    overlays = _compute_overlay_scores(result.nodes, result.edges, body.overlays)

    return GraphResult(
        nodes=[start_node] + extra_nodes,
        edges=[_edge_to_graph_edge(e) for e in result.edges],
        overlays=overlays,
        explainability=ExplainabilityMetadata(
            summary=(
                f"Traversal complete: {node_count} nodes, {edge_count} edges across "
                f"layers H2H={layer_counts['H2H']} H2A={layer_counts['H2A']} "
                f"A2H={layer_counts['A2H']} A2A={layer_counts['A2A']}"
            ),
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
        tenant_id=body.tenantId,
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
        tenant_id=body.tenantId,
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


@router.post("/compare", response_model=GraphCompareResult)
async def graph_compare(
    body: GraphCompareRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphCompareResult:
    """Compare graph state at two points in time using bitemporal valid-time windows.

    Returns nodes/edges that were added or removed between compareTo (baseline)
    and asOf (target). Both snapshots use valid-time filtering so superseded
    facts at the baseline are excluded even if they share the same vertex ID.
    """
    _require_read(request, body.tenantId)
    metrics.increment("graph_compare")

    engine = GraphTraversalEngine(graph)

    # Fetch the two temporal snapshots in parallel would require asyncio.gather;
    # sequential is safe here since both are read-only BFS over in-memory graph.
    result_at = await engine.temporal_bfs(
        start_id=body.anchor.id,
        as_of=body.asOf,
        depth=body.depth,
        direction="both",
        limit=500,
        tenant_id=body.tenantId,
    )
    result_base = await engine.temporal_bfs(
        start_id=body.anchor.id,
        as_of=body.compareTo,
        depth=body.depth,
        direction="both",
        limit=500,
        tenant_id=body.tenantId,
    )

    if body.filter:
        result_at = _filter_result(result_at, body.filter)
        result_base = _filter_result(result_base, body.filter)

    nodes_at = {v.vertex_id: v for v in result_at.nodes}
    nodes_base = {v.vertex_id: v for v in result_base.nodes}

    def _edge_id(e: Edge) -> str:
        return f"{e.from_vertex_id}:{e.edge_type}:{e.to_vertex_id}"

    edges_at = {_edge_id(e): e for e in result_at.edges}
    edges_base = {_edge_id(e): e for e in result_base.edges}

    added_nodes: list[GraphCompareNodeDiff] = []
    removed_nodes: list[GraphCompareNodeDiff] = []
    changed_nodes: list[GraphCompareNodeDiff] = []
    unchanged_nodes = 0

    for vid, v in nodes_at.items():
        if vid not in nodes_base:
            added_nodes.append(GraphCompareNodeDiff(
                id=vid, kind=v.vertex_type.lower(),
                label=v.properties.get("display_name") or v.properties.get("label"),
                changeType="added",
            ))
        else:
            base_v = nodes_base[vid]
            changed_props = {
                k: v.properties[k]
                for k in v.properties
                if k not in ("valid_from", "valid_to", "recorded_at", "superseded_at")
                and str(v.properties.get(k)) != str(base_v.properties.get(k))
            }
            if changed_props:
                changed_nodes.append(GraphCompareNodeDiff(
                    id=vid, kind=v.vertex_type.lower(),
                    label=v.properties.get("display_name") or v.properties.get("label"),
                    changeType="changed",
                    changedProperties=changed_props,
                ))
            else:
                unchanged_nodes += 1

    for vid, v in nodes_base.items():
        if vid not in nodes_at:
            removed_nodes.append(GraphCompareNodeDiff(
                id=vid, kind=v.vertex_type.lower(),
                label=v.properties.get("display_name") or v.properties.get("label"),
                changeType="removed",
            ))

    added_edges: list[GraphCompareEdgeDiff] = []
    removed_edges: list[GraphCompareEdgeDiff] = []
    unchanged_edges = 0

    for eid, e in edges_at.items():
        if eid not in edges_base:
            added_edges.append(GraphCompareEdgeDiff(
                id=eid, type=e.edge_type,
                **{"from": e.from_vertex_id},
                to=e.to_vertex_id,
                changeType="added",
            ))
        else:
            unchanged_edges += 1

    for eid, e in edges_base.items():
        if eid not in edges_at:
            removed_edges.append(GraphCompareEdgeDiff(
                id=eid, type=e.edge_type,
                **{"from": e.from_vertex_id},
                to=e.to_vertex_id,
                changeType="removed",
            ))

    return GraphCompareResult(
        tenantId=body.tenantId,
        anchor=body.anchor,
        asOf=body.asOf,
        compareTo=body.compareTo,
        addedNodes=added_nodes,
        removedNodes=removed_nodes,
        changedNodes=changed_nodes,
        addedEdges=added_edges,
        removedEdges=removed_edges,
        unchangedNodeCount=unchanged_nodes,
        unchangedEdgeCount=unchanged_edges,
        computedAt=_utc_now(),
    )


@router.post("/overlay", response_model=GraphResult)
async def graph_overlay(
    body: GraphOverlayRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphResult:
    """Apply overlay scores (layer coverage, risk, trust) to a graph view.

    Scores are computed from real graph data. Returns status=no_data when
    the tenant graph has no records.
    """
    _require_read(request, body.tenantId)
    metrics.increment("graph_overlay")

    all_verts = await graph.get_all_vertices(limit=body.limit)
    all_verts = [v for v in all_verts if v.properties.get("tenantId") == body.tenantId]
    all_edges: list[Edge] = []
    for v in all_verts:
        all_edges.extend(await graph.get_edges(v.vertex_id, direction="out"))

    result = TraversalResult(nodes=all_verts, edges=all_edges)
    if body.graph:
        result = _filter_result(result, body.graph)

    overlays = None
    overlay_scores: dict[str, float] = {}
    if body.overlays:
        overlays, overlay_scores = await _build_overlays(body.overlays, body.tenantId)

    # Augment overlay_scores with graph-level quality + contamination metrics
    graph_report = intelligence_quality_service.dimension_report("graph", body.tenantId)
    graph_score = float(graph_report.get("quality_score", 0.0))
    open_drift = await drift_service.list(tenant_id=body.tenantId, status="open")
    contamination_count = sum(
        1 for d in open_drift if d.get("drift_type") == "tenant_data_contamination"
    )
    features = {
        **overlay_scores,
        "graph_quality_score": graph_score,
        "open_drift_count": float(len(open_drift)),
        "contamination_count": float(contamination_count),
    }

    return GraphResult(
        nodes=[_vertex_to_node(v) for v in result.nodes],
        edges=[_edge_to_graph_edge(e) for e in result.edges],
        overlays=overlays,
        explainability=ExplainabilityMetadata(
            summary=(
                f"Graph quality score: {graph_score:.3f} | "
                f"Open drift events: {len(open_drift)} | "
                f"Open contamination events: {contamination_count}"
            ),
            features=features,
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
    all_verts = [v for v in all_verts if v.properties.get("tenantId") == body.tenantId]
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
            "version": _GRAPH_CONTRACT_VERSION,
            "routes": ["traverse", "path", "temporal", "compare", "overlay", "filter"],
            "status": "traversal_engine_active",
            "relationship_layers": _RELATIONSHIP_LAYERS,
            "layer_count": len(_RELATIONSHIP_LAYERS),
        }
    ).to_dict()


@router.get("/health")
async def graph_health(
    request: Request,
    graph: GraphClient = Depends(get_graph),
    tenantId: Optional[str] = Query(None, description="Target tenant ID (Kyber operators only; defaults to the authenticated tenant)"),
) -> dict:
    """Graph health endpoint — layer coverage, node/edge counts, backend mode."""
    tenant = request.state.tenant
    tenant.require_permission("read")

    # Kyber operators may pass tenantId to inspect a specific tenant's graph.
    # Regular tenants are always scoped to their own ID.
    effective_tenant_id = tenantId if tenantId and getattr(tenant, "is_platform_admin", False) else tenant.tenant_id
    if tenantId and tenantId != tenant.tenant_id and not getattr(tenant, "is_platform_admin", False):
        from shared.common.common import ForbiddenError
        raise ForbiddenError("tenantId does not match authenticated tenant")

    all_verts = await graph.get_all_vertices(limit=10000)
    all_verts = [v for v in all_verts if v.properties.get("tenantId") == effective_tenant_id]
    all_edges: list[Edge] = []
    for v in all_verts:
        all_edges.extend(await graph.get_edges(v.vertex_id, direction="out"))

    layer_counts = get_layer_stats(all_edges)
    total_edges = len(all_edges)
    total_nodes = len(all_verts)

    layers_with_data = [l for l, c in layer_counts.items() if c > 0]
    all_layers_present = set(_RELATIONSHIP_LAYERS) <= set(layers_with_data)

    return APIResponse(
        data={
            "status": "healthy" if total_nodes > 0 else "no_data",
            "backend_mode": "neptune" if getattr(graph, "_mode", "local") == "neptune" else "local",
            "node_count": total_nodes,
            "edge_count": total_edges,
            "layer_counts": layer_counts,
            "layers_with_data": layers_with_data,
            "all_four_layers_present": all_layers_present,
            "relationship_layers": _RELATIONSHIP_LAYERS,
            "computed_at": _utc_now(),
        }
    ).to_dict()
