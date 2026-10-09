from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.onchain.action_recorder import ActionRecorder
from services.onchain.models import ActionRecord, ActionType
from shared.graph.graph import GraphClient, Vertex, VertexType
from shared.common.common import BadRequestError, ConflictError, ServiceUnavailableError


class _Graph:
    def __init__(self) -> None:
        self.vertices: list[Vertex] = []

    async def get_vertices_for_tenant(self, tenant_id: str, limit: int = 1000, *, vertex_type=None):
        return [
            vertex for vertex in self.vertices
            if vertex.properties.get("tenantId") == tenant_id
            and (vertex_type is None or vertex.vertex_type == vertex_type)
        ][:limit]


class _Gateway:
    def __init__(self, graph: _Graph, outcomes=None) -> None:
        self.graph = graph
        self.intents = []
        self.outcomes = list(outcomes or [])

    async def apply(self, intent):
        self.intents.append(intent)
        outcome = self.outcomes.pop(0) if self.outcomes else SimpleNamespace(
            applied=True, deduplicated=False, blocked=False, violations=[]
        )
        if intent.vertex and (outcome.applied or outcome.deduplicated):
            self.graph.vertices.append(intent.vertex)
        return outcome


class _Producer:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, _event):
        self.events.append(_event)
        return None


@pytest.mark.asyncio
async def test_record_uses_gateway_with_tenant_qualified_ids_and_stable_source_identity():
    graph = _Graph()
    gateway = _Gateway(graph)
    producer = _Producer()
    recorder = ActionRecorder(graph_client=graph, mutation_gateway=gateway, event_producer=producer)
    action = ActionRecord(
        action_id="action-1",
        agent_id="agent-1",
        action_type=ActionType.DEPLOY,
        chain_id="1",
        tx_hash="0xABC",
        contract_address="0xDEF",
    )

    await recorder.record(action, tenant_id="tenant-a")

    assert [intent.operation for intent in gateway.intents] == [
        "node_versioned", "edge_created", "node_versioned", "edge_created"
    ]
    assert all(intent.tenant_id == "tenant-a" for intent in gateway.intents)
    assert gateway.intents[0].vertex.vertex_id == "tenant-a:action-1"
    assert gateway.intents[0].source_event_id == f"onchain:1:0xabc:{action.action_id}"
    assert gateway.intents[1].edge.from_vertex_id == "tenant-a:agent-1"
    assert gateway.intents[2].vertex.vertex_id == "tenant-a:contract:1:0xdef"
    assert producer.events[0].tenant_id == "tenant-a"
    assert await recorder.get_agent_actions("agent-1", tenant_id="tenant-a")
    assert not await recorder.get_agent_actions("agent-1", tenant_id="tenant-b")


@pytest.mark.asyncio
async def test_contract_reads_are_tenant_scoped_and_missing_tenant_is_rejected():
    graph = _Graph()
    graph.vertices.append(Vertex(
        vertex_type=VertexType.CONTRACT,
        vertex_id="tenant-a:contract:1:0xdef",
        properties={"tenantId": "tenant-a", "address": "0xDEF", "chain_id": "1"},
    ))
    recorder = ActionRecorder(graph_client=graph, event_producer=_Producer())

    assert await recorder.get_contract_info("0xdef", tenant_id="tenant-a")
    assert await recorder.get_contract_info("0xdef", tenant_id="tenant-b") is None
    with pytest.raises(ValueError, match="tenant_id is required"):
        await recorder.get_agent_actions("agent-1", tenant_id="")


@pytest.mark.asyncio
async def test_replay_identity_is_stable_when_timestamp_changes():
    graph = _Graph()
    gateway = _Gateway(graph)
    recorder = ActionRecorder(graph_client=graph, mutation_gateway=gateway, event_producer=_Producer())
    first = ActionRecord(agent_id="agent-1", action_type=ActionType.CALL, chain_id="1", tx_hash="0xABC", timestamp="2026-01-01T00:00:00Z")
    second = first.model_copy(update={"timestamp": "2026-01-02T00:00:00Z", "tx_hash": " 0xabc "})

    await recorder.record(first, tenant_id="tenant-a")
    first_key = gateway.intents[0].idempotency_key
    await recorder.record(second, tenant_id="tenant-a")

    assert first.action_id == second.action_id
    assert gateway.intents[2].idempotency_key == first_key


