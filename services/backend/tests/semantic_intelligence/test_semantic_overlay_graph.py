"""Overlay reads the ACTUALLY-PROJECTED graph (#9).

``SemanticIntelligenceService.list_relationship_edges`` is graph-primary: when a
tenant's relationship Gold has been projected into ``SEMANTIC_RELATES_TO`` edges
it reads them back through the GraphClient (each ``live_in_graph=True``), and
before the projector has run it falls back to durable Gold (``live_in_graph=
False``). Both paths stay tenant-isolated. These pin that read-back contract
against a real GraphClient instead of the projector-internal helpers.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import graph_projector as projector_mod
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.graph_projector import project_tenant
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.graph.graph import EdgeType, GraphClient

TENANT = "tenant_overlay"
OTHER_TENANT = "tenant_overlay_other"
SOURCE = "profile_alice"
TARGET = "prod_widget"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    projector_mod._TENANT_PROJECT_LOCKS.clear()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()
    projector_mod._TENANT_PROJECT_LOCKS.clear()


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


async def _seed_relationship(
    tenant: str, source: str, target: str, *, content: str = "great product, I recommend it"
) -> None:
    obs, sentiments = await classify_event(
        {
            "source_event_id": f"e_{tenant}_{source}_{target}",
            "source_type": "feedback",
            "actor_ref": source,
            "primary_subject_ref": target,
            "content": content,
        },
        tenant,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)
    await service_mod.get_semantic_service().recompute_relationship_state(tenant, source, target)


async def _semantic_edges(client: GraphClient, source: str) -> list:
    return list(await client.get_edges(source, edge_type=EdgeType.SEMANTIC_RELATES_TO))


async def test_overlay_reads_projected_edges_live_in_graph():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()
    report = await project_tenant(TENANT, graph_client=client)
    assert report.projected == 1
    # The edge really is in this client (guards against a false-positive fallback).
    assert len(await _semantic_edges(client, SOURCE)) == 1

    service = service_mod.get_semantic_service()
    edges = await service.list_relationship_edges(TENANT, graph_client=client)

    assert len(edges) == 1
    edge = edges[0]
    assert edge["source_ref"] == SOURCE
    assert edge["target_ref"] == TARGET
    # Served from the graph read-back, not the Gold fallback.
    assert edge["live_in_graph"] is True
    assert edge["stance_alignment"] is not None


async def test_overlay_projected_read_is_tenant_scoped():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_relationship(OTHER_TENANT, SOURCE, TARGET)
    client = await _graph()
    await project_tenant(TENANT, graph_client=client)
    await project_tenant(OTHER_TENANT, graph_client=client)
    service = service_mod.get_semantic_service()

    ours = await service.list_relationship_edges(TENANT, graph_client=client)
    theirs = await service.list_relationship_edges(OTHER_TENANT, graph_client=client)

    # Each tenant sees exactly its own projected edge, never the other's.
    assert [(e["source_ref"], e["target_ref"], e["live_in_graph"]) for e in ours] == [
        (SOURCE, TARGET, True)
    ]
    assert [(e["source_ref"], e["target_ref"], e["live_in_graph"]) for e in theirs] == [
        (SOURCE, TARGET, True)
    ]
    # An unrelated tenant with no Gold and no projection sees nothing.
    assert await service.list_relationship_edges("tenant_overlay_empty", graph_client=client) == []


async def test_overlay_falls_back_to_gold_when_nothing_projected():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    # A fresh, empty graph client: the projector has not written any edge.
    client = await _graph()
    assert await _semantic_edges(client, SOURCE) == []

    service = service_mod.get_semantic_service()
    edges = await service.list_relationship_edges(TENANT, graph_client=client)

    # Still populated from durable Gold, but flagged as NOT live in the graph.
    assert len(edges) == 1
    assert edges[0]["source_ref"] == SOURCE
    assert edges[0]["target_ref"] == TARGET
    assert edges[0]["live_in_graph"] is False
    # Tenant isolation holds on the fallback path too.
    assert await service.list_relationship_edges(OTHER_TENANT, graph_client=client) == []
