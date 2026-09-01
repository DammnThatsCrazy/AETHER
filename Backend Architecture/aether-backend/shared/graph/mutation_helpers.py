"""Small adapters for routing legacy graph writers through the gateway.

The helpers intentionally keep the legacy call sites terse while preserving
the graph client's off-mode behaviour.  A writer that has no tenant context is
given the explicit ``unscoped`` tenant; rights enforce mode then fails closed
until the caller supplies a tenant and an IRRL proof instead of silently
creating a cross-tenant fact.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.graph.graph import Edge, GraphClient, Vertex, tenant_of
from shared.graph.mutation_gateway import (
    MutationIntent,
    get_mutation_gateway,
)


def _tenant_id(properties: Optional[dict[str, Any]]) -> str:
    return tenant_of(properties) or "unscoped"


def _rights_kwargs(properties: Optional[dict[str, Any]]) -> dict[str, Any]:
    values = properties or {}
    return {
        "rights_decision_id": values.get("rights_decision_id"),
        "rights_envelope_id": values.get("rights_envelope_id"),
        "rights_policy_set_ref": values.get("rights_policy_set_ref"),
        "rights_lineage_set_hash": values.get("rights_lineage_set_hash"),
        "rights_source_grant_refs": values.get("rights_source_grant_refs"),
    }


async def apply_vertex(
    vertex: Vertex,
    *,
    graph: Optional[GraphClient] = None,
    tenant_id: Optional[str] = None,
    operation: str = "node_versioned",
    actor_kind: str = "service",
    actor_id: str = "graph_writer",
) -> Any:
    """Apply a vertex mutation through the canonical graph gateway."""

    props = dict(vertex.properties or {})
    resolved_tenant = tenant_id or _tenant_id(props)
    if tenant_id and not tenant_of(props):
        props["tenantId"] = tenant_id
    effective_vertex = Vertex(
        vertex_type=vertex.vertex_type,
        vertex_id=vertex.vertex_id,
        properties=props,
        created_at=vertex.created_at,
    )
    return await get_mutation_gateway(graph).apply(
        MutationIntent(
            operation=operation,
            tenant_id=resolved_tenant,
            vertex=effective_vertex,
            actor_kind=actor_kind,
            actor_id=actor_id,
            reason_code="legacy_graph_writer",
            **_rights_kwargs(props),
        )
    )


async def apply_edge(
    edge: Edge,
    *,
    graph: Optional[GraphClient] = None,
    tenant_id: Optional[str] = None,
    operation: str = "edge_created",
    actor_kind: str = "service",
    actor_id: str = "graph_writer",
) -> Any:
    """Apply an edge mutation through the canonical graph gateway."""

    props = dict(edge.properties or {})
    resolved_tenant = tenant_id or _tenant_id(props)
    if tenant_id and not tenant_of(props):
        props["tenant_id"] = tenant_id
    effective_edge = Edge(
        edge_type=edge.edge_type,
        from_vertex_id=edge.from_vertex_id,
        to_vertex_id=edge.to_vertex_id,
        properties=props,
        created_at=edge.created_at,
    )
    return await get_mutation_gateway(graph).apply(
        MutationIntent(
            operation=operation,
            tenant_id=resolved_tenant,
            edge=effective_edge,
            actor_kind=actor_kind,
            actor_id=actor_id,
            reason_code="legacy_graph_writer",
            **_rights_kwargs(props),
        )
    )


__all__ = ["apply_edge", "apply_vertex"]
