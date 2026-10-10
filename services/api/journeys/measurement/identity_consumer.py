"""Measurement identity event consumer.

Listens to IDENTITY_MERGED events and triggers:
  1. Journey rebuild for the surviving profile (via JourneyCompiler)
  2. Attribution recompute for all conversions in the rebuilt journey
     (via AttributionEngine)

This ensures that when identity resolution stitches two profiles together,
the measurement pipeline automatically re-derives the correct attribution
from the full merged touchpoint history.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from shared.events.events import Event, EventProducer, Topic

logger = logging.getLogger("aether.measurement.identity_consumer")


class MeasurementIdentityConsumer:
    """Translate identity events into durable restatement jobs.

    Projection execution belongs to the retryable jobs worker. Rebuilding here
    as well would create a second Journey version and attribution run for the
    same committed merge/split.
    """

    def __init__(self, producer: EventProducer) -> None:
        self._producer = producer

    async def on_identity_merged(self, event: Event) -> None:
        """Idempotently queue the restatement or recover its missing enqueue."""
        await self._queue_event_restatement(event)

    async def on_identity_split(self, event: Event) -> None:
        """Idempotently queue both sides of the split for durable restatement."""
        await self._queue_event_restatement(event)

    async def _queue_event_restatement(self, event: Event) -> None:
        from replay.projections.projection_restatement_orchestrator import (
            ProjectionRestatementOrchestrator,
        )

        job = await ProjectionRestatementOrchestrator().queue_restatement_from_event(event)
        if job is None:
            logger.warning(
                "measurement identity event is non-queueable tenant=%s event_id=%s",
                event.tenant_id, event.event_id,
            )
            return
        logger.info(
            "measurement identity restatement ensured tenant=%s job_id=%s decision_id=%s",
            job.tenant_id, job.id, job.trigger_decision_id,
        )

    async def _rebuild_and_reattribute(
        self,
        tenant_id: str,
        profile_id: str,
        reason: str,
        *,
        restatement_key: Optional[str] = None,
    ) -> None:
        from journeys.measurement.engine.journey_compiler import JourneyCompiler
        from journeys.measurement.engine.attribution_engine import AttributionEngine

        compiler = JourneyCompiler()
        engine = AttributionEngine()

        rebuilt = await compiler.rebuild_affected_by_identity_change(
            tenant_id, profile_id, restatement_key=restatement_key
        )

        errors: list[str] = []
        for journey_version in rebuilt:
            conversion_ids: list[Any] = journey_version.get("conversion_ids") or []
            for conv_id in conversion_ids:
                try:
                    await engine.run_for_conversion(
                        tenant_id,
                        str(conv_id),
                        trigger_reason=reason,
                        idempotency_key=(
                            f"{restatement_key}:{conv_id}" if restatement_key else None
                        ),
                    )
                except Exception as exc:
                    errors.append(f"conversion attribution failed: {type(exc).__name__}")
                    logger.warning(
                        "attribution recompute after identity change failed for conversion=%s: %s",
                        conv_id, exc,
                    )

        logger.info(
            "measurement identity change processed: tenant=%s profile=%s journeys_rebuilt=%d reason=%s",
            tenant_id, profile_id, len(rebuilt), reason,
        )
        if errors:
            raise RuntimeError("; ".join(errors))

    def register(self, consumer: Any) -> None:
        """Register this handler with an EventConsumer instance."""
        consumer.subscribe(Topic.IDENTITY_MERGED, self.on_identity_merged)
        consumer.subscribe(Topic.IDENTITY_SPLIT, self.on_identity_split)
        logger.info("MeasurementIdentityConsumer registered for IDENTITY_MERGED + IDENTITY_SPLIT")
