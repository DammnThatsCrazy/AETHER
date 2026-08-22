"""Semantic graph projector — project Gold relationship state into the graph.

Proves the projector closes the "Gold is computed but never reaches the graph"
gap: a durable ``gold_relationship_semantic_state`` row becomes a governed
``SEMANTIC_RELATES_TO`` edge written THROUGH the mutation gateway (never a
direct graph write), idempotently, tenant-scoped — and that the overlay reads
real relationship edges instead of a hardcoded ``[]``.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.graph_projector import (
    SEMANTIC_EDGE_TYPE,
    project_tenant,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.graph.graph import EdgeType, GraphClient

TENANT = "tenant_projector"
OTHER_TENANT = "tenant_projector_other"
SOURCE = "profile_alice"
TARGET = "prod_widget"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


async def _graph() -> GraphClient:
    client = GraphClient()
    await client.connect()
    return client


async def _seed_relationship(
    tenant: str, source: str, target: str, *, content: str = "great product, I recommend it"
) -> None:
    """Classify an actor→subject observation and persist its Gold relationship."""
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
    await service_mod.get_semantic_service().recompute_relationship_state(
        tenant, source, target
    )


async def _semantic_edges(client: GraphClient, source: str) -> list:
    return [
        e
        for e in await client.get_edges(source, edge_type=EdgeType.SEMANTIC_RELATES_TO)
    ]


async def test_projects_relationship_gold_as_governed_edge():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    report = await project_tenant(TENANT, graph_client=client)

    assert report.projected == 1
    assert report.failed == 0
    edges = await _semantic_edges(client, SOURCE)
    assert len(edges) == 1
    edge = edges[0]
    assert edge.to_vertex_id == TARGET
    assert edge.edge_type == EdgeType.SEMANTIC_RELATES_TO == "SEMANTIC_RELATES_TO"
    # Governed provenance + tenant label are on the edge, never raw content.
    assert edge.properties.get("tenantId") == TENANT
    assert edge.properties.get("relationship_ref") == f"rel:{SOURCE}->{TARGET}"
    assert "stance_alignment" in edge.properties


async def test_projection_is_idempotent():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    client = await _graph()

    first = await project_tenant(TENANT, graph_client=client)
    second = await project_tenant(TENANT, graph_client=client)

    assert first.projected == 1
    assert second.projected == 0
    assert second.skipped_existing == 1
    # No duplicate edge on the second sweep.
    assert len(await _semantic_edges(client, SOURCE)) == 1


async def test_projection_is_tenant_scoped():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    await _seed_relationship(OTHER_TENANT, SOURCE, TARGET)
    client = await _graph()

    await project_tenant(TENANT, graph_client=client)
    edges = await _semantic_edges(client, SOURCE)
    # Only TENANT's edge exists; OTHER_TENANT was not projected into this client.
    assert [e.properties.get("tenantId") for e in edges] == [TENANT]

    await project_tenant(OTHER_TENANT, graph_client=client)
    edges = await _semantic_edges(client, SOURCE)
    assert sorted(e.properties.get("tenantId") for e in edges) == sorted(
        [TENANT, OTHER_TENANT]
    )


async def test_overlay_service_returns_real_relationship_edges():
    await _seed_relationship(TENANT, SOURCE, TARGET)
    service = service_mod.get_semantic_service()

    edges = await service.list_relationship_edges(TENANT)

    assert len(edges) == 1
    assert edges[0]["source_ref"] == SOURCE
    assert edges[0]["target_ref"] == TARGET
    assert "stance_alignment" in edges[0]
    # Tenant isolation: another tenant sees none of this.
    assert await service.list_relationship_edges(OTHER_TENANT) == []


async def test_degenerate_pairs_are_never_projected():
    # A self-loop / unknown endpoint is skipped, never a fabricated edge.
    from services.semantic_intelligence.graph_projector import edge_from_relationship

    assert edge_from_relationship(TENANT, {"source_ref": "x", "target_ref": "x"}) is None
    assert edge_from_relationship(TENANT, {"source_ref": "", "target_ref": "y"}) is None
    assert (
        edge_from_relationship(
            TENANT, {"source_ref": "unknown_subject", "target_ref": "y"}
        )
        is None
    )
