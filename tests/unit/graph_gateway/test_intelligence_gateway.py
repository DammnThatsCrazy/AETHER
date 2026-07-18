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
from services.intelligence.graph_mutations import upsert_outcome_graph
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
