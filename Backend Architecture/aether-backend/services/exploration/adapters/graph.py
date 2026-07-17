"""Graph surface adapter — delegates to the Universal Graph Query plane.

The exploration graph surface is a thin, honest projection over
``services.operational_intelligence`` ``POST /v1/graph/query`` machinery: it
reuses that plane's boolean filter language, budgets, cursor pagination, and
tenant isolation rather than re-implementing traversal. The other entity/graph
-centric surfaces (profile360, cluster360, timeline, geo, campaign360) are
projections over the same real plane — they share this delegation seam and
differ only in the categories they declare and how they reshape the response.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.contracts_models.filters import FilterExpression, FilterGroup

from services.exploration.adapters.base import (
    AdapterContext,
    AdapterResult,
    AdapterTruncation,
    SurfaceAdapter,
)


async def run_universal_graph_query(body: Any, request: Any, graph: Any, cache: Any):
    """Delegation seam to the Universal Graph Query route (lazy import).

    Kept module-level so unit tests can monkeypatch it without importing the
    heavy operational-intelligence route module.
    """
    from services.operational_intelligence.routes import universal_graph_query

    return await universal_graph_query(body, request, graph, cache)


def build_graph_query(ctx: AdapterContext, *, node_types: Optional[list[str]] = None):
    """Build a ``UniversalGraphQueryRequest`` from an adapter context."""
    from services.operational_intelligence.models import UniversalGraphQueryRequest

    anchors = [a.id for a in (ctx.context.anchors or [])]
    boolean_filter: Optional[FilterGroup] = None
    if ctx.applied_filters:
        boolean_filter = FilterGroup(
            logic="AND",
            expressions=list(ctx.applied_filters),
        )

    graph_constraints = ctx.context.graph
    edge_types = list(graph_constraints.edge_types or []) if graph_constraints else []
    layers = list(graph_constraints.layers or []) if graph_constraints else []
    depth = (graph_constraints.depth if graph_constraints and graph_constraints.depth else 2)

    return UniversalGraphQueryRequest(
        tenant_id=ctx.tenant_id,
        anchors=anchors,
        node_types=node_types or [],
        edge_types=edge_types,
        layers=layers,
        filter=boolean_filter,
        depth=max(1, min(int(depth), 6)),
        limit=max(1, min(int(ctx.limit), 500)),
        cursor=ctx.cursor,
        as_of=ctx.as_of,
    )


def _truncation_from_meta(meta: Any, returned: int) -> AdapterTruncation:
    return AdapterTruncation(
        truncated=bool(getattr(meta, "truncated", False)),
        reason=getattr(meta, "truncation_reason", None),
        returned_count=returned,
        total_estimate=None,
    )


class GraphSurfaceAdapter(SurfaceAdapter):
    """Real graph exploration over the Universal Graph Query plane."""

    surface_id = "graph"

    def _reshape(self, response: Any) -> dict:
        return {
            "nodes": [n.model_dump(mode="json") for n in response.nodes],
            "edges": [e.model_dump(mode="json") for e in response.edges],
        }

    async def execute(self, ctx: AdapterContext) -> AdapterResult:
        body = build_graph_query(ctx)
        response = await run_universal_graph_query(
            body, ctx.request, ctx.graph, ctx.cache
        )
        meta = response.meta
        node_count = int(getattr(meta, "node_count", len(response.nodes)))
        warnings = list(getattr(meta, "warnings", []) or [])
        return AdapterResult(
            surface=self.surface_id,
            backend="operational_intelligence.graph_query",
            data=self._reshape(response),
            truncation=_truncation_from_meta(meta, node_count),
            cursor=getattr(meta, "cursor", None),
            warnings=warnings,
            populated=node_count > 0 or len(response.edges) > 0,
        )


__all__ = [
    "GraphSurfaceAdapter",
    "build_graph_query",
    "run_universal_graph_query",
]
