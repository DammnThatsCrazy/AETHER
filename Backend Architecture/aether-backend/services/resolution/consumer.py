"""
Aether Backend — Identity Resolution Event Consumer

Subscribes to ``SDK_EVENTS_VALIDATED`` and triggers real-time identity
resolution on each validated event.  Results are published as resolution
events for downstream services (analytics, notifications).
"""

from __future__ import annotations

import logging
from typing import Any

from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

from .engine import IdentityResolutionEngine

logger = get_logger("aether.resolution.consumer")


class ResolutionEventConsumer:
    """
    Consumes validated SDK events and runs the real-time resolution pipeline.

    In production, this would be an SQS / Kafka consumer.  The stub exposes
    ``on_event_validated()`` as a callable handler that the ``EventConsumer``
    dispatches to.
    """

    def __init__(
        self,
        engine: IdentityResolutionEngine,
        producer: EventProducer,
    ) -> None:
        self.engine = engine
        self.producer = producer

    async def on_event_validated(self, event: Event) -> None:
        """
        Process a validated SDK event for identity resolution.

        Extracts tenant context and payload, then delegates to the engine
        for real-time deterministic matching.  Publishes a
        ``RESOLUTION_EVALUATED`` event regardless of outcome for
        observability.
        """
        tenant_id = event.tenant_id
        payload = event.payload

        if not payload:
            logger.warning(f"Empty payload in event {event.event_id}, skipping")
            return

        user_id = payload.get("user_id")
        if not user_id:
            logger.debug(
                f"Event {event.event_id} has no user_id, skipping resolution"
            )
            return

        try:
            decision = await self.engine.resolve_event(tenant_id, payload)

            # Publish evaluation event for observability
            resolution_payload: dict[str, Any] = {
                "source_event_id": event.event_id,
                "user_id": user_id,
                "resolved": decision is not None,
            }

            if decision:
                resolution_payload.update({
                    "decision_id": decision.decision_id,
                    "action": decision.action,
                    "confidence": decision.composite_confidence,
                    "deterministic": decision.deterministic_match,
                    "matched_profile": decision.profile_b_id,
                })

            await self.producer.publish(Event(
                topic=Topic.RESOLUTION_EVALUATED,
                tenant_id=tenant_id,
                source_service="resolution",
                correlation_id=event.correlation_id,
                payload=resolution_payload,
            ))

        except Exception as exc:
            logger.error(
                f"Resolution failed for event {event.event_id}: {exc}",
                exc_info=True,
            )
            # Do not re-raise — let the consumer framework handle retries
            # via its built-in dead-letter mechanism.

    def register(self, consumer: Any) -> None:
        """
        Register this handler with an ``EventConsumer`` instance.

        Usage::

            resolution_consumer = ResolutionEventConsumer(engine, producer)
            resolution_consumer.register(event_consumer)
        """
        consumer.subscribe(
            Topic.SDK_EVENTS_VALIDATED, self.on_event_validated,
        )
        logger.info("ResolutionEventConsumer registered for SDK_EVENTS_VALIDATED")
