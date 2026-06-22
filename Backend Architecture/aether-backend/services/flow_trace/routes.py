"""Flow-of-Funds Trace — API routes.

Endpoints:
    POST /v1/flow-trace/trace               Create and run a flow trace
    GET  /v1/flow-trace                     List traces for a tenant
    GET  /v1/flow-trace/{trace_id}          Get trace details
    GET  /v1/flow-trace/{trace_id}/paths    List discovered paths
    GET  /v1/flow-trace/{trace_id}/sources  Source nodes
    GET  /v1/flow-trace/{trace_id}/sinks    Sink nodes
    GET  /v1/flow-trace/{trace_id}/cycles   Cycle information
    GET  /v1/flow-trace/{trace_id}/timeline Trace event timeline
    POST /v1/flow-trace/{trace_id}/attach   Attach trace to investigation case
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from config.settings import settings
from dependencies.providers import get_graph, get_producer
from repositories.repos import (
    FlowTracePathRepository,
    FlowTraceRepository,
    InvestigationRepository,
    TransferRepository,
)
from services.flow_trace.models import (
    FlowTraceAttachRequest,
    FlowTraceRequest,
    FlowTraceResponse,
)
from services.flow_trace.scoring import score_path, score_trace
from services.flow_trace.traversal import FlowTraceEngine
from services.operational_intelligence.models import EvidenceRef
from shared.common.common import APIResponse, ForbiddenError, NotFoundError
from shared.events.events import Event, EventProducer, Topic
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.flow_trace")

router = APIRouter(prefix="/v1/flow-trace", tags=["Flow-of-Funds Trace"])

_traces = FlowTraceRepository()
_paths_repo = FlowTracePathRepository()
_investigations = InvestigationRepository()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_feature() -> None:
    if not settings.fraud_intelligence.flow_trace_enabled:
        raise NotFoundError("Flow Trace feature is not enabled")


def _require(request: Request, tenant_id: str, permission: str = "fraud:read") -> None:
    _require_feature()
    tenant = request.state.tenant
    tenant.require_permission(permission)
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


async def _get_trace(trace_id: str, tenant_id: str) -> dict:
    row = await _traces.get(trace_id)
    if row is None or row.get("tenant_id") != tenant_id:
        raise NotFoundError(f"FlowTrace {trace_id!r} not found")
    return row


def _to_response(row: dict) -> FlowTraceResponse:
    return FlowTraceResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        anchor_entity_id=row.get("anchor_entity_id", ""),
        direction=row.get("direction", "downstream"),
        label=row.get("label"),
        status=row.get("status", "complete"),
        path_count=row.get("path_count", 0),
        node_count=row.get("node_count", 0),
        source_nodes=row.get("source_nodes", []),
        sink_nodes=row.get("sink_nodes", []),
        aggregation_points=row.get("aggregation_points", []),
        cycle_detected=row.get("cycle_detected", False),
        cycle_nodes=row.get("cycle_nodes", []),
        risk_score=row.get("risk_score", 0.0),
        pattern_tags=row.get("pattern_tags", []),
        evidence_refs=[EvidenceRef(**e) for e in row.get("evidence_refs", [])],
        created_at=row.get("created_at", ""),
        completed_at=row.get("completed_at"),
        metadata=row.get("metadata", {}),
    )


@router.post("/trace", response_model=None)
async def create_trace(
    body: FlowTraceRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Create and run a flow-of-funds trace from the anchor entity."""
    _require(request, body.tenant_id, "fraud:evaluate")
    now = _utc_now()

    engine = FlowTraceEngine(TransferRepository())
    result = await engine.trace(
        tenant_id=body.tenant_id,
        anchor_entity_id=body.anchor_entity_id,
        direction=body.direction,
        max_hops=min(body.max_hops, settings.fraud_intelligence.max_flow_trace_hops),
        min_amount_usd=body.min_amount_usd,
    )

    trace_id = result["trace_id"]
    paths = result["paths"]
    nodes = result["nodes"]

    # Score all paths
    path_risk_scores = []
    for p in paths:
        rs = score_path(
            hop_count=p.hop_count,
            total_amount_usd=p.total_amount_usd,
            contains_cycle=p.contains_cycle,
            passes_through_sink=p.passes_through_sink,
            passes_through_source=p.passes_through_source,
            pattern_count=len(p.pattern_tags),
        )
        p.risk_score = rs
        path_risk_scores.append(rs)

    trace_risk = score_trace(
        path_risk_scores=path_risk_scores,
        cycle_detected=result["cycle_detected"],
        source_count=len(result["source_nodes"]),
        sink_count=len(result["sink_nodes"]),
        aggregation_point_count=len(result["aggregation_points"]),
        total_path_count=len(paths),
    )

    # Build trace record
    trace_row = {
        "id": trace_id,
        "tenant_id": body.tenant_id,
        "anchor_entity_id": body.anchor_entity_id,
        "direction": body.direction,
        "label": body.label,
        "status": "complete",
        "path_count": len(paths),
        "node_count": len(nodes),
        "source_nodes": result["source_nodes"],
        "sink_nodes": result["sink_nodes"],
        "aggregation_points": result["aggregation_points"],
        "cycle_detected": result["cycle_detected"],
        "cycle_nodes": result["cycle_nodes"],
        "risk_score": trace_risk,
        "pattern_tags": result["pattern_tags"],
        "evidence_refs": [],
        "created_at": now,
        "completed_at": _utc_now(),
        "metadata": body.metadata,
    }
    await _traces.create(trace_row)

    # Persist paths
    for p in paths:
        path_row = {
            "id": p.id,
            "trace_id": trace_id,
            "tenant_id": body.tenant_id,
            "path_nodes": p.path_nodes,
            "path_edges": p.path_edges,
            "hop_count": p.hop_count,
            "total_amount_usd": p.total_amount_usd,
            "risk_score": p.risk_score,
            "pattern_tags": [t for t in p.pattern_tags],
            "contains_cycle": p.contains_cycle,
            "passes_through_sink": p.passes_through_sink,
            "passes_through_source": p.passes_through_source,
            "discovered_at": p.discovered_at,
            "metadata": p.metadata,
        }
        await _paths_repo.create(path_row)

    # Project to graph (best-effort)
    try:
        vertex = Vertex(
            vertex_type=VertexType.FLOW_TRACE,
            vertex_id=trace_id,
            properties={
                "tenant_id": body.tenant_id,
                "risk_score": str(trace_risk),
                "anchor": body.anchor_entity_id,
            },
        )
        await graph.upsert_vertex(vertex)
        edge = Edge(
            edge_type=EdgeType.PART_OF_FLOW_TRACE,
            from_vertex_id=body.anchor_entity_id,
            to_vertex_id=trace_id,
            properties={"tenant_id": body.tenant_id},
        )
        await graph.add_edge(edge)
        for sink_id in result["sink_nodes"]:
            sink_edge = Edge(
                edge_type=EdgeType.HAS_SINK,
                from_vertex_id=trace_id,
                to_vertex_id=sink_id,
                properties={"tenant_id": body.tenant_id},
            )
            await graph.add_edge(sink_edge)
        for source_id in result["source_nodes"]:
            source_edge = Edge(
                edge_type=EdgeType.HAS_SOURCE,
                from_vertex_id=trace_id,
                to_vertex_id=source_id,
                properties={"tenant_id": body.tenant_id},
            )
            await graph.add_edge(source_edge)
    except Exception as exc:
        logger.warning("flow_trace_graph_projection_failed", extra={"error": str(exc)})

    await producer.publish(Event(
        topic=Topic.FLOW_TRACE_CREATED,
        tenant_id=body.tenant_id,
        source_service="flow_trace",
        payload={"trace_id": trace_id, "anchor": body.anchor_entity_id, "risk_score": trace_risk},
    ))
    await producer.publish(Event(
        topic=Topic.FLOW_TRACE_COMPLETED,
        tenant_id=body.tenant_id,
        source_service="flow_trace",
        payload={"trace_id": trace_id, "path_count": len(paths)},
    ))
    metrics.increment("flow_trace_created")
    return _to_response(trace_row).model_dump()


