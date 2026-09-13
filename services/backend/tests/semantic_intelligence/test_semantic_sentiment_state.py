"""Phase C·4 — durable weighted Gold entity sentiment state.

Parallels the C·1 semantic reducer: sentiment observations are reduced (weighted
by confidence × recency) into durable gold_entity_sentiment_state, with a
sentiment trend and dominant emotion, produced by the worker.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.reducers import REDUCER_VERSION, reduce_entity_sentiment
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_sentiment"
SUBJECT = "prod_sent"


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


async def _seed(content: str):
    obs, sentiments = await classify_event(
        {
            "source_event_id": f"e_{content[:4]}",
            "source_type": "feedback",
            "actor_ref": "u1",
            "primary_subject_ref": SUBJECT,
            "content": content,
        },
        TENANT,
    )
    store = get_store()
    await store.put_semantic(obs)
    for s in sentiments:
        await store.put_sentiment(s)


def test_insufficient_sentiment():
    state = reduce_entity_sentiment(TENANT, SUBJECT, [])
    assert state["insufficient_data"] is True
    assert state["reducer_version"] == REDUCER_VERSION


async def test_positive_content_yields_positive_valence():
    await _seed("love this, great, excellent, recommend")
    state = await service_mod.get_semantic_service().recompute_entity_sentiment(TENANT, SUBJECT)
    assert state["insufficient_data"] is False
    assert state["valence"] > 0
    assert "dominant_emotion" in state


async def test_gold_sentiment_persisted_and_read():
    await _seed("great, excellent, recommend")
    svc = service_mod.get_semantic_service()
    await svc.recompute_entity_sentiment(TENANT, SUBJECT)
    gold = await svc.entity_sentiment_state(TENANT, SUBJECT)
    assert gold["subject_ref"] == SUBJECT
    assert gold["reducer_version"] == REDUCER_VERSION


async def test_worker_produces_sentiment_gold():
    ev = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_id": "e_sw",
            "event_type": "feedback_submitted",
            "user_id": "u1",
            "properties": {"content": "great product, I recommend it", "product_id": SUBJECT},
        },
    )
    await SemanticEventConsumer().on_validated_event(ev)
    from services.semantic_intelligence.repositories.base_fact_repo import SemanticFactRepository

    gold = await SemanticFactRepository("gold_entity_sentiment_state").list_by_tenant(
        TENANT, SUBJECT, limit=1
    )
    assert gold and gold[0]["subject_ref"] == SUBJECT
