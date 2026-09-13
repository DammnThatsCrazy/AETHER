"""Semantic domain-event emission (#5).

The consumer publishes ``SEMANTIC_OBSERVED`` / ``SEMANTIC_STATE_RECOMPUTED`` /
``SEMANTIC_REVIEW_ENQUEUED`` through its injected producer as observations are
classified. These prove the emission is wired to the right paths, carries only
identifiers + model/reducer versions (never raw content), and is strictly
best-effort — a producer that raises must NOT break the classification pipeline
or drop the persisted observation.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_events"
# A distinctive free-text marker: it flows into classification but must never
# surface in any emitted domain-event payload.
RAW_MARKER = "zzz_raw_secret_marker_recommend_this_product"


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


class _RecordingProducer:
    """Fake producer that records every published Event."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.events.append(event)


class _RaisingProducer:
    """Producer whose publish always fails (best-effort emission contract)."""

    def __init__(self) -> None:
        self.calls = 0

    async def publish(self, event: Event) -> None:
        self.calls += 1
        raise RuntimeError("event bus unavailable")


def _validated_event(
    *,
    subject: str | None = None,
    content: str | None = None,
    event_type: str = "feedback_submitted",
    correlation_id: str = "corr_events_1",
    **props: Any,
) -> Event:
    payload: dict[str, Any] = {
        "event_id": f"evt_{event_type}_{subject or 'unresolved'}",
        "event_type": event_type,
        "user_id": "user_events_1",
        "properties": dict(props),
    }
    if subject is not None:
        payload["primary_subject_ref"] = subject
    if content is not None:
        payload["properties"]["content"] = content
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        correlation_id=correlation_id,
        payload=payload,
    )


def _by_topic(producer: _RecordingProducer) -> dict[Topic, list[Event]]:
    out: dict[Topic, list[Event]] = {}
    for event in producer.events:
        out.setdefault(event.topic, []).append(event)
    return out


def _assert_no_raw_content(producer: _RecordingProducer) -> None:
    blob = json.dumps([e.payload for e in producer.events], default=str)
    assert RAW_MARKER not in blob, "raw content leaked into an emitted domain event"


async def test_resolved_subject_emits_observed_and_state_recomputed():
    producer = _RecordingProducer()
    consumer = SemanticEventConsumer(producer=producer)

    await consumer.on_validated_event(
        _validated_event(subject="prod_widget", content=f"{RAW_MARKER}, I recommend it")
    )

    by_topic = _by_topic(producer)
    assert Topic.SEMANTIC_OBSERVED in by_topic
    assert Topic.SEMANTIC_STATE_RECOMPUTED in by_topic
    # A resolved subject is not ambiguous, so no review item is enqueued.
    assert Topic.SEMANTIC_REVIEW_ENQUEUED not in by_topic

    observed = by_topic[Topic.SEMANTIC_OBSERVED][0]
    assert observed.tenant_id == TENANT
    assert observed.correlation_id == "corr_events_1"
    obs_payload = observed.payload
    assert obs_payload["tenant_id"] == TENANT
    assert obs_payload["subject_ref"] == "prod_widget"
    assert obs_payload["observation_id"]
    assert obs_payload["status"]
    assert obs_payload["model_id"] and obs_payload["model_version"]

    recomputed = by_topic[Topic.SEMANTIC_STATE_RECOMPUTED][0].payload
    assert recomputed["tenant_id"] == TENANT
    assert recomputed["subject_ref"] == "prod_widget"
    assert recomputed["reducer_version"]

    _assert_no_raw_content(producer)


async def test_unresolved_subject_emits_review_enqueued_with_ids():
    producer = _RecordingProducer()
    consumer = SemanticEventConsumer(producer=producer)

    # No subject anywhere → the resolver defers to the ambiguous_subject queue.
    await consumer.on_validated_event(
        _validated_event(content=f"{RAW_MARKER}, but which product?")
    )

    by_topic = _by_topic(producer)
    assert Topic.SEMANTIC_REVIEW_ENQUEUED in by_topic
    # An observation is still persisted (terminal state), so OBSERVED fires...
    assert Topic.SEMANTIC_OBSERVED in by_topic
    # ...but Gold state is not recomputed for an unknown subject.
    assert Topic.SEMANTIC_STATE_RECOMPUTED not in by_topic

    review = by_topic[Topic.SEMANTIC_REVIEW_ENQUEUED][0]
    assert review.tenant_id == TENANT
    assert review.correlation_id == "corr_events_1"
    payload = review.payload
    assert payload["tenant_id"] == TENANT
    assert payload["review_item_id"]
    assert payload["queue_type"] == "ambiguous_subject"
    assert payload["subject_ref"] == "unknown_subject"

    _assert_no_raw_content(producer)


async def test_emission_failure_does_not_break_pipeline():
    producer = _RaisingProducer()
    consumer = SemanticEventConsumer(producer=producer)

    # Must NOT raise even though every publish attempt fails.
    await consumer.on_validated_event(
        _validated_event(subject="prod_widget", content=f"{RAW_MARKER}, solid")
    )

    # The producer really was called (emission attempted, then swallowed)...
    assert producer.calls >= 1
    # ...and the observation was still persisted despite the emission failures.
    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1
    assert rows[0].primary_subject_ref == "prod_widget"


async def test_missing_producer_is_a_noop():
    # The replay path constructs the consumer without a producer; classification
    # must still succeed with no emission and no error.
    consumer = SemanticEventConsumer()

    await consumer.on_validated_event(
        _validated_event(subject="prod_widget", content=f"{RAW_MARKER}, ok")
    )

    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1
