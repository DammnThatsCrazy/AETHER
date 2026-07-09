"""Graph mutations for agentic observability events."""
from __future__ import annotations

from typing import Optional

from config.settings import settings
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, EdgeType, Vertex, VertexType
from services.agentic_observability.models import AgenticObservationRecord


def _edge_props(
    record: AgenticObservationRecord,
    edge_type: str,
    from_vertex_id: str,
    to_vertex_id: str,
) -> dict:
    actor_id = record.actor.actor_id or (record.agent.agent_id if record.agent else "unknown")
    return build_edge_properties(
        tenant_id=record.tenant_id,
        edge_type=edge_type,
        from_vertex_id=from_vertex_id,
        to_vertex_id=to_vertex_id,
        actor_kind="agent",
        actor_id=actor_id,
        provenance="agentic_observability",
        valid_from=record.observed_at,
        confidence=0.9,
        source_event_id=record.observation_id,
    )


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
            properties=_edge_props(record, EdgeType.AGENT_CONNECTED_VIA_MCP, agent_id, obj_id),
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
            properties=_edge_props(record, EdgeType.AGENT_USED_TOOL_OBS, agent_id, obj_id),
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
            properties=_edge_props(record, EdgeType.AGENT_TRIGGERED_ACTIVITY, agent_id, obj_id),
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
            properties=_edge_props(record, EdgeType.AGENT_PRODUCED_RISK_SIGNAL, agent_id, obj_id),
        ))

    # External Agent Telemetry Plane V1: aggregate deployment projection.
    # One DEPLOYMENT vertex per registry deployment, never per-event vertices.
    if (
        settings.external_agent_telemetry.graph_enabled
        and record.deployment_id
        and agent_id
    ):
        mutations.extend(
            build_deployment_mutations(record.tenant_id, agent_id, record.deployment_id)
        )

    return mutations


def build_account_mutations(tenant_id: str, agent_id: Optional[str], account_id: str) -> list:
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.EXTERNAL_AGENTIC_ACCOUNT,
        vertex_id=account_id,
        properties={"tenant_id": tenant_id},
    ))
    if agent_id:
        from datetime import datetime, timezone
        from shared.graph.edge_properties import make_edge_idempotency_key, SCHEMA_VERSION
        et = EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT
        mutations.append(Edge(
            edge_type=et,
            from_vertex_id=agent_id,
            to_vertex_id=account_id,
            properties={
                "tenant_id": tenant_id,
                "idempotency_key": make_edge_idempotency_key(tenant_id, et, agent_id, account_id),
                "actor_kind": "agent",
                "actor_id": agent_id,
                "schema_version": SCHEMA_VERSION,
                "provenance": "agentic_observability",
                "valid_from": datetime.now(timezone.utc).isoformat(),
                "confidence": "0.9",
            },
        ))
    return mutations


def build_deployment_mutations(tenant_id: str, agent_id: Optional[str], deployment_id: str) -> list:
    """Aggregate deployment → agent projection (External Agent Telemetry V1).

    Reuses the ExternalAgenticAccount vertex / AGENT_LINKED_TO_EXTERNAL_ACCOUNT
    edge with kind="agent_deployment" rather than adding new graph types. The
    idempotency key excludes any source event so repeated observations converge
    on a single vertex and edge per (agent, deployment) pair.
    """
    mutations: list = []
    mutations.append(Vertex(
        vertex_type=VertexType.EXTERNAL_AGENTIC_ACCOUNT,
        vertex_id=deployment_id,
        properties={"tenant_id": tenant_id, "kind": "agent_deployment"},
    ))
    if agent_id:
        from datetime import datetime, timezone
        from shared.graph.edge_properties import make_edge_idempotency_key, SCHEMA_VERSION
        et = EdgeType.AGENT_LINKED_TO_EXTERNAL_ACCOUNT
        mutations.append(Edge(
            edge_type=et,
            from_vertex_id=agent_id,
            to_vertex_id=deployment_id,
            properties={
                "tenant_id": tenant_id,
                "idempotency_key": make_edge_idempotency_key(tenant_id, et, agent_id, deployment_id),
                "actor_kind": "agent",
                "actor_id": agent_id,
                "schema_version": SCHEMA_VERSION,
                "provenance": "agentic_observability",
                "valid_from": datetime.now(timezone.utc).isoformat(),
                "confidence": "0.9",
                "kind": "agent_deployment",
            },
        ))
    return mutations
