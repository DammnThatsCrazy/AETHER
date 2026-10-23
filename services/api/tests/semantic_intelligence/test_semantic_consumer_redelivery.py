"""At-least-once delivery: the same validated event arriving twice (or at once)
must not become two observations, and one tenant's event id must never collide
with another's. Duplicates would silently skew sentiment state."""
from __future__ import annotations

import asyncio

import pytest

from intelligence.semantic_intelligence import service as service_mod
from intelligence.semantic_intelligence.consumer import SemanticEventConsumer
from intelligence.semantic_intelligence.engine import get_store, set_store
from intelligence.semantic_intelligence.service import SemanticIntelligenceService
from intelligence.semantic_intelligence.store import DurableSemanticSentimentStore
from repositories.repos import reset_in_memory_stores
from shared.events.events import Event, Topic

SUBJECT = "prod_redelivery"


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


class _Producer:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


def _event(tenant: str, event_id: str = "evt_redelivered", correlation_id: str = "corr") -> Event:
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=tenant,
        correlation_id=correlation_id,
        payload={
            "event_id": event_id,
            "event_type": "feedback_submitted",
            "user_id": "user_redelivery",
            "primary_subject_ref": SUBJECT,
            "properties": {"content": "I recommend this product, it is excellent"},
        },
    )


async def _observations(tenant: str) -> list:
    rows, _ = await service_mod.get_semantic_service().list_observations(tenant, SUBJECT, limit=200)
    return rows


@pytest.mark.asyncio
async def test_redelivered_event_yields_one_observation():
    consumer = SemanticEventConsumer(producer=_Producer())
    for attempt in range(3):
        await consumer.on_validated_event(_event("tenant_redelivery", correlation_id=f"corr-{attempt}"))
    assert len(await _observations("tenant_redelivery")) == 1


@pytest.mark.asyncio
async def test_concurrent_redelivery_yields_one_observation():
    consumer = SemanticEventConsumer(producer=_Producer())
    await asyncio.gather(*[
        consumer.on_validated_event(_event("tenant_redelivery", correlation_id=f"corr-{i}"))
        for i in range(10)
    ])
    assert len(await _observations("tenant_redelivery")) == 1


@pytest.mark.asyncio
async def test_the_same_event_id_in_two_tenants_is_two_independent_observations():
    consumer = SemanticEventConsumer(producer=_Producer())
    await asyncio.gather(
        consumer.on_validated_event(_event("tenant_one")),
        consumer.on_validated_event(_event("tenant_two")),
    )
    assert len(await _observations("tenant_one")) == 1
    assert len(await _observations("tenant_two")) == 1


def _unresolved_event(tenant: str, event_id: str = "evt_unresolved") -> Event:
    """No subject reference at all: the resolver routes it to ``ambiguous_subject``."""
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=tenant,
        correlation_id="corr",
        payload={
            "event_id": event_id,
            "event_type": "feedback_submitted",
            "user_id": "user_redelivery",
            "properties": {"content": "I recommend this product, it is excellent"},
        },
    )


async def _open_reviews(tenant: str) -> list:
    data = await service_mod.get_semantic_service().review_queue(tenant, "ambiguous_subject")
    return data.get("items", data.get("open", []))


@pytest.mark.asyncio
async def test_redelivered_unresolved_event_enqueues_one_review_item():
    consumer = SemanticEventConsumer(producer=_Producer())
    for _ in range(3):
        await consumer.on_validated_event(_unresolved_event("tenant_review"))
    assert len(await _open_reviews("tenant_review")) == 1


@pytest.mark.asyncio
async def test_concurrent_redelivery_enqueues_one_review_item():
    consumer = SemanticEventConsumer(producer=_Producer())
    await asyncio.gather(*[
        consumer.on_validated_event(_unresolved_event("tenant_review")) for _ in range(10)
    ])
    assert len(await _open_reviews("tenant_review")) == 1


@pytest.mark.asyncio
async def test_distinct_events_and_tenants_each_get_their_own_review_item():
    consumer = SemanticEventConsumer(producer=_Producer())
    await consumer.on_validated_event(_unresolved_event("tenant_review", "evt_a"))
    await consumer.on_validated_event(_unresolved_event("tenant_review", "evt_b"))
    await consumer.on_validated_event(_unresolved_event("tenant_other", "evt_a"))
    assert len(await _open_reviews("tenant_review")) == 2
    assert len(await _open_reviews("tenant_other")) == 1
