"""WP2.5: representative service-writer migrations route through the gateway.

Covers the DelegationProjector worker (a clean class handler); the sibling
route writers (flows / entities / delegation API) share the identical
edge_intent / vertex_intent path and are covered end-to-end by the existing
e2e + profile360 suites.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import shared.graph.mutation_gateway as mg
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from services.profile360_workers.workers import DelegationProjector
from shared.graph.graph import EdgeType, GraphClient
from shared.graph.mutation_gateway import current_graph_digest, replay_ledger

TENANT = "tenant_delegation_gw"


@pytest.fixture(autouse=True)
def _reset():
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()
    mg._shared_gateway = None


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


class _FakeDelegationRepo:
    async def find_by_id(self, delegation_id):
        return {
            "delegation_id": delegation_id,
            "tenant_id": TENANT,
            "grantor_entity_id": "grantor-1",
            "grantee_entity_id": "grantee-1",
            "starts_at": "2026-07-17T00:00:00+00:00",
            "ends_at": None,
            "revoked_at": None,
        }


def _event():
    return SimpleNamespace(payload={"delegation_id": "d1"}, tenant_id=TENANT)


@pytest.mark.asyncio
async def test_delegation_projector_ledgers_authorized_delegation(set_mode):
    set_mode("shadow")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    await DelegationProjector(graph=client, repo=_FakeDelegationRepo()).handle(_event())

    edges = await client.get_edges("grantor-1")
    assert [e.edge_type for e in edges] == [EdgeType.DELEGATES]

    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["operation"] == "edge_created"
    assert rows[0]["causality_class"] == "authorized_delegation"
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)


@pytest.mark.asyncio
async def test_delegation_projector_off_mode_no_ledger(set_mode):
    set_mode("off")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    await DelegationProjector(graph=client, repo=_FakeDelegationRepo()).handle(_event())
    assert len(await client.get_edges("grantor-1")) == 1
    assert await ledger.list_records(TENANT) == []


@pytest.mark.asyncio
async def test_agentic_observability_persist_mutations_ledgered(set_mode, monkeypatch):
    """foundation.persist_mutations routes node_created + edge_created writes."""
    from shared.graph.graph import Edge, Vertex

    set_mode("shadow")
    client = GraphClient()
    monkeypatch.setattr(
        "dependencies.providers.get_graph", lambda: client, raising=False
    )
    from services.agentic_observability import foundation

    vertex = Vertex("Agent", "agent-obs-1", {"tenant_id": TENANT})
    edge = Edge("OBSERVED", "agent-obs-1", "svc-1", {"tenant_id": TENANT})
    result = await foundation.persist_mutations([vertex, edge], tenant_id=TENANT)
    assert result.graph_mutations_persisted == 2

    rows = await GraphMutationLedgerRepository().list_records(TENANT)
    assert [r["operation"] for r in rows] == ["node_created", "edge_created"]
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)
