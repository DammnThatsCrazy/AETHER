"""Graph mutations for external account observations."""
from __future__ import annotations

from shared.graph.graph import Edge, EdgeType, Vertex, VertexType


def build_account_mutations(tenant_id: str, account_id: str, agent_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.EXTERNAL_AGENTIC_ACCOUNT,
        vertex_id=account_id,
        properties={"tenant_id": tenant_id, "execution_by_aether": "false"},
    ))
    if agent_id:
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT,
            from_vertex_id=agent_id,
            to_vertex_id=account_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_brokerage_mutations(tenant_id: str, brokerage_id: str, agent_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.EXTERNAL_BROKERAGE_ACCOUNT,
        vertex_id=brokerage_id,
        properties={"tenant_id": tenant_id, "execution_by_aether": "false"},
    ))
    if agent_id:
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT,
            from_vertex_id=agent_id,
            to_vertex_id=brokerage_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_trade_intent_mutations(tenant_id: str, intent_id: str, agent_id: str | None, brokerage_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.TRADE_INTENT_OBSERVED,
        vertex_id=intent_id,
        properties={"tenant_id": tenant_id, "execution_by_aether": "false"},
    ))
    if agent_id:
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_GENERATED_TRADE_INTENT,
            from_vertex_id=agent_id,
            to_vertex_id=intent_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_order_mutations(tenant_id: str, order_id: str, brokerage_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.TRADE_ORDER_OBSERVED,
        vertex_id=order_id,
        properties={"tenant_id": tenant_id, "execution_by_aether": "false"},
    ))
    if brokerage_id:
        mutations.append(Edge(
            edge_type=EdgeType.EXTERNAL_ACCOUNT_OBSERVED_ORDER,
            from_vertex_id=brokerage_id,
            to_vertex_id=order_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations


def build_portfolio_mutations(tenant_id: str, portfolio_id: str, brokerage_id: str | None) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.PORTFOLIO_SNAPSHOT_OBSERVED,
        vertex_id=portfolio_id,
        properties={"tenant_id": tenant_id},
    ))
    if brokerage_id:
        mutations.append(Edge(
            edge_type=EdgeType.EXTERNAL_ACCOUNT_OBSERVED_PORTFOLIO,
            from_vertex_id=brokerage_id,
            to_vertex_id=portfolio_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations
