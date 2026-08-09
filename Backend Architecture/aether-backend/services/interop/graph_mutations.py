"""Interoperability graph projections — deterministic, evidence-bearing
topology and message-link edges. Messages stay silver facts; the graph
carries providers, gateways, paths, applications, and actor relationships.
Callers gate on settings.interop.graph_enabled and persist via
foundation.persist_mutations."""

from __future__ import annotations

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from services.interop.foundation import PUBLIC_TENANT, utc_now_iso

_PROVENANCE = "interoperability_intelligence"


def build_topology_mutations(
    provider: dict, gateways: list[dict], paths: list[dict],
) -> tuple[list[Vertex], list[Edge]]:
    """Provider/gateway/path topology (public reference scope)."""
    provider_vid = f"interop_provider:{provider['provider_id']}"
    vertices = [Vertex(
        vertex_id=provider_vid,
        vertex_type=VertexType.INTEROP_PROVIDER,
        properties={
            "tenant_id": PUBLIC_TENANT,
            "provider_kind": provider.get("provider_kind", "unknown"),
            "implementation_status": provider.get("implementation_status", "scaffolded"),
        },
    )]
    edges: list[Edge] = []

    for gateway in gateways:
        gateway_vid = f"interop_gateway:{gateway['gateway_id']}"
        chain_vid = f"chain:{gateway.get('native_chain_id', 'unknown')}"
        vertices.append(Vertex(
            vertex_id=gateway_vid,
            vertex_type=VertexType.INTEROP_GATEWAY,
            properties={
                "tenant_id": PUBLIC_TENANT,
                "network_id": gateway.get("network_id", ""),
                "gateway_role": gateway.get("gateway_role", "unknown"),
            },
        ))
        vertices.append(Vertex(
            vertex_id=chain_vid,
            vertex_type=VertexType.CHAIN,
            properties={"tenant_id": PUBLIC_TENANT},
        ))
        edges.append(_edge(EdgeType.CONNECTS_CHAIN, gateway_vid, chain_vid,
                           PUBLIC_TENANT, gateway.get("gateway_id", "")))

    for path in paths:
        path_vid = f"interop_path:{path['path_id']}"
        vertices.append(Vertex(
            vertex_id=path_vid,
            vertex_type=VertexType.INTEROP_PATH,
            properties={
                "tenant_id": PUBLIC_TENANT,
                "source_network_id": path.get("source_network_id", ""),
                "destination_network_id": path.get("destination_network_id", ""),
            },
        ))
        edges.append(_edge(EdgeType.USES_PROVIDER, path_vid, provider_vid,
                           PUBLIC_TENANT, path.get("path_id", "")))
        for gateway_key in ("source_gateway_id", "destination_gateway_id"):
            gateway_id = path.get(gateway_key)
            if gateway_id:
                edges.append(_edge(
                    EdgeType.ROUTES_THROUGH, path_vid,
                    f"interop_gateway:{gateway_id}", PUBLIC_TENANT,
                    path.get("path_id", ""),
                ))
    return vertices, edges


def build_message_mutations(message: dict) -> tuple[list[Vertex], list[Edge]]:
    """Material message links: SENT_VIA_PATH from the originating application
    (or wallet) to the path; SECURED_BY_POLICY when a snapshot is attached.
    Tenant-scoped for tenant messages, public for public-scope rows."""
    tenant_id = message["tenant_id"]
    path_vid = f"interop_path:{message['path_id']}"
    source = message.get("source") or {}
    origin_application = source.get("application_id")
    origin_vid = (
        f"interop_application:{origin_application}"
        if origin_application else f"wallet:{source.get('transaction_hash', 'unknown')}"
    )
    vertices = [Vertex(
        vertex_id=path_vid,
        vertex_type=VertexType.INTEROP_PATH,
        properties={"tenant_id": PUBLIC_TENANT},
    )]
    if origin_application:
        vertices.append(Vertex(
            vertex_id=origin_vid,
            vertex_type=VertexType.INTEROP_APPLICATION,
            properties={"tenant_id": PUBLIC_TENANT},
        ))
    edges = [_edge(
        EdgeType.SENT_VIA_PATH, origin_vid, path_vid, tenant_id,
        message["interop_message_id"],
        status=message.get("status", "unknown"),
        correlation_key=message.get("correlation_key", ""),
    )]
    snapshot_id = message.get("security_snapshot_id")
    if snapshot_id:
        edges.append(_edge(
            EdgeType.SECURED_BY_POLICY, path_vid,
            f"security_policy_snapshot:{snapshot_id}", tenant_id,
            message["interop_message_id"],
        ))
    return vertices, edges


def _edge(edge_type: str, from_vid: str, to_vid: str, tenant_id: str,
          source_event_id: str, **extra: str) -> Edge:
    return Edge(
        edge_type=edge_type,
        from_vertex_id=from_vid,
        to_vertex_id=to_vid,
        properties=build_edge_properties(
            tenant_id=tenant_id,
            edge_type=edge_type,
            from_vertex_id=from_vid,
            to_vertex_id=to_vid,
            # Graph write validator admits only agent|human|system; the
            # interop intelligence plane is a system actor.
            actor_kind="system",
            actor_id="interop_intelligence",
            provenance=_PROVENANCE,
            valid_from=utc_now_iso(),
            source_event_id=source_event_id,
            **extra,
        ),
    )
