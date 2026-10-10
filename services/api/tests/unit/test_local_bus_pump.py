"""Regression tests for the local in-memory event-bus delivery bridge.

Discovered during the production-certification drive: in ``AETHER_ENV=local``
with no broker reachable, ``EventProducer.publish`` appends to an in-memory
list and ``EventConsumer.receive_loop`` returns immediately — nothing outside a
broker poll ever called ``EventConsumer.process``, so Bronze-validated events
(e.g. ``POST /v1/batch``) reached Bronze and stopped before Silver projection.
``EventProducer.pump_local`` is the canonical local bridge that drains the
in-memory list into ``process`` (the same handler path Kafka/SQS drive).
"""

from __future__ import annotations

import asyncio
import os

import pytest  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from shared.events.events import (  # noqa: E402
    Event,
    EventConsumer,
    EventProducer,
    Topic,
)


def _make_producer() -> EventProducer:
    producer = EventProducer()
    assert producer.mode == "uninitialized"
    return producer


async def _publish(producer: EventProducer, event_id: str) -> None:
    await producer.publish(
        Event(
            topic=Topic.SDK_EVENTS_VALIDATED,
            tenant_id="t1",
            source_service="pump-test",
            correlation_id=f"c-{event_id}",
            event_id=event_id,
            payload={"k": "v"},
        )
    )


@pytest.mark.asyncio
async def test_local_producer_connects_in_memory() -> None:
    producer = _make_producer()
    await producer.connect()
    assert producer.mode == "in-memory"


@pytest.mark.asyncio
async def test_published_event_is_not_delivered_without_pump() -> None:
    producer = _make_producer()
    await producer.connect()
    consumer = EventConsumer(group_id="pump-test")
    seen: list[str] = []

    async def _handler(event: Event) -> None:
        seen.append(event.event_id)

    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()

    await _publish(producer, "e-1")
    await asyncio.sleep(0.05)
    assert seen == [], "in-memory publish must not deliver without the pump"


@pytest.mark.asyncio
async def test_pump_delivers_exactly_once_and_picks_up_new_publishes() -> None:
    producer = _make_producer()
    await producer.connect()
    consumer = EventConsumer(group_id="pump-test")
    seen: list[str] = []

    async def _handler(event: Event) -> None:
        seen.append(event.event_id)

    consumer.subscribe(Topic.SDK_EVENTS_VALIDATED, _handler)
    await consumer.start()

    await _publish(producer, "e-1")
    await _publish(producer, "e-2")

    stop = asyncio.Event()
    pump = asyncio.create_task(producer.pump_local(consumer, stop))
    await asyncio.sleep(0.2)

    assert seen == ["e-1", "e-2"], f"expected both events once, got {seen}"

    # Handlers that publish while pumping are picked up on a later tick.
    async def _re_publisher(event: Event) -> None:
        seen.append(event.event_id)
        if event.event_id == "e-2":
            await _publish(producer, "e-3")

    # Rebind to a re-publishing handler after draining the first two.
    consumer2 = EventConsumer(group_id="pump-test-2")
    consumer2.subscribe(Topic.SDK_EVENTS_VALIDATED, _re_publisher)
    stop2 = asyncio.Event()
    pump2 = asyncio.create_task(producer.pump_local(consumer2, stop2))
    await asyncio.sleep(0.2)
    assert "e-3" in seen, "handler-published event must be picked up"
    stop2.set()
    await pump2

    stop.set()
    await pump


@pytest.mark.asyncio
async def test_pump_stops_cleanly_on_stop_event() -> None:
    producer = _make_producer()
    await producer.connect()
    consumer = EventConsumer(group_id="pump-test")
    await consumer.start()

    stop = asyncio.Event()
    pump = asyncio.create_task(producer.pump_local(consumer, stop))
    await asyncio.sleep(0.05)
    assert not pump.done()
    stop.set()
    await asyncio.wait_for(pump, timeout=1.0)
    assert pump.done()


@pytest.mark.asyncio
async def test_pump_skips_when_not_in_memory_mode() -> None:
    producer = _make_producer()
    producer._mode = "kafka"  # simulate a broker-connected producer
    consumer = EventConsumer(group_id="pump-test")
    stop = asyncio.Event()
    await producer.pump_local(consumer, stop)
    # Returns immediately without delivering; nothing to observe beyond return.
    assert stop is not None
