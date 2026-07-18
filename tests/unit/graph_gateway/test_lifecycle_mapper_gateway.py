"""WP2.5: AgentLifecycleMapper routes lifecycle projections through the gateway.

agent_registered with an owner emits AGENT node_versioned + USER node_versioned
+ OWNS_AGENT edge_created; shadow ledgers all three and replays to the live
digest. Off mode keeps behaviour identical with zero ledger writes.
"""

from __future__ import annotations

import pytest

from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from repositories.repos import reset_in_memory_stores
from services.agent.lifecycle_mapper import AgentLifecycleMapper
from shared.graph.graph import GraphClient
from shared.graph.mutation_gateway import current_graph_digest, replay_ledger

TENANT = "tenant_lifecycle_gw"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    yield
    reset_in_memory_stores()
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


def _payload():
    return {"agent_id": "agent-1", "owner_user_id": "user-1", "timestamp": "2026-07-17T00:00:00+00:00"}


@pytest.mark.asyncio
async def test_agent_registered_is_ledgered(set_mode):
    set_mode("shadow")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    mapper = AgentLifecycleMapper(graph_client=client)
    await mapper.handle_event("agent_registered", _payload(), TENANT)

    rows = await ledger.list_records(TENANT)
    assert [r["operation"] for r in rows] == [
        "node_versioned", "node_versioned", "edge_created",
    ]
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)


@pytest.mark.asyncio
async def test_agent_registered_off_mode_no_ledger(set_mode):
    set_mode("off")
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    mapper = AgentLifecycleMapper(graph_client=client)
    await mapper.handle_event("agent_registered", _payload(), TENANT)
    assert await client.get_edges(f"{TENANT}:user:user-1")  # OWNS_AGENT edge projected
    assert await ledger.list_records(TENANT) == []
