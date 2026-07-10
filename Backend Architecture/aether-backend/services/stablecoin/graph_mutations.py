"""Stablecoin graph projections — deterministic, tenant-scoped, evidence-
bearing vertices/edges built from canonical records. Callers gate on
settings.stablecoin.graph_enabled and persist via foundation.persist_mutations."""

from __future__ import annotations

from typing import Any

from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from services.stablecoin.foundation import utc_now_iso

_PROVENANCE = "stablecoin_intelligence"


def _tenant_mismatch(a: dict | None, b: dict | None) -> bool:
    ta = (a or {}).get("tenant_id")
    tb = (b or {}).get("tenant_id")
    return bool(ta and tb and ta != tb)


def build_deployment_mutations(deployment: dict) -> tuple[list[Vertex], list[Edge]]:
    """STABLECOIN_DEPLOYMENT vertex + DEPLOYED_ON_CHAIN edge to the chain
    vertex + ISSUED_BY link is intentionally omitted until issuer entities
    resolve. Global reference topology uses the platform tenant."""
    deployment_vid = f"stablecoin_deployment:{deployment['deployment_id']}"
    chain_vid = f"chain:{deployment['chain_id']}"
    vertices = [
        Vertex(
            vertex_id=deployment_vid,
            vertex_type=VertexType.STABLECOIN_DEPLOYMENT,
            properties={
                "tenant_id": "platform",
                "canonical_asset_id": deployment["canonical_asset_id"],
                "chain_id": deployment["chain_id"],
                "contract_or_mint": deployment["contract_or_mint"],
                "deployment_type": deployment.get("deployment_type", "unknown"),
            },
        ),
        Vertex(
            vertex_id=chain_vid,
            vertex_type=VertexType.CHAIN,
            properties={"tenant_id": "platform", "chain_id": deployment["chain_id"]},
        ),
    ]
    edges = [
        Edge(
            edge_type=EdgeType.DEPLOYED_ON_CHAIN,
            from_vertex_id=deployment_vid,
            to_vertex_id=chain_vid,
            properties=build_edge_properties(
                tenant_id="platform",
                edge_type=EdgeType.DEPLOYED_ON_CHAIN,
                from_vertex_id=deployment_vid,
                to_vertex_id=chain_vid,
                actor_kind="service",
                actor_id="stablecoin_registry",
                provenance=_PROVENANCE,
                valid_from=utc_now_iso(),
            ),
        ),
    ]
    return vertices, edges


def build_observation_mutations(observation: dict) -> tuple[list[Vertex], list[Edge]]:
    """Wallet-to-wallet TRANSFERRED_STABLECOIN (domain, excluded from actor
    layers) plus SENT_STABLECOIN_TO (H2H) when both entity refs resolve.
    Cross-tenant edges are structurally impossible: both endpoints inherit
    the observation's tenant."""
    tenant_id = observation["tenant_id"]
    vertices: list[Vertex] = []
    edges: list[Edge] = []

    from_wallet = observation.get("from_wallet_id") or observation.get("from_address")
    to_wallet = observation.get("to_wallet_id") or observation.get("to_address")
    if not (from_wallet and to_wallet):
        return vertices, edges

    from_vid = f"wallet:{from_wallet}"
    to_vid = f"wallet:{to_wallet}"
    for vid, addr in ((from_vid, from_wallet), (to_vid, to_wallet)):
        vertices.append(Vertex(
            vertex_id=vid,
            vertex_type=VertexType.WALLET,
            properties={"tenant_id": tenant_id, "address": addr},
        ))

    edges.append(Edge(
        edge_type=EdgeType.TRANSFERRED_STABLECOIN,
        from_vertex_id=from_vid,
        to_vertex_id=to_vid,
        properties=build_edge_properties(
            tenant_id=tenant_id,
            edge_type=EdgeType.TRANSFERRED_STABLECOIN,
            from_vertex_id=from_vid,
            to_vertex_id=to_vid,
            actor_kind="service",
            actor_id="stablecoin_observations",
            provenance=_PROVENANCE,
            valid_from=observation.get("observed_at") or utc_now_iso(),
            source_event_id=observation["observation_id"],
            amount_decimal=str(observation.get("amount_decimal", "")),
            deployment_id=observation.get("deployment_id", ""),
        ),
    ))

    from_ref: Any = observation.get("from_entity_ref")
    to_ref: Any = observation.get("to_entity_ref")
    if from_ref and to_ref and not _tenant_mismatch(from_ref, to_ref):
        from_entity_vid = f"entity:{from_ref['kind']}:{from_ref['id']}"
        to_entity_vid = f"entity:{to_ref['kind']}:{to_ref['id']}"
        edges.append(Edge(
            edge_type=EdgeType.SENT_STABLECOIN_TO,
            from_vertex_id=from_entity_vid,
            to_vertex_id=to_entity_vid,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.SENT_STABLECOIN_TO,
                from_vertex_id=from_entity_vid,
                to_vertex_id=to_entity_vid,
                actor_kind="human",
                actor_id=from_ref["id"],
                provenance=_PROVENANCE,
                valid_from=observation.get("observed_at") or utc_now_iso(),
                source_event_id=observation["observation_id"],
            ),
        ))
    return vertices, edges


def build_support_mutations(assertion: dict) -> tuple[list[Vertex], list[Edge]]:
    """SUPPORTS_ASSET edge from the asserting entity to the deployment."""
    tenant_id = assertion["tenant_id"]
    subject = assertion["subject_entity_ref"]
    subject_vid = f"entity:{subject['kind']}:{subject['id']}"
    deployment_vid = f"stablecoin_deployment:{assertion['deployment_id']}"
    vertices = [
        Vertex(
            vertex_id=subject_vid,
            vertex_type=VertexType.ORGANIZATION if subject["kind"] == "organization" else VertexType.ENTITY,
            properties={"tenant_id": tenant_id, "kind": subject["kind"]},
        ),
        Vertex(
            vertex_id=deployment_vid,
            vertex_type=VertexType.STABLECOIN_DEPLOYMENT,
            properties={"tenant_id": "platform"},
        ),
    ]
    edges = [
        Edge(
            edge_type=EdgeType.SUPPORTS_ASSET,
            from_vertex_id=subject_vid,
            to_vertex_id=deployment_vid,
            properties=build_edge_properties(
                tenant_id=tenant_id,
                edge_type=EdgeType.SUPPORTS_ASSET,
                from_vertex_id=subject_vid,
                to_vertex_id=deployment_vid,
                actor_kind="service",
                actor_id="stablecoin_support",
                provenance=_PROVENANCE,
                valid_from=utc_now_iso(),
                source_event_id=assertion["assertion_id"],
                capability=assertion.get("capability", ""),
                support_status=assertion.get("support_status", ""),
            ),
        ),
    ]
    return vertices, edges
