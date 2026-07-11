"""Recompute-on-split wiring: IDENTITY_SPLIT topic + measurement consumer.

A fragment split reassigns touchpoints between entities exactly as a merge
stitches them, so it must trigger the same journey/attribution recompute — for
both the original entity and the fragment's new home.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from shared.events.events import Event, Topic  # noqa: E402
from services.measurement.identity_consumer import MeasurementIdentityConsumer  # noqa: E402

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


async def _run(consumer, payload):
    calls: list[tuple[str, str, str]] = []

    async def _fake_rebuild(tenant_id, profile_id, reason):
        calls.append((tenant_id, profile_id, reason))

    consumer._rebuild_and_reattribute = _fake_rebuild  # type: ignore[assignment]
    event = Event(
        topic=Topic.IDENTITY_SPLIT,
        tenant_id=TENANT,
        source_service="identity",
        payload=payload,
    )
    await consumer.on_identity_split(event)
    return calls


async def test_split_recomputes_both_entities():
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    calls = await _run(consumer, {
        "original_entity_id": "orig-1",
        "resulting_entity_id": "frag-1",
    })
    profiles = {c[1] for c in calls}
    assert profiles == {"orig-1", "frag-1"}


async def test_split_resulting_equal_to_original_recomputes_once():
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    calls = await _run(consumer, {
        "original_entity_id": "orig-1",
        "resulting_entity_id": "orig-1",
    })
    assert [c[1] for c in calls] == ["orig-1"]


async def test_split_missing_resulting_recomputes_origin_only():
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    calls = await _run(consumer, {"original_entity_id": "orig-1"})
    assert [c[1] for c in calls] == ["orig-1"]


async def test_split_missing_original_is_a_noop():
    consumer = MeasurementIdentityConsumer(producer=MagicMock())
    calls = await _run(consumer, {"resulting_entity_id": "frag-1"})
    assert calls == []
