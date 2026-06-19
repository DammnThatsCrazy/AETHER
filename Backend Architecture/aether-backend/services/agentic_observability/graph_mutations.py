"""Graph mutations for agentic observability events."""
from __future__ import annotations

from typing import Optional

from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from services.agentic_observability.models import AgenticObservationRecord


def build_mutations(record: AgenticObservationRecord) -> list:
    """Build graph mutations for an agentic observation record."""
    mutations: list = []
    agent_id = record.actor.actor_id or (record.agent.agent_id if record.agent else None)
    obj_id = record.object.object_id

    if record.event_name == "agent_mcp_connection_observed" and agent_id and obj_id:
        mutations.append(Vertex(
            vertex_type=VertexType.MCP_CONNECTION,
            vertex_id=obj_id,
            properties={"tenant_id": record.tenant_id, "observed_at": record.observed_at},
        ))
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_CONNECTED_VIA_MCP,
            from_vertex_id=agent_id,
            to_vertex_id=obj_id,
            properties={"tenant_id": record.tenant_id},
        ))

    elif record.event_name in ("agent_tool_observed", "agent_tool_invocation_observed") and agent_id and obj_id:
        mutations.append(Vertex(
            vertex_type=VertexType.AGENT_TOOL_OBS,
            vertex_id=obj_id,
            properties={"tool_name": record.object.object_type, "tenant_id": record.tenant_id},
        ))
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_USED_TOOL_OBS,
            from_vertex_id=agent_id,
            to_vertex_id=obj_id,
            properties={"tenant_id": record.tenant_id},
        ))

    elif record.event_name in ("agent_activity_observed", "agent_task_observed") and agent_id and obj_id:
        mutations.append(Vertex(
            vertex_type=VertexType.AGENT_ACTIVITY,
            vertex_id=obj_id,
            properties={"tenant_id": record.tenant_id, "observed_at": record.observed_at},
        ))
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_TRIGGERED_ACTIVITY,
            from_vertex_id=agent_id,
            to_vertex_id=obj_id,
            properties={"tenant_id": record.tenant_id},
        ))

    elif record.event_name == "agent_risk_signal_observed" and agent_id and obj_id:
        mutations.append(Vertex(
            vertex_type=VertexType.AGENT_RISK_SIGNAL,
            vertex_id=obj_id,
            properties={
                "tenant_id": record.tenant_id,
                "risk_level": record.risk.risk_level.value if record.risk and record.risk.risk_level else "low",
            },
        ))
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_PRODUCED_RISK_SIGNAL,
            from_vertex_id=agent_id,
            to_vertex_id=obj_id,
            properties={"tenant_id": record.tenant_id},
        ))

    return mutations


def build_account_mutations(tenant_id: str, agent_id: Optional[str], account_id: str) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.EXTERNAL_AGENTIC_ACCOUNT,
        vertex_id=account_id,
        properties={"tenant_id": tenant_id},
    ))
    if agent_id:
        mutations.append(Edge(
            edge_type=EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT,
            from_vertex_id=agent_id,
            to_vertex_id=account_id,
            properties={"tenant_id": tenant_id},
        ))
    return mutations
