"""End-to-end: semantic Gold relationship state → governed graph edge.

The semantic graph projector is the bridge that was missing — Gold relationship
state was computed and stored but never reached the intelligence graph. These
tests prove, through the REAL mutation gateway in enforce mode, that a
``gold_relationship_semantic_state`` row is projected as a governed
``SEMANTIC_RELATES_TO`` edge AND recorded in the append-only mutation ledger
(never a direct graph write), and that a repeated sweep is idempotent.
"""

from __future__ import annotations

import dataclasses

import pytest


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    from config.settings import settings
    from repositories.graph_mutation_ledger import reset_graph_ledger_memory
    from repositories.repos import reset_in_memory_stores
    from services.semantic_intelligence import service as service_mod
    from services.semantic_intelligence.engine import get_store, set_store
    from services.semantic_intelligence.service import SemanticIntelligenceService
    from services.semantic_intelligence.store import DurableSemanticSentimentStore

    reset_in_memory_stores()
    reset_graph_ledger_memory()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    # Enforce mode: the mutation is transactional through the ledger.
    monkeypatch.setattr(
        settings,
        "temporal_observatory",
        dataclasses.replace(
            settings.temporal_observatory, mutation_gateway_mode="enforce"
        ),
    )
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()
    reset_graph_ledger_memory()


def test_semantic_edge_type_registered_and_excluded_layer():
    from shared.graph.graph import EdgeType
    from shared.graph.relationship_layers import RelationshipLayer, classify_edge_type

    assert EdgeType.SEMANTIC_RELATES_TO == "SEMANTIC_RELATES_TO"
    # A derived analytics overlay — deliberately outside the four operational
    # interaction layers, so enforce validation requires no consent purpose.
    assert classify_edge_type(EdgeType.SEMANTIC_RELATES_TO) == RelationshipLayer.EXCLUDED


async def _seed(tenant: str, source: str, target: str) -> None:
    from services.semantic_intelligence import service as service_mod
    from services.semantic_intelligence.engine import classify_event, get_store

    obs, sentiments = await classify_event(
        {
            "source_event_id": f"e_{tenant}_{source}_{target}",
            "source_type": "feedback",
            "actor_ref": source,
            "primary_subject_ref": target,
            "content": "great product, I recommend it",
        },
        tenant,
    )
    await get_store().put_semantic(obs)
    for s in sentiments:
        await get_store().put_sentiment(s)
    await service_mod.get_semantic_service().recompute_relationship_state(
        tenant, source, target
    )


async def _fresh_graph():
    from shared.graph.graph import GraphClient

    client = GraphClient()
    await client.connect()
    return client


async def test_relationship_gold_projects_through_the_ledger():
    from repositories.graph_mutation_ledger import GraphMutationLedgerRepository
    from services.semantic_intelligence.graph_projector import project_tenant
    from shared.graph.graph import EdgeType

    await _seed("T", "a", "b")
    client = await _fresh_graph()

    report = await project_tenant("T", graph_client=client)

    assert report.projected == 1 and report.failed == 0
    edges = await client.get_edges("a", edge_type=EdgeType.SEMANTIC_RELATES_TO)
    assert len(edges) == 1 and edges[0].to_vertex_id == "b"
    # The governed write was recorded in the append-only ledger (enforce mode).
    records = await GraphMutationLedgerRepository().list_records("T")
    assert len(records) >= 1


async def test_projection_is_idempotent_through_the_gateway():
    from services.semantic_intelligence.graph_projector import project_tenant
    from shared.graph.graph import EdgeType

    await _seed("T", "a", "b")
    client = await _fresh_graph()

    first = await project_tenant("T", graph_client=client)
    second = await project_tenant("T", graph_client=client)

    assert first.projected == 1
    assert second.projected == 0
    edges = await client.get_edges("a", edge_type=EdgeType.SEMANTIC_RELATES_TO)
    assert len(edges) == 1  # never duplicated
