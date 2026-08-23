"""Phase B — semantic DSR deletion / consent restriction propagation.

Proves a revoked/erased subject's semantic data does not persist: erasure
hard-deletes across the semantic silver/gold tables + review queue and returns a
verification result; restriction marks observations CONSENT_RESTRICTED; and the
semantic components are part of the DSR propagation record.
"""

from __future__ import annotations

from typing import Optional

import pytest

from repositories.repos import reset_in_memory_stores
from services.dsr_propagation.models import DSR_COMPONENTS
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.graph_projector import project_tenant
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.privacy import SemanticPrivacyHandler
from services.semantic_intelligence.repositories.review_queue_repo import (
    SemanticReviewQueueRepository,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.graph.graph import EdgeType, GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway

TENANT = "tenant_privacy"
SUBJECT = "prod_target"


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


_PAYLOAD = {
    "source_event_id": "e1",
    "source_type": "feedback",
    "actor_ref": "u1",
    "primary_subject_ref": SUBJECT,
    "target_type": "product",
    "content": "great product, I recommend it",
}


def test_semantic_components_registered_in_dsr():
    for component in (
        "semantic_observations",
        "sentiment_observations",
        "semantic_gold_state",
        "semantic_review_queue",
    ):
        assert component in DSR_COMPONENTS


async def test_erasure_deletes_semantic_data_and_reports():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    await SemanticReviewQueueRepository().enqueue(
        TENANT, "ambiguous_subject", subject_ref=SUBJECT
    )
    assert len(await get_store().list_semantic(TENANT)) == 1

    result = await svc.erase_subject(TENANT, SUBJECT)
    assert result["completed"] is True
    assert result["deleted"]["silver_semantic_observations"] == 1
    assert result["deleted"]["semantic_review_queue"] == 1
    assert result["deleted_total"] >= 2

    # Nothing remains for the subject.
    assert await get_store().list_semantic(TENANT, SUBJECT) == []
    assert await SemanticReviewQueueRepository().list_open(TENANT) == []


async def test_erasure_is_tenant_scoped():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    await svc.classify_and_persist(_PAYLOAD, "other_tenant")

    await svc.erase_subject(TENANT, SUBJECT)
    # The other tenant's observation is untouched.
    assert len(await get_store().list_semantic("other_tenant", SUBJECT)) == 1


async def test_restriction_marks_consent_restricted():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)

    result = await svc.restrict_subject(TENANT, SUBJECT)
    assert result["completed"] is True
    assert result["restricted"]["silver_semantic_observations"] == 1

    rows = await get_store().list_semantic(TENANT, SUBJECT)
    assert rows and rows[0].status is ObservationStatus.CONSENT_RESTRICTED


# ── graph projection revocation ──────────────────────────────────────────────
#
# Codex P1: deleting/removing the durable Gold relationship rows is not enough
# — a previously projected SEMANTIC_RELATES_TO edge (written by the semantic
# graph projector through the mutation gateway) stays LIVE in the graph until
# the projector's next reconciliation sweep (a default six-hour interval).
# These tests pin that erasure and restriction revoke the subject's projected
# edges through the gateway BEFORE reporting completed, tenant-scoped, and that
# a revocation failure fails the DSR closed (completed=False).

OTHER_TENANT = "tenant_privacy_other"


class _RecordingGateway(GraphMutationGateway):
    """Gateway that records the revocations it is asked to apply, then applies them."""

    def __init__(self, graph_client: GraphClient) -> None:
        super().__init__(graph_client=graph_client)
        self.revocations: list = []

    async def apply(self, intent):
        if intent.revocation is not None:
            self.revocations.append(intent)
        return await super().apply(intent)


class _FailingGateway:
    """Gateway whose revocation always fails — proves the DSR fails closed."""

    async def apply(self, intent):
        raise RuntimeError("gateway revocation failed")


async def _project_edge(
    source: str,
    target: str,
    *,
    tenant: str = TENANT,
    client: Optional[GraphClient] = None,
) -> GraphClient:
    """Seed a source→target relationship Gold row and project it into the graph.

    Mirrors the projector test's seeding: classify → persist silver → recompute
    both relationship Golds → ``project_tenant`` (which writes the governed
    ``SEMANTIC_RELATES_TO`` edge through the gateway into ``client``).
    """
    obs, sentiments = await classify_event(
        {
            "source_event_id": f"e_proj_{source}_{target}",
            "source_type": "feedback",
            "actor_ref": source,
            "primary_subject_ref": target,
            "content": "great excellent recommend",
        },
        tenant,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)
    await service_mod.get_semantic_service().recompute_relationship_state(tenant, source, target)
    if client is None:
        client = GraphClient()
        await client.connect()
    await project_tenant(tenant, graph_client=client)
    return client


