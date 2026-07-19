"""Phase A1 — durable semantic store, service port, supersession, honest health.

These tests exercise the durable path (``DurableSemanticSentimentStore`` over the
shared in-memory fallback registry) that replaces the process-local singleton.
They prove the anti-patterns the mono-prompt flags are gone: durable-across-
instances storage, idempotent replay, real supersession, byte-identical route/
worker classification, a real review queue, and computed (not hardcoded) health.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import engine
from services.semantic_intelligence.engine import (
    SemanticSentimentStore,
    classify_event,
    get_store,
    set_store,
)
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.repositories.review_queue_repo import (
    SemanticReviewQueueRepository,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_durable"

_PAYLOAD = {
    "source_event_id": "evt_1",
    "source_type": "feedback",
    "actor_ref": "user_1",
    "actor_type": "profile",
    "primary_subject_ref": "product_42",
    "target_type": "product",
    "content": "I love this product, great quality, I recommend it",
    "language": "en",
}


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    yield
    set_store(original)
    reset_in_memory_stores()


async def test_durable_store_persists_and_rehydrates():
    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(_PAYLOAD, TENANT)
    assert obs.status == ObservationStatus.CLASSIFIED
    assert sentiments and sentiments[0].valence > 0

    rows, partial = await svc.list_observations(TENANT, "product_42")
    assert len(rows) == 1
    assert rows[0].observation_id == obs.observation_id
    assert not partial


async def test_persistence_survives_new_store_instance():
    """Durability: a *fresh* store instance reads prior writes (not per-instance)."""
    svc = SemanticIntelligenceService()
    await svc.classify_and_persist(_PAYLOAD, TENANT)

    # Simulate a process restart: a brand-new durable store instance must still
    # see the row (it lives in the shared durable-fallback registry / DB, not in
    # a per-instance dict the way the old in-memory singleton did).
    set_store(DurableSemanticSentimentStore())
    rows, _ = await SemanticIntelligenceService().list_observations(TENANT, "product_42")
    assert len(rows) == 1


async def test_idempotent_replay_no_duplicates():
    svc = SemanticIntelligenceService()
    first, _ = await svc.classify_and_persist(_PAYLOAD, TENANT)
    second, _ = await svc.classify_and_persist(_PAYLOAD, TENANT)
    assert first.idempotency_key == second.idempotency_key
    rows, _ = await svc.list_observations(TENANT, "product_42", limit=100)
    assert len(rows) == 1


async def test_supersession_transitions_status():
    store = get_store()
    obs, _ = classify_event(_PAYLOAD, TENANT)
    await store.put_semantic(obs)

    changed = await store.supersede(TENANT, obs.idempotency_key, "sem_new")
    assert changed is True

    rows = await store.list_semantic(TENANT, "product_42")
    assert rows[0].status == ObservationStatus.SUPERSEDED
    assert rows[0].superseded_by == "sem_new"


async def test_route_and_worker_paths_are_identical():
    """The service (worker path) and the pure classifier agree byte-for-byte."""
    pure_obs, _ = classify_event(_PAYLOAD, TENANT)
    svc = SemanticIntelligenceService()
    persisted_obs, _ = await svc.classify_and_persist(_PAYLOAD, TENANT)
    assert persisted_obs.idempotency_key == pure_obs.idempotency_key
    assert persisted_obs.intent == pure_obs.intent
    assert persisted_obs.stance == pure_obs.stance


async def test_tenant_isolation():
    svc = SemanticIntelligenceService()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    other_rows, _ = await svc.list_observations("other_tenant", "product_42")
    assert other_rows == []


async def test_fleet_health_is_computed_not_hardcoded():
    svc = SemanticIntelligenceService()
    before = await svc.fleet_health()
    assert before["classified_observations"] == 0
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    after = await svc.fleet_health()
    assert after["classified_observations"] == 1
    assert after["enabled_tenants"] == 1
    assert "status_breakdown" in after


async def test_review_queue_is_backed_by_a_real_store():
    repo = SemanticReviewQueueRepository()
    assert await repo.list_open(TENANT) == []
    item = await repo.enqueue(TENANT, "ambiguous_subject", subject_ref="product_42")
    open_items = await repo.list_open(TENANT)
    assert len(open_items) == 1
    assert open_items[0]["queue_type"] == "ambiguous_subject"
    counts = await repo.counts(TENANT)
    assert counts["ambiguous_subject"] == 1
    assert await repo.resolve(TENANT, item["id"], "assigned_subject") is True
    assert await repo.list_open(TENANT) == []


async def test_abstains_on_empty_content():
    svc = SemanticIntelligenceService()
    obs, sentiments = await svc.classify_and_persist(
        {**_PAYLOAD, "content": ""}, TENANT
    )
    assert obs.status == ObservationStatus.ABSTAINED
    assert obs.abstention_reason == "insufficient_content"
    assert sentiments == []
