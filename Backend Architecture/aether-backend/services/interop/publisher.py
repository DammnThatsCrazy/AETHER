"""Interoperability Intelligence event publish seam.

Converts the canonical ``make_event()`` dicts emitted by the correlation,
reconciliation and security services (``{event_name, tenant_id, payload,
occurred_at}``) into shared :class:`Event` objects and hands them to the
shared :class:`EventProducer`. The broker (Kafka in staging/production, SNS/SQS
fanout, or the in-memory list in local dev) is external and entirely owned by
the shared producer — this module only ever performs the publish call.

Topic mapping is conservative: the shared :class:`Topic` enum carries one
interop generic topic (``CANONICAL_ACTIVITY_INGESTED``) plus the two
notification-bound topics (``INTEROP_MESSAGE_STUCK``,
``INTEROP_SECURITY_POLICY_CHANGED``). We reuse those members and carry the
fine-grained registry ``event_name`` in the payload so consumers (silver
projector, Profile360, notification intelligence) dispatch on the registry
name without any enum changes. If the integration pass later adds dedicated
interop topics to :class:`Topic`, only the ``_topic_for`` mapping below needs
updating.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.events.events import Event, EventProducer, Topic
from services.interop.foundation import utc_now_iso

_SOURCE_SERVICE = "interoperability_intelligence"

# event_name -> Topic. Events not listed fall back to CANONICAL_ACTIVITY_INGESTED.
_TOPIC_MAP: dict[str, Topic] = {
    "interop_security_policy_changed": Topic.INTEROP_SECURITY_POLICY_CHANGED,
    "interop_message_stuck": Topic.INTEROP_MESSAGE_STUCK,
}


def topic_for(event_name: str) -> Topic:
    """The Topic a registry event should be published under."""
    return _TOPIC_MAP.get(event_name, Topic.CANONICAL_ACTIVITY_INGESTED)


class InteropEventPublisher:
    """Publish seam: ``make_event`` dicts -> :class:`Event` -> ``EventProducer``.

    The broker connection is owned by the injected :class:`EventProducer`
    (``connect()`` is a no-op re-entrancy guard on the producer). Publishing is
    a real call on every environment; local dev lands in the producer's
    in-memory list, staging/production lands on Kafka/SQS. A failed publish
    raises after the producer's own retries — the scan worker treats that as a
    cycle failure so checkpoints do not advance past an undelivered event batch.
    """

    def __init__(self, producer: Optional[EventProducer] = None) -> None:
        self._producer = producer or EventProducer()
        self._source_service = _SOURCE_SERVICE
        self._published: list[Event] = []

    async def connect(self) -> None:
        await self._producer.connect()

    async def publish(self, event_dict: dict[str, Any], correlation_id: str = "") -> Event:
        """Publish one ``make_event`` dict; returns the built :class:`Event`."""
        event = self._to_event(event_dict, correlation_id)
        await self._producer.publish(event)
        self._published.append(event)
        return event

    async def publish_batch(
        self, event_dicts: list[dict[str, Any]], correlation_id: str = "",
    ) -> list[Event]:
        """Publish many ``make_event`` dicts in one batch; returns built Events."""
        events = [self._to_event(ed, correlation_id) for ed in event_dicts]
        if not events:
            return []
        await self._producer.publish_batch(events)
        self._published.extend(events)
        return events

    @property
    def published(self) -> list[Event]:
        """Local mirror of everything published through this seam (tests)."""
        return list(self._published)

    def _to_event(self, event_dict: dict[str, Any], correlation_id: str) -> Event:
        event_name = event_dict.get("event_name") or "interop_observation"
        payload = dict(event_dict.get("payload") or {})
        payload.setdefault("event_name", event_name)
        return Event(
            topic=topic_for(event_name),
            payload=payload,
            tenant_id=event_dict.get("tenant_id") or "",
            timestamp=event_dict.get("occurred_at") or utc_now_iso(),
            source_service=self._source_service,
            correlation_id=correlation_id,
        )
