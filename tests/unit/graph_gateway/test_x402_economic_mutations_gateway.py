"""WP2.5: x402 EconomicGraphMutations route commerce writes through the gateway.

Exercised via write_agent_economic_identity (model-free): two node_versioned
upserts + one edge_created, ledgered under shadow with replay==live digest.
"""

from __future__ import annotations

import pytest

from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from services.x402.economic_mutations import EconomicGraphMutations
from shared.graph.graph import GraphClient
from shared.graph.mutation_gateway import current_graph_digest, replay_ledger

TENANT = "tenant_x402_econ_gw"


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


@pytest.mark.asyncio
async def test_economic_identity_is_ledgered(set_mode):
    set_mode("shadow")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    mut = EconomicGraphMutations(graph_client=client)
    await mut.write_agent_economic_identity("agent-9", TENANT, {"reputation": "high"})

    rows = await ledger.list_records(TENANT)
    assert [r["operation"] for r in rows] == [
        "node_versioned", "node_versioned", "edge_created",
    ]
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)


@pytest.mark.asyncio
async def test_economic_identity_off_mode_no_ledger(set_mode):
    set_mode("off")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    mut = EconomicGraphMutations(graph_client=client)
    await mut.write_agent_economic_identity("agent-9", TENANT, None)
    # Projection still happened (edge exists out of the tenant-scoped agent vertex).
    assert await client.get_edges(f"{TENANT}:agent-9")
    assert await ledger.list_records(TENANT) == []