@router.get("", response_model=None)
async def list_traces(
    request: Request,
    tenant_id: str = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """List flow traces for the authenticated tenant."""
    _require(request, tenant_id, "fraud:read")
    rows = await _traces.list_by_tenant(tenant_id, limit=limit)
    traces = [_to_response(r).model_dump() for r in rows]
    return APIResponse(data=traces, meta={"count": len(traces)}).to_dict()


@router.get("/{trace_id}", response_model=None)
async def get_trace(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Get a single flow trace by ID."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_trace(trace_id, tenant_id)
    return _to_response(row).model_dump()


@router.get("/{trace_id}/paths", response_model=None)
async def get_paths(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    """List all discovered flow paths for a trace."""
    _require(request, tenant_id, "fraud:read")
    await _get_trace(trace_id, tenant_id)
    path_rows = await _paths_repo.list_by_trace(trace_id)
    return APIResponse(
        data=path_rows[:limit],
        meta={"count": len(path_rows)},
    ).to_dict()


@router.get("/{trace_id}/sources", response_model=None)
async def get_sources(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Return the identified source (injection) nodes for a trace."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_trace(trace_id, tenant_id)
    sources = row.get("source_nodes", [])
    return APIResponse(data=sources, meta={"count": len(sources)}).to_dict()


@router.get("/{trace_id}/sinks", response_model=None)
async def get_sinks(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Return the identified sink (terminal recipient) nodes for a trace."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_trace(trace_id, tenant_id)
    sinks = row.get("sink_nodes", [])
    return APIResponse(data=sinks, meta={"count": len(sinks)}).to_dict()


@router.get("/{trace_id}/cycles", response_model=None)
async def get_cycles(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Return cycle detection results for a trace."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_trace(trace_id, tenant_id)
    return {
        "trace_id": trace_id,
        "cycle_detected": row.get("cycle_detected", False),
        "cycle_nodes": row.get("cycle_nodes", []),
    }


@router.get("/{trace_id}/timeline", response_model=None)
async def get_timeline(
    trace_id: str,
    request: Request,
    tenant_id: str = Query(...),
) -> dict:
    """Return a timeline of trace lifecycle events."""
    _require(request, tenant_id, "fraud:read")
    row = await _get_trace(trace_id, tenant_id)
    timeline = [
        {"event": "trace_created", "at": row.get("created_at"), "detail": {"anchor": row.get("anchor_entity_id")}},
    ]
    if row.get("completed_at"):
        timeline.append({
            "event": "trace_completed",
            "at": row["completed_at"],
            "detail": {
                "path_count": row.get("path_count", 0),
                "risk_score": row.get("risk_score", 0.0),
            },
        })
    return APIResponse(data=timeline, meta={"count": len(timeline)}).to_dict()


@router.post("/{trace_id}/attach", response_model=None)
async def attach_to_case(
    trace_id: str,
    body: FlowTraceAttachRequest,
    request: Request,
    graph: GraphClient = Depends(get_graph),
    producer: EventProducer = Depends(get_producer),
) -> dict:
    """Attach a flow trace to an existing investigation case."""
    _require(request, body.tenant_id, "fraud:evaluate")
    row = await _get_trace(trace_id, body.tenant_id)

    # Verify the case exists and belongs to the same tenant
    case_row = await _investigations.find_by_id(body.case_id)
    if case_row is None or case_row.get("tenantId") != body.tenant_id:
        raise NotFoundError(f"InvestigationCase {body.case_id!r} not found")

    # Add flow trace evidence to the case
    existing_evidence = case_row.get("evidence", [])
    trace_evidence = EvidenceRef(
        id=str(uuid.uuid4()),
        type="transaction",
        source="aether.flow_trace",
        observedAt=row.get("completed_at", row.get("created_at", "")),
        confidence=min(row.get("risk_score", 0.0) / 100.0, 1.0),
        uri=f"aether://flow-trace/{trace_id}",
    )
    updated_evidence = existing_evidence + [trace_evidence.model_dump()]
    await _investigations.update(body.case_id, {
        "evidence": updated_evidence,
        "updatedAt": _utc_now(),
    })

    # Project ATTACHED_TO_CASE graph edge (best-effort)
    try:
        edge = Edge(
            edge_type=EdgeType.ATTACHED_TO_CASE,
            from_vertex_id=trace_id,
            to_vertex_id=body.case_id,
            properties={"tenant_id": body.tenant_id},
        )
        await graph.add_edge(edge)
    except Exception as exc:
        logger.warning("flow_trace_attach_graph_failed", extra={"error": str(exc)})

    metrics.increment("flow_trace_attached_to_case")
    return {"trace_id": trace_id, "case_id": body.case_id, "attached": True}
