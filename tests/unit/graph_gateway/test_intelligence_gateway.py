"""WP2.5: intelligence decision/outcome graph mutations route through the
canonical gateway — nodes as ``node_versioned``, edges as ``edge_created`` —
recorded in the ledger under shadow, with ledger replay matching the live
projection (parity). Off mode keeps behaviour identical with zero ledger writes.
"""

from __future__ import annotations

import pytest

from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from intelligence.intelligence.graph_mutations import upsert_outcome_graph
from shared.graph.graph import GraphClient
from shared.graph.mutation_gateway import current_graph_digest, replay_ledger

TENANT = "tenant_intel_gw"


@pytest.fixture(autouse=True)
def _reset():
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()


@pytest.fixture
def set_mode(monkeypatch):
    def _set(mode: str) -> None:
        import config.settings as settings_module

        monkeypatch.setattr(
            settings_module.settings,
            "temporal_observatory",
            settings_module.TemporalObservatoryConfig(mutation_gateway_mode=mode),
        )

    return _set


def _outcome() -> dict:
    return {
        "outcome_id": "outcome-1",
        "tenant_id": TENANT,
        "label": "converted",
        "action_id": "action-1",
        "recommendation_id": "rec-1",
        "confidence_delta": 0.1,
    }


@pytest.mark.asyncio
async def test_outcome_graph_is_ledgered(set_mode):
    set_mode("shadow")
    client = GraphClient()
    await upsert_outcome_graph(client, _outcome())

    rows = await GraphMutationLedgerRepository().list_records(TENANT)
    ops = [r["operation"] for r in rows]
    # One vertex (node_versioned) + two edges (edge_created).
    assert ops == ["node_versioned", "edge_created", "edge_created"]
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)


@pytest.mark.asyncio
async def test_outcome_graph_off_mode_no_ledger(set_mode):
    set_mode("off")
    client = GraphClient()
    await upsert_outcome_graph(client, _outcome())
    # Projection still happened: PRODUCED edge exists out of the outcome vertex.
    assert await client.get_edges("outcome-1")
    assert await GraphMutationLedgerRepository().list_records(TENANT) == []


def _recommendation(tenant: str, rec_id: str) -> dict:
    return {
        "recommendation_id": rec_id,
        "tenant_id": tenant,
        "entity_id": f"{tenant}-entity",
        "evidence": [
            {"source_type": "profile_signal", "source_id": "profile360:shared-entity"},
            {"source_type": "edge", "source_id": "graph:shared-entity"},
            {"source_type": "policy", "source_id": "policy:churn_risk"},
        ],
    }


def _graph() -> GraphClient:
    from shared.graph.graph import _InMemoryGraphBackend

    client = GraphClient()
    client._backend = _InMemoryGraphBackend()  # noqa: SLF001
    return client


async def _supported_by(client: GraphClient, rec_id: str) -> list[str]:
    return sorted(e.to_vertex_id for e in await client.get_edges(rec_id, "SUPPORTED_BY", "out"))


@pytest.mark.asyncio
async def test_tenants_sharing_evidence_ids_each_get_their_own_vertices(set_mode):
    set_mode("off")
    client = _graph()
    from intelligence.intelligence.graph_mutations import upsert_recommendation_graph

    for tenant in ("tenant-a", "tenant-b"):
        await upsert_recommendation_graph(client, _recommendation(tenant, f"rec-{tenant}"))

    for tenant in ("tenant-a", "tenant-b"):
        expected = sorted(f"{tenant}:{source}" for source in (
            "graph:shared-entity", "policy:churn_risk", "profile360:shared-entity",
        ))
        assert await _supported_by(client, f"rec-{tenant}") == expected
        for vertex_id in expected:
            assert (await client.get_vertex(vertex_id)).properties["tenant_id"] == tenant


@pytest.mark.asyncio
async def test_a_refused_evidence_vertex_is_counted_and_only_its_edge_skipped(set_mode, monkeypatch):
    set_mode("off")
    client = _graph()
    from intelligence.intelligence import graph_mutations
    from shared.graph.graph import Vertex, VertexType

    counted: list[tuple] = []
    monkeypatch.setattr(
        graph_mutations.metrics, "increment",
        lambda name, *a, **k: counted.append((name, k.get("labels"))),
    )
    await client.add_vertex(Vertex(
        VertexType.POLICY_DECISION, "tenant-a:policy:churn_risk", {"tenant_id": "tenant-z"},
    ))

    await graph_mutations.upsert_recommendation_graph(client, _recommendation("tenant-a", "rec-a"))

    assert await _supported_by(client, "rec-a") == [
        "tenant-a:graph:shared-entity", "tenant-a:profile360:shared-entity",
    ]
    assert counted == [("intelligence_graph_vertex_conflict_total", {"kind": "evidence"})]
