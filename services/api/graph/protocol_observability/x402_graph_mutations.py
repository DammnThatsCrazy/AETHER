"""Graph mutations for x402 protocol observations."""
from __future__ import annotations

from shared.graph.graph import Edge, EdgeType, Vertex, VertexType


def build_interaction_mutations(tenant_id: str, interaction_id: str, agent_id: str | None, resource_url: str) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_INTERACTION_OBSERVED,
        vertex_id=interaction_id,
        properties={"tenant_id": tenant_id, "resource_url": resource_url},
    ))
    if agent_id:
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_REQUESTED_RESOURCE_OBS,
            from_vertex_id=agent_id,
            to_vertex_id=interaction_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_challenge_mutations(tenant_id: str, challenge_id: str, interaction_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_CHALLENGE_OBSERVED,
        vertex_id=challenge_id,
        properties={"tenant_id": tenant_id},
    ))
    if interaction_id:
        mutations.append(Edge(
            edge_type=EdgeType.RESOURCE_RETURNED_X402_CHALLENGE,
            from_vertex_id=interaction_id,
            to_vertex_id=challenge_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_settlement_mutations(tenant_id: str, settlement_id: str, interaction_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_SETTLEMENT_OBSERVED,
        vertex_id=settlement_id,
        properties={"tenant_id": tenant_id, "execution_by_aether": "false"},
    ))
    if interaction_id:
        mutations.append(Edge(
            edge_type=EdgeType.INTERACTION_HAS_SETTLEMENT_OBSERVED,
            from_vertex_id=interaction_id,
            to_vertex_id=settlement_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_requirement_mutations(tenant_id: str, requirement_id: str, challenge_obs_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_PAYMENT_REQUIREMENT_OBSERVED,
        vertex_id=requirement_id,
        properties={"tenant_id": tenant_id},
    ))
    if challenge_obs_id:
        mutations.append(Edge(
            edge_type=EdgeType.CHALLENGE_HAS_PAYMENT_REQUIREMENT,
            from_vertex_id=challenge_obs_id,
            to_vertex_id=requirement_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_signature_mutations(tenant_id: str, signature_id: str, interaction_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_SIGNATURE_OBSERVED,
        vertex_id=signature_id,
        properties={"tenant_id": tenant_id, "execution_by_aether": "false"},
    ))
    if interaction_id:
        mutations.append(Edge(
            edge_type=EdgeType.INTERACTION_HAS_SIGNATURE_OBSERVED,
            from_vertex_id=interaction_id,
            to_vertex_id=signature_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_verification_mutations(tenant_id: str, verification_id: str, interaction_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_VERIFICATION_OBSERVED,
        vertex_id=verification_id,
        properties={"tenant_id": tenant_id},
    ))
    if interaction_id:
        mutations.append(Edge(
            edge_type=EdgeType.INTERACTION_HAS_VERIFICATION_OBSERVED,
            from_vertex_id=interaction_id,
            to_vertex_id=verification_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_resource_access_mutations(tenant_id: str, access_id: str, interaction_id: str | None, access_granted: bool) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.X402_RESOURCE_ACCESS_OBSERVED,
        vertex_id=access_id,
        properties={"tenant_id": tenant_id, "access_granted": str(access_granted)},
    ))
    if interaction_id:
        mutations.append(Edge(
            edge_type=EdgeType.INTERACTION_HAS_RESOURCE_ACCESS_OUTCOME,
            from_vertex_id=interaction_id,
            to_vertex_id=access_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations
