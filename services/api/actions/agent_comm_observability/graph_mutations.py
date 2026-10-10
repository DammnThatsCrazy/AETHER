"""Graph mutations for agent communication observations."""
from __future__ import annotations

from shared.graph.graph import Edge, EdgeType, Vertex, VertexType


def build_inbox_mutations(tenant_id: str, inbox_id: str, agent_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.AGENT_INBOX_OBSERVED,
        vertex_id=inbox_id,
        properties={"tenant_id": tenant_id},
    ))
    if agent_id:
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_HAS_INBOX,
            from_vertex_id=agent_id,
            to_vertex_id=inbox_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_message_mutations(tenant_id: str, message_id: str, thread_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.AGENT_MESSAGE_OBSERVED,
        vertex_id=message_id,
        properties={"tenant_id": tenant_id},
    ))
    if thread_id:
        mutations.append(Edge(
            edge_type=EdgeType.THREAD_CONTAINS_MESSAGE,
            from_vertex_id=thread_id,
            to_vertex_id=message_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_extraction_mutations(tenant_id: str, entity_id: str, message_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.EXTRACTED_ENTITY_OBSERVED,
        vertex_id=entity_id,
        properties={"tenant_id": tenant_id},
    ))
    if message_id:
        mutations.append(Edge(
            edge_type=EdgeType.MESSAGE_EXTRACTED_ENTITY,
            from_vertex_id=message_id,
            to_vertex_id=entity_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations
