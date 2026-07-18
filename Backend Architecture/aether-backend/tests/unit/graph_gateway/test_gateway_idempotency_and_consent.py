"""Enforce-mode gateway regression tests for PR-2 review batch 2.

Two properties this suite pins down:

1. **Idempotency distinctness** — two *distinct* observations of the same
   relationship (same tenant / edge_type / from / to) that carry different
   ``source_event_id`` values must BOTH project; only a genuine replay (same
   ``source_event_id``) is deduplicated. This is the class of bug that dropped
   the 2nd+ transfer / import / outbox / lifecycle edge before this batch.

2. **H2A/A2H consent gating** — an H2A/A2H edge without ``consent_purpose`` is
   rejected by enforce-mode validation, and passes once a valid registry
   ``consent_purpose`` is stamped (the finding #6 fix on agent registration).
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import reset_graph_ledger_memory
from shared.graph.graph import Edge, EdgeType, GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway
from shared.graph.mutation_intents import edge_intent
from shared.graph.write_validator import GraphWriteValidationError


@pytest.fixture(autouse=True)
def _reset_ledger():
    """Every test starts against an empty in-memory ledger."""
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()


@pytest.fixture()
def enforce_mode(monkeypatch):
    """Pin the gateway mode ladder to ``enforce`` for the duration of a test."""
    monkeypatch.setattr(
        settings,
        "temporal_observatory",
        dataclasses.replace(
            settings.temporal_observatory, mutation_gateway_mode="enforce"
        ),
    )
    return "enforce"


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


def _edge(edge_type: str, frm: str, to: str, **props) -> Edge:
    return Edge(
        edge_type=edge_type,
        from_vertex_id=frm,
        to_vertex_id=to,
        properties={"tenant_id": "tenant_a", **props},
    )


# ── 1. Idempotency distinctness ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_distinct_source_events_both_project(enforce_mode):
    """Same (tenant, type, from, to), different source_event_id → both apply."""
    gateway = GraphMutationGateway(graph_client=await _graph())

    first = await gateway.apply(
        edge_intent(
            _edge(EdgeType.HIRED, "agent_1", "agent_2"),
            operation="edge_created",
            tenant_id="tenant_a",
            actor_kind="agent",
            actor_id="agent_1",
            source_event_id="call_evt_1",
        )
    )
    second = await gateway.apply(
        edge_intent(
            _edge(EdgeType.HIRED, "agent_1", "agent_2"),
            operation="edge_created",
            tenant_id="tenant_a",
            actor_kind="agent",
            actor_id="agent_1",
            source_event_id="call_evt_2",
        )
    )

    assert first.applied and not first.deduplicated
    assert second.applied and not second.deduplicated
    # Distinct observations must land on distinct idempotency keys / ledger rows.
    assert first.record.idempotency_key != second.record.idempotency_key
    assert first.mutation_id != second.mutation_id


@pytest.mark.asyncio
async def test_replayed_source_event_is_deduplicated(enforce_mode):
    """Same (tenant, type, from, to) AND same source_event_id → 2nd dedups."""
    gateway = GraphMutationGateway(graph_client=await _graph())

    def _intent():
        return edge_intent(
            _edge(EdgeType.HIRED, "agent_1", "agent_2"),
            operation="edge_created",
            tenant_id="tenant_a",
            actor_kind="agent",
            actor_id="agent_1",
            source_event_id="call_evt_same",
        )

    first = await gateway.apply(_intent())
    second = await gateway.apply(_intent())

    assert first.applied and not first.deduplicated
    assert second.deduplicated and not second.applied


# ── 2. H2A/A2H consent gating ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_h2a_edge_without_consent_purpose_is_rejected(enforce_mode):
    """A DELEGATES (H2A) edge lacking consent_purpose fails enforce validation."""
    gateway = GraphMutationGateway(graph_client=await _graph())

    with pytest.raises(GraphWriteValidationError) as excinfo:
        await gateway.apply(
            edge_intent(
                _edge(EdgeType.DELEGATES, "user_1", "agent_1"),
                operation="edge_created",
                tenant_id="tenant_a",
                actor_kind="human",
                actor_id="user_1",
                source_event_id="deleg_1",
            )
        )
    assert any("consent_purpose" in v for v in excinfo.value.violations)


@pytest.mark.asyncio
async def test_h2a_edge_with_consent_purpose_passes(enforce_mode):
    """Stamping a valid registry consent_purpose lets the H2A edge project."""
    gateway = GraphMutationGateway(graph_client=await _graph())

    outcome = await gateway.apply(
        edge_intent(
            _edge(
                EdgeType.DELEGATES,
                "user_1",
                "agent_1",
                consent_purpose="agent",
            ),
            operation="edge_created",
            tenant_id="tenant_a",
            actor_kind="human",
            actor_id="user_1",
            source_event_id="deleg_1",
        )
    )

    assert outcome.applied and not outcome.deduplicated
    assert outcome.record.idempotency_key


# ── 3. Lifecycle mapper per-event key derivation (finding #5) ─────────────────


def test_lifecycle_edge_source_event_id_is_distinct_per_event():
    """CALLED_TOOL edges differing only in per-event metadata get distinct keys,
    and an identical event resolves to the same key (safe replay)."""
    from services.agent.lifecycle_mapper import AgentLifecycleMapper

    def _called_tool(execution_id: str, called_at: str) -> Edge:
        return Edge(
            edge_type=EdgeType.CALLED_TOOL,
            from_vertex_id="tenant_a:agent:a1",
            to_vertex_id="tenant_a:tool:t1",
            properties={
                "tenant_id": "tenant_a",
                "called_at": called_at,
                "task_id": "task_1",
                "execution_id": execution_id,
            },
        )

    k1 = AgentLifecycleMapper._edge_source_event_id(
        _called_tool("exec_1", "2026-01-01T00:00:00Z")
    )
    k2 = AgentLifecycleMapper._edge_source_event_id(
        _called_tool("exec_2", "2026-01-01T00:00:05Z")
    )
    k1_again = AgentLifecycleMapper._edge_source_event_id(
        _called_tool("exec_1", "2026-01-01T00:00:00Z")
    )

    assert k1 and k2 and k1 != k2
    assert k1 == k1_again  # identical event → same key (replay dedups)

    # Only tenant_id present → nothing distinguishing → natural identity kept.
    bare = Edge(
        edge_type=EdgeType.CALLED_TOOL,
        from_vertex_id="tenant_a:agent:a1",
        to_vertex_id="tenant_a:tool:t1",
        properties={"tenant_id": "tenant_a"},
    )
    assert AgentLifecycleMapper._edge_source_event_id(bare) is None
