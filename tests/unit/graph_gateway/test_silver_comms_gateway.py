"""WP2.5: the Silver→Graph and Comms projectors route their graph writes
through the canonical mutation gateway.

Behaviour is unchanged at mode=off (edge still projected, zero ledger writes);
at mode=shadow each write is recorded in the append-only ledger and the ledger
replays to a digest identical to the live projection (parity)."""

from __future__ import annotations

import pytest

import shared.graph.mutation_gateway as mg
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from services.comms.graph_projection import (
    CommsGraphProjector,
    reset_local_relationships,
)
from services.silver.projectors.silver_graph_projector import SilverGraphProjector
from shared.graph.graph import EdgeType, GraphClient
from shared.graph.mutation_gateway import (
    GraphMutationGateway,
    current_graph_digest,
    replay_ledger,
)

TENANT = "tenant_silver_comms_gw"


@pytest.fixture(autouse=True)
def _reset():
    reset_graph_ledger_memory()
    reset_local_relationships()
    yield
    reset_graph_ledger_memory()
    reset_local_relationships()
    mg._shared_gateway = None


@pytest.fixture
def wired():
    """Bind the process-wide gateway to a fresh in-memory client + ledger."""
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    mg._shared_gateway = GraphMutationGateway(graph_client=client, ledger=ledger)
    return client, ledger


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


def _exposure_event() -> dict:
    return {
        "context": {"tenantId": TENANT},
        "userId": "user-1",
        "properties": {"contentId": "content-9"},
        "messageId": "evt-exp-1",
        "timestamp": "2026-07-17T00:00:00+00:00",
        "type": "content_viewed",
    }


@pytest.mark.asyncio
async def test_silver_exposure_edge_is_ledgered_edge_created(set_mode, wired):
    set_mode("shadow")
    client, ledger = wired
    await SilverGraphProjector()._emit_exposure(None, _exposure_event())

    edges = await client.get_edges("user-1")
    assert [e.edge_type for e in edges] == [EdgeType.EXPOSED_TO]
    assert edges[0].properties["idempotency_key"]

    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["operation"] == "edge_created"
    assert rows[0]["aggregate_id"] == f"{EdgeType.EXPOSED_TO}:user-1:content-9"
    assert rows[0]["source_event_id"] == "evt-exp-1"


@pytest.mark.asyncio
async def test_silver_off_mode_projects_without_ledger(set_mode, wired):
    set_mode("off")
    client, ledger = wired
    await SilverGraphProjector()._emit_exposure(None, _exposure_event())
    assert len(await client.get_edges("user-1")) == 1
    assert await ledger.list_records(TENANT) == []


@pytest.mark.asyncio
async def test_comms_relationship_edge_is_ledgered(set_mode, wired):
    set_mode("shadow")
    client, ledger = wired
    row = {
        "source_event_type": "email_sent",
        "tenant_id": TENANT,
        "sender_entity_id": "sender-1",
        "recipient_entity_id": "recipient-1",
        "channel": "email",
        "message_category": "marketing",
        "occurred_at": "2026-07-17T00:00:00+00:00",
        "source_event_id": "evt-comms-1",
    }
    await CommsGraphProjector().project_fact(row)

    edges = await client.get_edges("entity:sender-1")
    assert [e.edge_type for e in edges] == [EdgeType.CONTACTED]
    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["operation"] == "edge_created"


@pytest.mark.asyncio
async def test_shadow_ledger_replays_to_live_digest(set_mode, wired):
    """Ledger replay digest == live projection digest (shadow parity)."""
    set_mode("shadow")
    client, ledger = wired
    await SilverGraphProjector()._emit_exposure(None, _exposure_event())
    await CommsGraphProjector().project_fact(
        {
            "source_event_type": "email_sent",
            "tenant_id": TENANT,
            "sender_entity_id": "sender-1",
            "recipient_entity_id": "recipient-1",
            "channel": "email",
            "message_category": "marketing",
            "occurred_at": "2026-07-17T00:00:00+00:00",
            "source_event_id": "evt-comms-1",
        }
    )
    rows = await ledger.list_records(TENANT)
    assert replay_ledger(rows) == await current_graph_digest(client, TENANT)