async def test_erasure_revokes_projected_graph_edges_via_gateway():
    client = await _project_edge(SUBJECT, "prod_other")
    live = await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO)
    assert len(live) == 1

    result = await SemanticPrivacyHandler(graph_client=client).handle_erasure(TENANT, SUBJECT)

    assert result["completed"] is True
    assert result["graph_revocations"] == 1
    # Direct graph consumers no longer see the erased subject's relationship.
    assert await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO) == []


async def test_erasure_revokes_projected_edges_where_subject_is_target():
    client = await _project_edge("prod_other", SUBJECT)  # SUBJECT is the TARGET
    live = await client.get_edges("prod_other", edge_type=EdgeType.SEMANTIC_RELATES_TO)
    assert len(live) == 1

    result = await SemanticPrivacyHandler(graph_client=client).handle_erasure(TENANT, SUBJECT)

    assert result["completed"] is True
    assert result["graph_revocations"] == 1
    assert await client.get_edges("prod_other", edge_type=EdgeType.SEMANTIC_RELATES_TO) == []
    # Soft-revoke marker proves it went through the gateway's revoke path.
    revoked = await client.get_edges(
        "prod_other", edge_type=EdgeType.SEMANTIC_RELATES_TO, include_revoked=True
    )
    assert len(revoked) == 1
    assert revoked[0].properties.get("revoked") is True
    assert revoked[0].properties.get("revoke_reason") == "gold_relationship_removed"


async def test_erasure_revokes_via_mutation_gateway_for_subject():
    # The revocation is issued THROUGH the canonical mutation gateway — never a
    # direct graph write — for exactly the subject's projected edge.
    client = await _project_edge(SUBJECT, "prod_other")
    gateway = _RecordingGateway(client)

    result = await SemanticPrivacyHandler(
        graph_client=client, gateway=gateway
    ).handle_erasure(TENANT, SUBJECT)

    assert result["completed"] is True
    assert result["graph_revocations"] == 1
    assert len(gateway.revocations) == 1
    revocation = gateway.revocations[0].revocation
    assert revocation.edge_type == EdgeType.SEMANTIC_RELATES_TO
    assert revocation.from_vertex_id == SUBJECT
    assert revocation.to_vertex_id == "prod_other"
    assert revocation.reason == "gold_relationship_removed"
    assert await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO) == []


async def test_erasure_revocation_is_tenant_scoped():
    client = GraphClient()
    await client.connect()
    await _project_edge(SUBJECT, "prod_other", tenant=TENANT, client=client)
    await _project_edge(SUBJECT, "prod_other", tenant=OTHER_TENANT, client=client)
    assert len(await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO)) == 2

    result = await SemanticPrivacyHandler(graph_client=client).handle_erasure(TENANT, SUBJECT)

    assert result["completed"] is True
    assert result["graph_revocations"] == 1
    remaining = await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO)
    assert len(remaining) == 1
    assert remaining[0].properties.get("tenantId") == OTHER_TENANT


async def test_restriction_revokes_projected_graph_edges_via_gateway():
    client = await _project_edge(SUBJECT, "prod_other")
    assert len(await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO)) == 1

    result = await SemanticPrivacyHandler(graph_client=client).handle_restriction(
        TENANT, SUBJECT
    )

    assert result["completed"] is True
    assert result["graph_revocations"] == 1
    assert await client.get_edges(SUBJECT, edge_type=EdgeType.SEMANTIC_RELATES_TO) == []


async def test_erasure_revocation_failure_fails_closed():
    client = await _project_edge(SUBJECT, "prod_other")
    result = await SemanticPrivacyHandler(
        graph_client=client, gateway=_FailingGateway()
    ).handle_erasure(TENANT, SUBJECT)

    # A revocation failure must NOT report the DSR complete (fail-closed).
    assert result["completed"] is False
    assert any("graph_revoke" in e for e in result["errors"])


async def test_restriction_revocation_failure_fails_closed():
    client = await _project_edge(SUBJECT, "prod_other")
    result = await SemanticPrivacyHandler(
        graph_client=client, gateway=_FailingGateway()
    ).handle_restriction(TENANT, SUBJECT)

    assert result["completed"] is False
    assert any("graph_revoke" in e for e in result["errors"])
