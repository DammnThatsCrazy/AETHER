"""Governed population membership (population360 P3.1).

Membership is a first-class graph fact: every join is a ``MEMBER_OF`` edge
(entity -> population) written through the ``GraphMutationGateway`` with
provenance on the edge *and* ledger vocabulary (``definition_version`` /
``membership_state`` / ``membership_basis`` / ``evidence_refs``), and a leave
is a soft-revoke (``edge_expired``) — never a hard delete. The
population-membership table row is the current-state materialisation the
governed path maintains; reads surface *active* memberships.

Suites pin: (1) the governed join writes the edge + ledger record + row;
(2) a duplicate join stays idempotent; (3) a leave revokes the edge and
transitions the row to ``left`` (row still present); (4) re-join after a leave
starts a fresh membership episode; (5) tenant isolation end to end.
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from shared.graph.graph import EdgeType, GraphClient
from services.population.governance import PopulationMembershipGovernor
from services.population.models import MembershipBasis, MembershipState, PopulationType
from services.population.registry import membership_repo, population_repo


@pytest.fixture(autouse=True)
def _reset_stores():
    """Start every test from empty in-memory repos + ledger."""
    population_repo._store.clear()
    membership_repo._store.clear()
    reset_graph_ledger_memory()
    yield
    population_repo._store.clear()
    membership_repo._store.clear()
    reset_graph_ledger_memory()


@pytest.fixture()
def enforce_mode(monkeypatch):
    """Pin the gateway mode ladder to ``enforce`` (ledger + facts written)."""
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


async def _population(tenant_id: str = "tenant_a") -> dict:
    return await population_repo.create_population(
        name="High-value segment",
        population_type=PopulationType.SEGMENT,
        definition={"filters": [{"field": "lifetime_value", "op": "gt", "value": 1000}]},
        source_tag="p3_test",
        tenant_id=tenant_id,
    )


# ── 1. Governed join ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_join_writes_governed_edge_ledger_and_row(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)

    row = await governor.add_membership(
        population=pop,
        entity_id="entity_1",
        entity_type="user",
        basis=MembershipBasis.RULE,
        confidence=0.9,
        reason="rule_match",
        source_tag="p3_test",
        tenant_id="tenant_a",
        evidence_refs=["evidence_rule_v1"],
    )

    # Materialised row is the governed current state.
    assert row["membership_state"] == MembershipState.ACTIVE.value
    assert row["status"] == MembershipState.ACTIVE.value
    assert row["definition_version"] == "1"
    assert row["evidence_refs"] == ["evidence_rule_v1"]

    # A MEMBER_OF edge landed on the graph with membership provenance.
    edges = await graph.get_edges(pop["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=True)
    assert len(edges) == 1
    props = edges[0].properties
    assert props["tenant_id"] == "tenant_a"
    assert props["membership_state"] == MembershipState.ACTIVE.value
    assert props["definition_version"] == "1"
    assert props["membership_basis"] == MembershipBasis.RULE.value
    assert props["population_type"] == PopulationType.SEGMENT.value
    assert props["evidence_refs"] == ["evidence_rule_v1"]

    # The ledger record carries the provenance too (edge vocabulary + record).
    records = await GraphMutationLedgerRepository().list_records("tenant_a")
    membership = [r for r in records if r.get("operation") == "edge_created"
                  and (r.get("payload") or {}).get("from_vertex_id") == "entity_1"]
    assert len(membership) == 1
    rec = membership[0]
    assert rec["evidence_refs"] == ["evidence_rule_v1"]
    assert rec["subject_id"] == "entity_1"
    assert (rec["payload"]["properties"]["definition_version"]) == "1"


@pytest.mark.asyncio
async def test_duplicate_join_is_idempotent(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)

    await governor.add_membership(population=pop, entity_id="entity_1",
                                  tenant_id="tenant_a")
    second = await governor.add_membership(population=pop, entity_id="entity_1",
                                           tenant_id="tenant_a")

    assert second["membership_state"] == MembershipState.ACTIVE.value
    edges = await graph.get_edges(pop["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=True)
    assert len(edges) == 1  # one active membership fact, no duplication
    active = [m for m in await membership_repo.get_members(pop["id"])]
    assert len(active) == 1
    assert await membership_repo.count_active_members(pop["id"]) == 1


# ── 3. Governed leave ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_leave_revokes_edge_and_transitions_row(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)

    await governor.add_membership(population=pop, entity_id="entity_1",
                                  tenant_id="tenant_a")
    row = await governor.remove_membership(population=pop, entity_id="entity_1",
                                           tenant_id="tenant_a",
                                           reason="churned")

    # Row is NOT deleted — it transitions to left (close-and-append honesty).
    assert row["membership_state"] == MembershipState.LEFT.value
    assert row["left_at"]
    assert row["leave_reason"] == "churned"

    # The active edge is soft-revoked, not hard-deleted.
    active = await graph.get_edges(pop["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=False)
    assert active == []
    revoked = await graph.get_edges(pop["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=True)
    assert len(revoked) == 1
    assert revoked[0].properties.get("revoked") is True
    assert revoked[0].properties.get("revoke_reason") == "churned"

    # Reads surface only *active* memberships.
    assert await membership_repo.count_active_members(pop["id"]) == 0
    assert await membership_repo.get_members(pop["id"]) == []
    assert await membership_repo.get_populations_for_entity("entity_1") == []


@pytest.mark.asyncio
async def test_rejoin_after_leave_starts_fresh_membership_episode(enforce_mode):
    graph = await _graph()
    pop = await _population("tenant_a")
    governor = PopulationMembershipGovernor(graph_client=graph)

    await governor.add_membership(population=pop, entity_id="entity_1",
                                  tenant_id="tenant_a", source_event_id="join_1")
    await governor.remove_membership(population=pop, entity_id="entity_1",
                                     tenant_id="tenant_a", reason="churned")
    rejoin = await governor.add_membership(population=pop, entity_id="entity_1",
                                           tenant_id="tenant_a",
                                           source_event_id="join_2")

    # Row reactivates (new joined_at; leave cleared).
    assert rejoin["membership_state"] == MembershipState.ACTIVE.value
    assert rejoin["left_at"] == ""
    assert rejoin["leave_reason"] == ""

    # One revoked episode + one live episode.
    all_edges = await graph.get_edges(pop["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=True)
    assert len(all_edges) == 2
    live = await graph.get_edges(pop["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=False)
    assert len(live) == 1
    assert live[0].properties.get("revoked") is None

    # Ledger shows join -> leave -> rejoin as three append-only facts.
    records = await GraphMutationLedgerRepository().list_records("tenant_a")
    ops = [r.get("operation") for r in records
           if (r.get("payload") or {}).get("from_vertex_id") == "entity_1"]
    assert ops == ["edge_created", "edge_expired", "edge_created"]


# ── 5. Tenant isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_end_to_end(enforce_mode):
    graph = await _graph()
    pop_a = await _population("tenant_a")
    pop_b = await _population("tenant_b")
    governor = PopulationMembershipGovernor(graph_client=graph)

    await governor.add_membership(population=pop_a, entity_id="entity_1",
                                  tenant_id="tenant_a")
    await governor.add_membership(population=pop_b, entity_id="entity_2",
                                  tenant_id="tenant_b")

    # Each tenant sees only its own memberships.
    assert await membership_repo.get_members(pop_a["id"]) != []
    assert await membership_repo.get_members(pop_b["id"]) != []
    for row in await membership_repo.get_members(pop_a["id"]):
        assert row["tenant_id"] == "tenant_a"
    for row in await membership_repo.get_members(pop_b["id"]):
        assert row["tenant_id"] == "tenant_b"

    # Edges carry the tenant; no cross-tenant edge matches.
    edges_a = await graph.get_edges(pop_a["id"], EdgeType.MEMBER_OF, direction="in", include_revoked=True)
    assert all(e.properties.get("tenant_id") == "tenant_a" for e in edges_a)

    # Ledger is tenant-scoped.
    assert len(await GraphMutationLedgerRepository().list_records("tenant_a")) == 1
    assert len(await GraphMutationLedgerRepository().list_records("tenant_b")) == 1
