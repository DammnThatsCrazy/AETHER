"""Operational intelligence graph API — real traversal implementation.

Routes are backed by GraphTraversalEngine, which performs BFS over the
pluggable GraphClient (Neptune in production, in-memory in local dev).
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Union

from fastapi import APIRouter, Depends, Query, Request

from dependencies.providers import get_cache, get_graph
from shared.cache.cache import CacheKey
from shared.common.common import APIResponse, ForbiddenError
from shared.graph.graph import Edge, GraphClient, Vertex
from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type, get_layer_stats
from shared.graph.traversal import GraphTraversalEngine, TraversalResult
from shared.logger.logger import metrics
from services.data_quality.service import drift_service, intelligence_quality_service
from services.operational_intelligence.models import (
    ExplainabilityMetadata,
    FacetValue,
    FilterExpression,
    FilterGroup,
    FilterOperator,
    FlowGraphRequest,
    GraphCompareNodeDiff,
    GraphCompareEdgeDiff,
    GraphCompareRequest,
    GraphCompareResult,
    GraphEdge,
    GraphExportJob,
    GraphExportRequest,
    GraphFacet,
    GraphFacetRequest,
    GraphFacetResponse,
    GraphFilterRequest,
    GraphNode,
    GraphOverlay,
    GraphOverlayRequest,
    GraphQueryFilter,
    GraphQueryResponse,
    GraphResult,
    GraphResultMeta,
    GraphTraversalRequest,
    QUERY_BUDGET_DEFAULTS,
    ShortestPathRequest,
    TemporalGraphRequest,
    UniversalGraphQueryRequest,
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
        # Counter is also a security signal — alert if count exceeds 0 in production
        metrics.increment("graph_tenant_isolation_violation_total", labels={
            "requested_tenant": tenant_id,
            "authed_tenant": str(getattr(tenant, "tenant_id", "unknown")),
        })
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


async def _compute_overlay_scores(
    nodes: list[Vertex],
    edges: list[Edge],
    requested_overlays: list[str] | None,
    tenant_id: str = "",
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
        elif overlay_id == "economic":
            # Economic overlay — aggregate revenue/spend/LTV from node properties
            economic_nodes = [n for n in nodes if n.properties.get("revenue") or n.properties.get("ltv")]
            currencies: set[str] = set()
            total_rev = 0.0
            total_spend = 0.0
            for n in economic_nodes:
                try:
                    total_rev += float(n.properties.get("revenue") or 0)
                    total_spend += float(n.properties.get("spend") or 0)
                except (TypeError, ValueError):
                    pass
                if n.properties.get("currency"):
                    currencies.add(str(n.properties["currency"]))
            flow_edges = [e for e in edges if e.edge_type in ("PAYS_FOR", "TRANSFERS_TO", "SETTLED_VIA", "REFUNDED_BY")]
            multi_currency = len(currencies) > 1
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Economic",
                dimensions=[],
                properties={
                    "status": "computed",
                    "economic_node_count": len(economic_nodes),
                    "total_revenue": round(total_rev, 2),
                    "total_spend": round(total_spend, 2),
                    "currencies": sorted(currencies),
                    "multi_currency_warning": multi_currency,
                    "flow_edge_count": len(flow_edges),
                    "computed_at": _utc_now(),
                },
            ))
        elif overlay_id == "campaign":
            # Campaign attribution overlay — aggregate from node properties
            attributed_nodes = [
                n for n in nodes
                if n.properties.get("attributed_campaign_id") or n.properties.get("campaign_id")
            ]
            campaign_ids: set[str] = set()
            total_revenue = 0.0
            for n in attributed_nodes:
                cid = n.properties.get("attributed_campaign_id") or n.properties.get("campaign_id")
                if cid:
                    campaign_ids.add(str(cid))
                rev = n.properties.get("revenue") or n.properties.get("attributed_revenue") or 0
                try:
                    total_revenue += float(rev)
                except (TypeError, ValueError):
                    pass
            # Count ACQUIRED_VIA / ATTRIBUTED_TO_CAMPAIGN edges
            campaign_edges = [
                e for e in edges
                if e.edge_type in ("ACQUIRED_VIA", "ATTRIBUTED_TO_CAMPAIGN", "CONVERTED_FROM", "TOUCHPOINT_IN")
            ]
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Campaign Attribution",
                dimensions=[],
                properties={
                    "status": "computed",
                    "attributed_node_count": len(attributed_nodes),
                    "campaign_count": len(campaign_ids),
                    "campaign_ids": sorted(campaign_ids)[:20],
                    "campaign_edge_count": len(campaign_edges),
                    "total_attributed_revenue": round(total_revenue, 2),
                    "attribution_coverage_pct": round(len(attributed_nodes) / total_nodes * 100, 1) if total_nodes > 0 else 0.0,
                    "computed_at": _utc_now(),
                },
            ))
        elif overlay_id == "fraud":
            # Fraud overlay — join entity IDs against fraud network membership records
            from repositories.repos import FraudNetworkMemberRepository as _FNMRepo
            _fnm_repo = _FNMRepo()
            fraud_node_data: dict[str, dict] = {}
            for n in nodes:
                eid = n.properties.get("entity_id") or n.vertex_id
                try:
                    memberships = await _fnm_repo.list_by_entity(eid, tenant_id)
                except Exception:
                    memberships = []
                if memberships:
                    # Use highest-severity membership for node annotation
                    top = sorted(memberships, key=lambda m: m.get("risk_contribution", 0), reverse=True)[0]
                    fraud_node_data[n.vertex_id] = {
                        "fraud_network_id": top.get("network_id"),
                        "fraud_network_type": top.get("network_type"),
                        "member_role": top.get("role"),
                        "risk_score": top.get("risk_contribution") or n.properties.get("risk_score"),
                        "alert_state": top.get("alert_state") or n.properties.get("alert_state"),
                        "membership_count": len(memberships),
                    }
            fraud_member_count = len(fraud_node_data)
            network_ids: set[str] = {d["fraud_network_id"] for d in fraud_node_data.values() if d.get("fraud_network_id")}
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Fraud Network",
                dimensions=[],
                properties={
                    "status": "computed",
                    "fraud_member_count": fraud_member_count,
                    "network_count": len(network_ids),
                    "network_ids": sorted(str(nid) for nid in network_ids)[:20],
                    "fraud_coverage_pct": round(fraud_member_count / total_nodes * 100, 1) if total_nodes > 0 else 0.0,
                    "node_annotations": fraud_node_data,
                    "computed_at": _utc_now(),
                },
            ))
        elif overlay_id == "geography":
            # Geography overlay — aggregate country/region distribution from node properties
            country_dist: dict[str, int] = {}
            region_dist: dict[str, int] = {}
            location_type_dist: dict[str, int] = {}
            nodes_with_geo = 0
            for n in nodes:
                country = (
                    n.properties.get("country")
                    or n.properties.get("geo_country")
                    or n.properties.get("location_country")
                )
                region = n.properties.get("region") or n.properties.get("geo_region")
                loc_type = n.properties.get("location_type")
                if country:
                    nodes_with_geo += 1
                    country_dist[str(country)] = country_dist.get(str(country), 0) + 1
                if region:
                    region_dist[str(region)] = region_dist.get(str(region), 0) + 1
                if loc_type:
                    location_type_dist[str(loc_type)] = location_type_dist.get(str(loc_type), 0) + 1
            top_countries = sorted(country_dist.items(), key=lambda x: x[1], reverse=True)[:10]
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Geography",
                dimensions=[],
                properties={
                    "status": "computed",
                    "nodes_with_geo_data": nodes_with_geo,
                    "geo_coverage_pct": round(nodes_with_geo / total_nodes * 100, 1) if total_nodes > 0 else 0.0,
                    "country_count": len(country_dist),
                    "top_countries": [{"country": c, "count": n} for c, n in top_countries],
                    "region_count": len(region_dist),
                    "location_type_distribution": location_type_dist,
                    "computed_at": _utc_now(),
                },
            ))
        elif overlay_id == "consent":
            # Consent overlay — aggregate activation_eligible states from node properties
            eligible_count = sum(
                1 for n in nodes
                if n.properties.get("activation_eligible") is True
                or n.properties.get("consent_state") in ("granted", "active")
            )
            withdrawn_count = sum(
                1 for n in nodes
                if n.properties.get("consent_state") in ("withdrawn", "expired")
            )
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Consent / Eligibility",
                dimensions=[],
                properties={
                    "status": "computed",
                    "activation_eligible_count": eligible_count,
                    "consent_withdrawn_or_expired_count": withdrawn_count,
                    "activation_eligible_pct": round(eligible_count / total_nodes * 100, 1) if total_nodes > 0 else 0.0,
                    "computed_at": _utc_now(),
                },
            ))
        elif overlay_id == "agent":
            # Agent economic overlay — surface agent spend/revenue/task data from node properties
            agent_nodes = [
                n for n in nodes
                if n.vertex_type in ("agent", "Agent", "bot", "Bot")
                or n.properties.get("entity_type") in ("agent", "bot")
            ]
            total_agent_spend = 0.0
            total_agent_revenue = 0.0
            total_tasks = 0
            for n in agent_nodes:
                try:
                    total_agent_spend += float(n.properties.get("total_spend") or 0)
                    total_agent_revenue += float(n.properties.get("total_revenue_produced") or 0)
                    total_tasks += int(n.properties.get("task_count") or 0)
                except (TypeError, ValueError):
                    pass
            # A2A edges (delegation chains)
            a2a_edges = [e for e in edges if e.edge_type in ("HIRED", "SPAWNED_SUBAGENT", "DELEGATED_TO", "DELEGATED")]
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Agent Intelligence",
                dimensions=[],
                properties={
                    "status": "computed",
                    "agent_node_count": len(agent_nodes),
                    "total_agent_spend": round(total_agent_spend, 2),
                    "total_agent_revenue_produced": round(total_agent_revenue, 2),
                    "total_task_count": total_tasks,
                    "delegation_chain_count": len(a2a_edges),
                    "computed_at": _utc_now(),
                },
            ))
        elif overlay_id == "confidence":
            # Confidence/provenance overlay — aggregate confidence scores
            scores = [
                float(n.properties["confidence"])
                for n in nodes
                if isinstance(n.properties.get("confidence"), (int, float))
            ]
            avg_conf = round(sum(scores) / len(scores), 3) if scores else None
            overlays.append(GraphOverlay(
                id=overlay_id,
                name="Confidence",
                dimensions=[],
                properties={
                    "status": "computed",
                    "nodes_with_confidence": len(scores),
                    "avg_confidence": avg_conf,
                    "high_confidence_count": sum(1 for s in scores if s >= 0.8),
                    "low_confidence_count": sum(1 for s in scores if s < 0.5),
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
    "campaign":       ["attribution", "economic", "behavioral"],
    "economic":       ["economic", "chain", "behavioral"],
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
    "campaign":       "schema",
    "economic":       "events",
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


# ── Boolean filter evaluation ─────────────────────────────────────────────────

def _get_field_value(vertex: Vertex, field: str) -> Any:
    """Extract field value from a vertex using dot-path or special keys."""
    if field in ("node_type", "type", "vertex_type"):
        return vertex.vertex_type
    if field == "tenant_id":
        return vertex.properties.get("tenantId")
    # Economic field aliases — map economic.* shorthand to vertex properties
    _ECONOMIC_ALIASES: dict[str, str] = {
        "economic.revenue": "revenue",
        "economic.spend": "spend",
        "economic.ltv": "ltv",
        "economic.margin": "margin",
        "economic.transaction_volume": "transaction_volume",
        "economic.currency": "currency",
        "economic.rail": "rail",
        "economic.inflow": "inflow",
        "economic.outflow": "outflow",
        # geography shortcuts
        "geography.country": "country",
        "geography.region": "region",
        "geography.city": "city",
        "geography.jurisdiction": "jurisdiction",
    }
    if field in _ECONOMIC_ALIASES:
        return vertex.properties.get(_ECONOMIC_ALIASES[field])
    # dot-path into properties dict
    parts = field.split(".")
    val: Any = vertex.properties
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def _evaluate_expression(expr: FilterExpression, vertex: Vertex) -> bool:
    """Evaluate one FilterExpression against a vertex; fails closed on type errors."""
    val = _get_field_value(vertex, expr.field)
    op = expr.op
    expected = expr.value

    if op == FilterOperator.EXISTS:
        return val is not None
    if op == FilterOperator.NOT_EXISTS:
        return val is None
    if val is None:
        return False  # null fails all comparison operators

    try:
        if op == FilterOperator.EQ:
            return str(val) == str(expected)
        if op == FilterOperator.NEQ:
            return str(val) != str(expected)
        if op == FilterOperator.GT:
            return float(val) > float(expected)
        if op == FilterOperator.GTE:
            return float(val) >= float(expected)
        if op == FilterOperator.LT:
            return float(val) < float(expected)
        if op == FilterOperator.LTE:
            return float(val) <= float(expected)
        if op == FilterOperator.IN:
            return str(val) in [str(v) for v in (expected or [])]
        if op == FilterOperator.NOT_IN:
            return str(val) not in [str(v) for v in (expected or [])]
        if op == FilterOperator.CONTAINS:
            return str(expected) in str(val)
        if op == FilterOperator.STARTS_WITH:
            return str(val).startswith(str(expected))
        if op == FilterOperator.BETWEEN:
            lo, hi = float(expected["from"]), float(expected["to"])
            return lo <= float(val) <= hi
        if op == FilterOperator.THRESHOLD:
            return float(val) >= float(expected)
    except (TypeError, ValueError, KeyError, AttributeError):
        return False
    return False


def _evaluate_filter_group(group: FilterGroup, vertex: Vertex) -> bool:
    """Recursively evaluate a FilterGroup (AND / OR / NOT) against a vertex."""
    results = [
        _evaluate_expression(e, vertex)
        if isinstance(e, FilterExpression)
        else _evaluate_filter_group(e, vertex)
        for e in group.expressions
    ]
    if group.logic == "AND":
        return all(results) if results else True
    if group.logic == "OR":
        return any(results) if results else False
    if group.logic == "NOT":
        return not any(results)
    return False


def _apply_boolean_filter(
    nodes: list[Vertex], edges: list[Edge], fg: FilterGroup
) -> tuple[list[Vertex], list[Edge]]:
    """Filter nodes by a FilterGroup; prune edges whose endpoints are removed."""
    filtered = [v for v in nodes if _evaluate_filter_group(fg, v)]
    ids = {v.vertex_id for v in filtered}
    filtered_edges = [
        e for e in edges if e.from_vertex_id in ids and e.to_vertex_id in ids
    ]
    return filtered, filtered_edges


def _cursor_encode(offset: int) -> str:
    return base64.b64encode(json.dumps({"offset": offset}).encode()).decode()


def _cursor_decode(cursor: str) -> int:
    try:
        return json.loads(base64.b64decode(cursor.encode()).decode()).get("offset", 0)
    except Exception:
        return 0


def _make_meta(
    *,
    nodes: list,
    edges: list,
    all_nodes_count: int,
    start_ms: float,
    as_of: Optional[str] = None,
    cursor: Optional[str] = None,
    warnings: Optional[list[str]] = None,
) -> GraphResultMeta:
    elapsed = int((time.monotonic() - start_ms) * 1000)
    truncated = len(nodes) < all_nodes_count
    budget_used = min(1.0, len(nodes) / max(1, QUERY_BUDGET_DEFAULTS["max_nodes"]))
    return GraphResultMeta(
        truncated=truncated,
        truncation_reason="node_budget" if truncated else None,
        node_count=len(nodes),
        edge_count=len(edges),
        execution_ms=elapsed,
        query_id=str(uuid.uuid4()),
        budget_used=budget_used,
        cursor=cursor,
        as_of=as_of,
        warnings=warnings or [],
    )


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

    overlays = await _compute_overlay_scores(result.nodes, result.edges, body.overlays, tenant_id=body.tenantId)

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


@router.post("/query", response_model=GraphQueryResponse)
async def universal_graph_query(
    body: UniversalGraphQueryRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    cache=Depends(get_cache),
) -> GraphQueryResponse:
    """Universal graph query with boolean filter language, cursor pagination, and budget enforcement."""
    _require_read(request, body.tenant_id)
    metrics.increment("graph_query")
    start = time.monotonic()
    warnings: list[str] = []

    # ── Cache lookup — keyed on tenant+query+contract+time ───────────────────
    _q_body_key = json.dumps(body.model_dump(mode="json"), sort_keys=True, default=str)
    _q_hash = CacheKey.hash_query(_q_body_key)
    _cache_key = CacheKey.graph_query(
        tenant_id=body.tenant_id,
        query_hash=_q_hash,
        as_of=body.as_of or "",
    )
    try:
        _cached = await cache.get(_cache_key)
        if _cached:
            metrics.increment("graph_query_cache_hit")
            return GraphQueryResponse(**json.loads(_cached))
    except Exception:
        pass  # cache miss is fine

    engine = GraphTraversalEngine(graph)

    # ── Fetch base node set ───────────────────────────────────────────────────
    if body.anchors:
        all_nodes: list[Vertex] = []
        all_edges: list[Edge] = []
        seen_vids: set[str] = set()
        seen_ekeys: set[str] = set()
        for anchor_id in body.anchors[:10]:  # cap anchors at 10
            if body.as_of:
                result = await engine.temporal_bfs(
                    anchor_id, as_of=body.as_of, depth=body.depth,
                    direction="both", limit=body.limit, tenant_id=body.tenant_id,
                )
            else:
                result = await engine.bfs(
                    anchor_id, depth=body.depth, direction="both",
                    edge_types=body.edge_types or None,
                    limit=body.limit, tenant_id=body.tenant_id,
                )
            for v in result.nodes:
                if v.vertex_id not in seen_vids:
                    seen_vids.add(v.vertex_id)
                    all_nodes.append(v)
            for e in result.edges:
                ek = f"{e.from_vertex_id}:{e.edge_type}:{e.to_vertex_id}"
                if ek not in seen_ekeys:
                    seen_ekeys.add(ek)
                    all_edges.append(e)
            # also include anchor vertex itself
            anchor_v = await graph.get_vertex(anchor_id)
            if anchor_v and anchor_v.vertex_id not in seen_vids:
                if not body.tenant_id or anchor_v.properties.get("tenantId") == body.tenant_id:
                    seen_vids.add(anchor_v.vertex_id)
                    all_nodes.insert(0, anchor_v)
    else:
        raw_verts = await graph.get_all_vertices(limit=QUERY_BUDGET_DEFAULTS["max_nodes"])
        all_nodes = [v for v in raw_verts if v.properties.get("tenantId") == body.tenant_id]
        all_edges = []
        for v in all_nodes:
            all_edges.extend(await graph.get_edges(v.vertex_id, direction="out"))

    # ── Node-type filter ──────────────────────────────────────────────────────
    if body.node_types:
        allowed_nt = {t.lower() for t in body.node_types}
        all_nodes = [v for v in all_nodes if v.vertex_type.lower() in allowed_nt]
        node_ids = {v.vertex_id for v in all_nodes}
        all_edges = [e for e in all_edges if e.from_vertex_id in node_ids and e.to_vertex_id in node_ids]

    # ── Edge-type filter ──────────────────────────────────────────────────────
    if body.edge_types:
        allowed_et = set(body.edge_types)
        all_edges = [e for e in all_edges if e.edge_type in allowed_et]

    # ── Layer filter ──────────────────────────────────────────────────────────
    if body.layers:
        allowed_layers = set(body.layers)
        all_edges = [e for e in all_edges if classify_edge_type(e.edge_type) in allowed_layers]

    # ── Boolean filter ────────────────────────────────────────────────────────
    if body.filter:
        all_nodes, all_edges = _apply_boolean_filter(all_nodes, all_edges, body.filter)

    # ── Budget enforcement ────────────────────────────────────────────────────
    max_nodes = min(body.limit, QUERY_BUDGET_DEFAULTS["max_nodes"])
    all_nodes_total = len(all_nodes)
    truncated = len(all_nodes) > max_nodes

    # ── Cursor pagination ─────────────────────────────────────────────────────
    offset = _cursor_decode(body.cursor) if body.cursor else 0
    page_nodes = all_nodes[offset : offset + max_nodes]
    page_node_ids = {v.vertex_id for v in page_nodes}
    page_edges = [e for e in all_edges if e.from_vertex_id in page_node_ids and e.to_vertex_id in page_node_ids]

    next_cursor = _cursor_encode(offset + max_nodes) if len(all_nodes) > offset + max_nodes else None

    # ── Edge budget ───────────────────────────────────────────────────────────
    if len(page_edges) > QUERY_BUDGET_DEFAULTS["max_edges"]:
        page_edges = page_edges[:QUERY_BUDGET_DEFAULTS["max_edges"]]
        warnings.append("edge_budget_exceeded: edges truncated to max_edges limit")

    # ── Overlays ──────────────────────────────────────────────────────────────
    overlays = None
    if body.include_overlays:
        known_overlays = {"risk", "trust", "attribution", "layer_coverage", "economic", "campaign", "fraud", "geography", "consent", "confidence", "agent"}
        unknown = [o for o in body.include_overlays if o not in known_overlays]
        if unknown:
            warnings.append(f"unknown_overlays: {unknown}")
        overlays = await _compute_overlay_scores(page_nodes, page_edges, body.include_overlays, tenant_id=body.tenant_id)

    meta = _make_meta(
        nodes=page_nodes,
        edges=page_edges,
        all_nodes_count=all_nodes_total,
        start_ms=start,
        as_of=body.as_of,
        cursor=next_cursor,
        warnings=warnings,
    )

    result = GraphQueryResponse(
        nodes=[_vertex_to_node(v) for v in page_nodes],
        edges=[_edge_to_graph_edge(e) for e in page_edges],
        overlays=overlays,
        meta=meta,
    )

    # ── Cache write (short TTL for live queries, medium for temporal replay) ──
    try:
        from shared.cache.cache import TTL as _TTL
        _ttl = _TTL.MEDIUM if body.as_of else _TTL.SHORT
        await cache.set(_cache_key, json.dumps(result.model_dump(mode="json"), default=str), ttl=int(_ttl))
    except Exception:
        pass

    # ── Observability histograms ──────────────────────────────────────────────
    _duration_s = (time.monotonic() - start)
    metrics.observe("graph_query_duration_seconds", _duration_s, labels={
        "route": "query",
        "truncated": str(meta.truncated).lower(),
    })
    metrics.observe("graph_query_node_count", float(meta.node_count), labels={"route": "query"})
    if meta.truncated:
        metrics.increment("graph_budget_exceeded_total", labels={"budget_type": meta.truncation_reason or "node_limit"})

    return result


@router.post("/facets", response_model=GraphFacetResponse)
async def graph_facets(
    body: GraphFacetRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphFacetResponse:
    """Compute facet counts for graph nodes matching an optional filter."""
    _require_read(request, body.tenant_id)
    metrics.increment("graph_facets")
    start = time.monotonic()

    raw_verts = await graph.get_all_vertices(limit=body.limit)
    nodes = [v for v in raw_verts if v.properties.get("tenantId") == body.tenant_id]

    if body.as_of:
        def _valid(v: Vertex) -> bool:
            vf = v.properties.get("valid_from") or v.created_at or ""
            vt = v.properties.get("valid_to") or ""
            return (not vf or vf <= body.as_of) and (not vt or vt > body.as_of)
        nodes = [v for v in nodes if _valid(v)]

    if body.filter:
        nodes, _ = _apply_boolean_filter(nodes, [], body.filter)

    default_fields = body.facet_fields or ["node_type", "lifecycle_state"]
    facets: list[GraphFacet] = []
    for field in default_fields:
        counts: dict[str, int] = {}
        for v in nodes:
            val = str(_get_field_value(v, field) or "unknown")
            counts[val] = counts.get(val, 0) + 1
        facets.append(GraphFacet(
            field=field,
            values=[FacetValue(value=k, count=c) for k, c in sorted(counts.items(), key=lambda x: -x[1])],
        ))

    meta = _make_meta(nodes=nodes, edges=[], all_nodes_count=len(nodes), start_ms=start)
    return GraphFacetResponse(facets=facets, meta=meta)


@router.post("/explain")
async def graph_explain(
    body: UniversalGraphQueryRequest,
    request: Request,
) -> dict:
    """Return the parsed query plan for a UniversalGraphQueryRequest without executing it."""
    _require_read(request, body.tenant_id)
    metrics.increment("graph_explain")

    def _serialise_filter(fg: Optional[FilterGroup]) -> Optional[dict]:
        if fg is None:
            return None
        return {
            "logic": fg.logic,
            "expression_count": len(fg.expressions),
            "expressions": [
                {"field": e.field, "op": e.op.value, "value": e.value}
                if isinstance(e, FilterExpression)
                else _serialise_filter(e)
                for e in fg.expressions
            ],
        }

    plan = {
        "query_plan": {
            "strategy": "anchor_bfs" if body.anchors else "full_scan",
            "anchors": body.anchors,
            "depth": body.depth,
            "node_type_filter": body.node_types or None,
            "edge_type_filter": body.edge_types or None,
            "layer_filter": body.layers or None,
            "boolean_filter": _serialise_filter(body.filter),
            "temporal": body.as_of is not None,
            "as_of": body.as_of,
            "limit": body.limit,
            "include_overlays": body.include_overlays or None,
        },
        "estimated_cost": "low" if body.anchors else "medium",
        "warnings": [] if body.anchors else ["full_scan_without_anchors"],
        "query_id": str(uuid.uuid4()),
    }
    return APIResponse(data=plan).to_dict()


@router.post("/export", response_model=GraphExportJob)
async def graph_export(
    body: GraphExportRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> GraphExportJob:
    """Initiate a graph data export job. Returns immediately with job_id."""
    _require_read(request, body.tenant_id)
    metrics.increment("graph_export")

    # In local/in-memory mode we complete synchronously and return inline.
    # In production this would enqueue a Celery task and return status=queued.
    raw_verts = await graph.get_all_vertices(limit=body.limit)
    nodes = [v for v in raw_verts if v.properties.get("tenantId") == body.tenant_id]
    if body.filter:
        nodes, _ = _apply_boolean_filter(nodes, [], body.filter)

    job_id = str(uuid.uuid4())
    now = _utc_now()
    return GraphExportJob(
        job_id=job_id,
        status="completed",
        tenant_id=body.tenant_id,
        format=body.format,
        created_at=now,
        completed_at=now,
        download_url=f"/v1/graph/export/{job_id}/download?format={body.format}&count={len(nodes)}",
    )


@router.get("/export/{job_id}", response_model=GraphExportJob)
async def graph_export_status(
    job_id: str,
    request: Request,
) -> GraphExportJob:
    """Get the status of an async graph export job.

    In production this would look up the job in a persistent task store (Redis/DynamoDB).
    In local mode, all exports complete synchronously so this always returns not_found.
    """
    tenant = getattr(request.state, "tenant", None)
    if not tenant:
        raise ForbiddenError("Authentication required")
    return GraphExportJob(
        job_id=job_id,
        status="failed",
        tenant_id=getattr(tenant, "tenant_id", "unknown"),
        format="jsonl",
        created_at=_utc_now(),
        error="Job not found — in local mode exports complete synchronously and are not persisted.",
    )


@router.post("/flow")
async def graph_flow(
    body: FlowGraphRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
) -> dict:
    """Trace flow-of-funds from an anchor entity via economic edges.

    Traverses PAYS_FOR, TRANSFERS_TO, SETTLED_VIA, and REFUNDED_BY edges up to
    the requested depth and returns nodes and edges suitable for graph rendering.
    Multi-currency results include a warning when amounts cannot be safely summed.
    """
    _require_read(request, body.tenant_id)

    _FLOW_EDGE_TYPES = frozenset({"PAYS_FOR", "TRANSFERS_TO", "SETTLED_VIA", "REFUNDED_BY", "CHARGED_BACK_BY"})
    start = time.monotonic()
    query_id = str(uuid.uuid4())

    direction_map = {"downstream": "out", "upstream": "in", "both": "both"}
    bfs_direction = direction_map.get(body.direction, "out")

    engine = GraphTraversalEngine(graph)
    try:
        result: TraversalResult = engine.bfs(
            start_id=body.anchor_entity_id,
            depth=body.depth,
            direction=bfs_direction,
            edge_types=list(_FLOW_EDGE_TYPES),
            limit=body.limit,
            tenant_id=body.tenant_id,
        )
    except Exception:
        result = TraversalResult(nodes=[], edges=[])

    # Filter to only flow edge types (BFS may have included non-flow edges if edge_types not enforced)
    flow_edges = [e for e in result.edges if e.edge_type in _FLOW_EDGE_TYPES]
    flow_node_ids: set[str] = {body.anchor_entity_id}
    for e in flow_edges:
        flow_node_ids.add(e.from_vertex_id)
        flow_node_ids.add(e.to_vertex_id)
    flow_nodes = [n for n in result.nodes if n.vertex_id in flow_node_ids]

    # Include anchor node even if BFS did not return it
    anchor_ids = {n.vertex_id for n in flow_nodes}
    if body.anchor_entity_id not in anchor_ids:
        try:
            anchor = await graph.get_vertex(body.anchor_entity_id)
            if anchor and anchor.properties.get("tenantId") == body.tenant_id:
                flow_nodes.insert(0, anchor)
        except Exception:
            pass

    # Multi-currency check
    currencies: set[str] = set()
    for n in flow_nodes:
        if n.properties.get("currency"):
            currencies.add(str(n.properties["currency"]))

    truncated = len(result.nodes) >= body.limit
    duration_ms = int((time.monotonic() - start) * 1000)

    out_nodes = [
        GraphNode(
            id=n.vertex_id,
            node_type=n.vertex_type,
            label=n.properties.get("display_name") or n.properties.get("name") or n.vertex_id,
            properties=n.properties,
            trust_score=n.properties.get("trust_score"),
            risk_score=n.properties.get("risk_score"),
            lifecycle_state=n.properties.get("lifecycle_state"),
        )
        for n in flow_nodes
    ]
    out_edges = [
        GraphEdge(
            id=e.edge_id,
            source=e.from_vertex_id,
            target=e.to_vertex_id,
            edge_type=e.edge_type,
            layer=classify_edge_type(e.edge_type) or RelationshipLayer.H2H,
            properties=e.properties,
        )
        for e in flow_edges
    ]

    meta = GraphResultMeta(
        truncated=truncated,
        truncation_reason="limit_reached" if truncated else None,
        node_count=len(out_nodes),
        edge_count=len(out_edges),
        execution_ms=duration_ms,
        query_id=query_id,
        budget_used=min(len(out_nodes) / body.limit, 1.0),
        cursor=None,
        as_of=None,
        freshness_seconds=None,
        warnings=(["multi_currency_amounts_not_summed"] if len(currencies) > 1 else []),
    )

    return APIResponse(
        data={
            "nodes": [n.model_dump() for n in out_nodes],
            "edges": [e.model_dump() for e in out_edges],
            "meta": meta.model_dump(),
            "flow_summary": {
                "anchor_entity_id": body.anchor_entity_id,
                "direction": body.direction,
                "currencies": sorted(currencies),
                "multi_currency_warning": len(currencies) > 1,
                "flow_edge_count": len(out_edges),
                "hop_depth": body.depth,
            },
        }
    ).to_dict()


@router.get("/capabilities")
async def graph_capabilities() -> dict:
    """Advertise the supported operators, node/edge types, overlays, and features."""
    return APIResponse(
        data={
            "version": _GRAPH_CONTRACT_VERSION,
            "filter_operators": sorted(FilterOperator.valid_values()),
            "supported_overlays": ["risk", "trust", "attribution", "layer_coverage", "economic", "campaign", "fraud", "geography", "consent", "confidence", "agent"],
            "supported_facet_fields": ["node_type", "lifecycle_state", "risk_tier", "layer", "geography.country"],
            "relationship_layers": _RELATIONSHIP_LAYERS,
            "query_budget": QUERY_BUDGET_DEFAULTS,
            "temporal": {
                "point_in_time_replay": True,
                "bitemporal_fields": ["valid_from", "valid_to", "recorded_at", "superseded_at"],
            },
            "pagination": {
                "cursor_based": True,
                "max_page_size": 500,
            },
            "features": [
                "boolean_filter_language",
                "cursor_pagination",
                "query_budget_enforcement",
                "temporal_replay",
                "historical_comparison",
                "overlay_computation",
                "facet_computation",
                "export",
            ],
        }
    ).to_dict()


@router.get("/contracts")
async def graph_contracts() -> dict:
    """Expose the active graph contract route family for diagnostics."""
    return APIResponse(
        data={
            "version": _GRAPH_CONTRACT_VERSION,
            "routes": [
                "traverse", "path", "temporal", "compare",
                "query", "facets", "explain", "export", "capabilities",
                "overlay", "filter",
            ],
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
