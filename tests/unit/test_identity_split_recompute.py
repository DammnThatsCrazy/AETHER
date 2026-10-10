"""Recompute-on-split wiring: IDENTITY_SPLIT topic + measurement consumer.

A fragment split reassigns touchpoints between entities exactly as a merge
stitches them, so it must trigger the same journey/attribution recompute — for
both the original entity and the fragment's new home.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parents[2] / "services" / "api"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from shared.events.events import Event, Topic  # noqa: E402
from journeys.measurement.identity_consumer import MeasurementIdentityConsumer  # noqa: E402

TENANT = "tenant-split"


def test_identity_split_topic_exists():
    assert Topic.IDENTITY_SPLIT.value == "aether.identity.split"


def test_consumer_registers_for_split():
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    subscribed: list = []

    class _Consumer:
        def subscribe(self, topic, handler):
            subscribed.append(topic)

    consumer.register(_Consumer())
    assert Topic.IDENTITY_SPLIT in subscribed
    assert Topic.IDENTITY_MERGED in subscribed


async def _run(consumer, payload, monkeypatch):
    from replay.projections.projection_restatement_orchestrator import ProjectionRestatementOrchestrator

    queued: list[Event] = []

    async def _queue_event(self, event):
        queued.append(event)
        return MagicMock(id="restatement-1", tenant_id=TENANT, trigger_decision_id="split-1")

    monkeypatch.setattr(ProjectionRestatementOrchestrator, "queue_restatement_from_event", _queue_event)
    event = Event(
        topic=Topic.IDENTITY_SPLIT,
        tenant_id=TENANT,
        source_service="identity",
        payload=payload,
    )
    await consumer.on_identity_split(event)
    return queued


async def test_split_consumer_queues_event_with_both_entities(monkeypatch):
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    queued = await _run(consumer, {
        "decision_id": "split-1",
        "original_entity_id": "orig-1",
        "resulting_entity_id": "frag-1",
    }, monkeypatch)
    assert len(queued) == 1
    assert queued[0].topic == Topic.IDENTITY_SPLIT
    assert queued[0].payload["original_entity_id"] == "orig-1"
    assert queued[0].payload["resulting_entity_id"] == "frag-1"


async def test_split_consumer_forwards_duplicate_entity_evidence_unchanged(monkeypatch):
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    queued = await _run(consumer, {
        "decision_id": "split-1",
        "original_entity_id": "orig-1",
        "resulting_entity_id": "orig-1",
    }, monkeypatch)
    assert len(queued) == 1
    assert queued[0].payload["original_entity_id"] == queued[0].payload["resulting_entity_id"]


async def test_split_consumer_forwards_missing_resulting_entity_for_validation(monkeypatch):
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    queued = await _run(consumer, {"decision_id": "split-1", "original_entity_id": "orig-1"}, monkeypatch)
    assert len(queued) == 1
    assert queued[0].payload == {"decision_id": "split-1", "original_entity_id": "orig-1"}


async def test_split_consumer_forwards_missing_original_for_validation(monkeypatch):
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    queued = await _run(consumer, {"decision_id": "split-1", "resulting_entity_id": "frag-1"}, monkeypatch)
    assert len(queued) == 1
    assert queued[0].payload == {"decision_id": "split-1", "resulting_entity_id": "frag-1"}
