"""Additive graph intelligence API skeletons.

These routes establish the stable FastAPI/OpenAPI surface for the operational
intelligence graph query plane.  They are intentionally conservative: the first
iteration validates contracts, enforces tenant/read permissions, and returns
well-formed empty or anchor-only graph results.  Graph-store traversal can be
implemented behind these handlers without changing the public contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Request

from shared.common.common import APIResponse, ForbiddenError
from shared.logger.logger import metrics
from services.operational_intelligence.models import (
    EntityRef,
    ExplainabilityMetadata,
    GraphFilterRequest,
    GraphNode,
    GraphOverlay,
    GraphOverlayRequest,
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
    # The auth middleware is the source of truth for tenant identity.  Until the
    # graph engine is fully implemented, keep route skeletons strict so clients
    # cannot accidentally query another tenant's graph by body parameter alone.
    if tenant_id != tenant.tenant_id:
        raise ForbiddenError("tenantId does not match authenticated tenant")


def _node_from_ref(ref: EntityRef, *, tenant_id: str, role: str) -> GraphNode:
    return GraphNode(
        id=ref.id,
        kind=ref.kind,
        label=ref.label,
        properties={
            "tenantId": tenant_id,
            "role": role,
            "contractStage": "skeleton",
        },
    )


def _overlays(ids: Iterable[str] | None) -> list[GraphOverlay] | None:
    if not ids:
        return None
    return [GraphOverlay(id=overlay_id, name=overlay_id, dimensions=[]) for overlay_id in ids]


def _explain(summary: str) -> ExplainabilityMetadata:
    return ExplainabilityMetadata(
        summary=summary,
        evidence=[],
        features={"contractStage": "skeleton", "computedAt": _utc_now()},
    )


@router.post("/traverse", response_model=GraphResult)
async def traverse_graph(body: GraphTraversalRequest, request: Request) -> GraphResult:
    """Validate and reserve the bounded neighborhood traversal contract."""

    _require_read(request, body.tenantId)
    metrics.increment("graph_traverse_contract_validated")
    return GraphResult(
        nodes=[_node_from_ref(body.start, tenant_id=body.tenantId, role="start")],
        edges=[],
        overlays=_overlays(body.overlays),
        explainability=_explain("Graph traversal contract validated; traversal engine pending."),
    )


@router.post("/path", response_model=GraphResult)
async def shortest_path(body: ShortestPathRequest, request: Request) -> GraphResult:
    """Validate and reserve the shortest/scored path contract."""

    _require_read(request, body.tenantId)
    metrics.increment("graph_path_contract_validated")
    return GraphResult(
        nodes=[
            _node_from_ref(body.from_, tenant_id=body.tenantId, role="from"),
            _node_from_ref(body.to, tenant_id=body.tenantId, role="to"),
        ],
        edges=[],
        explainability=_explain("Shortest path contract validated; path engine pending."),
    )


@router.post("/temporal", response_model=GraphResult)
async def temporal_graph(body: TemporalGraphRequest, request: Request) -> GraphResult:
    """Validate and reserve temporal graph reconstruction requests."""

    _require_read(request, body.tenantId)
    metrics.increment("graph_temporal_contract_validated")
    node = _node_from_ref(body.anchor, tenant_id=body.tenantId, role="anchor")
    properties = dict(node.properties or {})
    properties["asOf"] = body.asOf
    node.properties = properties
    return GraphResult(
        nodes=[node],
        edges=[],
        explainability=_explain("Temporal graph contract validated; replay engine pending."),
    )


@router.post("/overlay", response_model=GraphResult)
async def graph_overlay(body: GraphOverlayRequest, request: Request) -> GraphResult:
    """Validate graph overlay requests for risk/trust/attribution views."""

    _require_read(request, body.tenantId)
    metrics.increment("graph_overlay_contract_validated")
    return GraphResult(
        nodes=[],
        edges=[],
        overlays=_overlays(body.overlays),
        explainability=_explain("Graph overlay contract validated; overlay materializer pending."),
    )


@router.post("/filter", response_model=GraphResult)
async def graph_filter(body: GraphFilterRequest, request: Request) -> GraphResult:
    """Validate graph filtering requests for Kyber workspace queries."""

    _require_read(request, body.tenantId)
    metrics.increment("graph_filter_contract_validated")
    return GraphResult(
        nodes=[],
        edges=[],
        explainability=_explain("Graph filter contract validated; graph query engine pending."),
    )


@router.get("/contracts")
async def graph_contracts() -> dict:
    """Expose the active graph contract route family for diagnostics."""

    return APIResponse(
        data={
            "version": "v1",
            "routes": ["traverse", "path", "temporal", "overlay", "filter"],
            "status": "contract_surface_active",
        }
    ).to_dict()