@pytest.mark.asyncio
async def test_missing_transaction_and_action_identity_is_rejected():
    recorder = ActionRecorder(graph_client=_Graph(), event_producer=_Producer())
    action = ActionRecord(agent_id="agent-1", action_type=ActionType.CALL, chain_id="1")

    with pytest.raises(BadRequestError, match="action_id or tx_hash is required"):
        await recorder.record(action, tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_blocked_gateway_outcome_fails_before_event_publish_but_dedup_is_accepted():
    graph = _Graph()
    producer = _Producer()
    blocked_gateway = _Gateway(graph, outcomes=[SimpleNamespace(
        applied=False, deduplicated=False, blocked=True, violations=["consent denied"]
    )])
    recorder = ActionRecorder(graph_client=graph, mutation_gateway=blocked_gateway, event_producer=producer)
    action = ActionRecord(action_id="stable", agent_id="agent-1", action_type=ActionType.CALL, chain_id="1")

    with pytest.raises(ConflictError, match="consent denied"):
        await recorder.record(action, tenant_id="tenant-a")
    assert producer.events == []

    dedup_gateway = _Gateway(graph, outcomes=[SimpleNamespace(
        applied=False, deduplicated=True, blocked=False, violations=[]
    )])
    recorder = ActionRecorder(graph_client=graph, mutation_gateway=dedup_gateway, event_producer=producer)
    await recorder.record(action, tenant_id="tenant-a")
    assert len(producer.events) == 1


@pytest.mark.asyncio
async def test_contract_chain_selector_disambiguates_and_limits_call_count():
    graph = _Graph()
    for chain in ("1", "10"):
        graph.vertices.append(Vertex(
            vertex_type=VertexType.CONTRACT,
            vertex_id=f"tenant-a:contract:{chain}:0xdef",
            properties={"tenantId": "tenant-a", "address": "0xDEF", "chain_id": chain},
        ))
        graph.vertices.append(Vertex(
            vertex_type=VertexType.ACTION_RECORD,
            vertex_id=f"tenant-a:call:{chain}",
            properties={
                "tenantId": "tenant-a", "agent_id": "agent-1", "action_id": f"call-{chain}",
                "action_type": ActionType.CALL, "chain_id": chain, "contract_address": "0xDEF",
            },
        ))
    recorder = ActionRecorder(graph_client=graph, event_producer=_Producer())

    with pytest.raises(ConflictError, match="provide chain_id"):
        await recorder.get_contract_info("0xdef", tenant_id="tenant-a")
    info = await recorder.get_contract_info("0xdef", tenant_id="tenant-a", chain_id="10")
    assert info is not None and info.chain_id == "10" and info.call_count == 1


@pytest.mark.asyncio
async def test_distinct_explicit_actions_without_transaction_keep_distinct_edge_identity():
    graph = _Graph()
    gateway = _Gateway(graph)
    recorder = ActionRecorder(graph_client=graph, mutation_gateway=gateway, event_producer=_Producer())
    for action_id in ("call-1", "call-2"):
        await recorder.record(ActionRecord(
            action_id=action_id, agent_id="agent-1", action_type=ActionType.CALL,
            chain_id="1", contract_address="0xDEF",
        ), tenant_id="tenant-a")

    call_edges = [intent for intent in gateway.intents if intent.edge and intent.edge.edge_type == "CALLED"]
    assert len(call_edges) == 2
    assert call_edges[0].source_event_id != call_edges[1].source_event_id
    assert call_edges[0].edge.properties["idempotency_key"] != call_edges[1].edge.properties["idempotency_key"]


@pytest.mark.asyncio
async def test_tenant_graph_read_refuses_silent_truncation():
    graph = _Graph()
    graph.vertices.extend(Vertex(
        vertex_type=VertexType.ACTION_RECORD,
        vertex_id=f"tenant-a:action-{index}",
        properties={"tenantId": "tenant-a", "agent_id": "agent-1"},
    ) for index in range(1001))
    recorder = ActionRecorder(graph_client=graph, event_producer=_Producer())

    with pytest.raises(ServiceUnavailableError):
        await recorder.get_agent_actions("agent-1", tenant_id="tenant-a")


@pytest.mark.asyncio
async def test_real_local_graph_projection_is_tenant_scoped(monkeypatch):
    from shared.graph import mutation_gateway

    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.delenv("NEPTUNE_ENDPOINT", raising=False)
    monkeypatch.setattr(mutation_gateway, "_gateway_mode", lambda: "off")
    graph = GraphClient()
    recorder = ActionRecorder(graph_client=graph, event_producer=_Producer())
    try:
        await recorder.record(ActionRecord(
            agent_id="agent-1", action_type=ActionType.DEPLOY, chain_id="1",
            tx_hash="0xABC", contract_address="0xDEF",
        ), tenant_id="tenant-a")
        assert len(await recorder.get_agent_actions("agent-1", tenant_id="tenant-a")) == 1
        assert await recorder.get_agent_actions("agent-1", tenant_id="tenant-b") == []
        assert await recorder.get_contract_info("0xdef", tenant_id="tenant-a") is not None
        assert await recorder.get_contract_info("0xdef", tenant_id="tenant-b") is None
    finally:
        await graph.close()
