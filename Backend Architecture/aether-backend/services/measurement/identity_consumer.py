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
from typing import Any

from shared.events.events import Event, EventProducer, Topic

logger = logging.getLogger("aether.measurement.identity_consumer")


class MeasurementIdentityConsumer:
    """Handles identity change events and propagates them to the measurement pipeline."""

    def __init__(self, producer: EventProducer) -> None:
        self._producer = producer

    async def on_identity_merged(self, event: Event) -> None:
        """Handle an IDENTITY_MERGED event.

        The identity service emits ``primary_entity_id`` (survivor) and
        ``secondary_entity_id`` (consumed). Those are read first; the legacy
        ``surviving_profile_id``/``merged_profile_id`` (and ``profile_id_a/b``)
        names are honored as fallbacks so older/replayed events still process.
        Before this fix the consumer read only the legacy names, so every real
        merge event failed the required-fields guard and never recomputed
        journeys or attribution.
        """
        payload = event.payload or {}
        tenant_id = event.tenant_id or payload.get("tenant_id", "")
        surviving_id = (
            payload.get("primary_entity_id")
            or payload.get("surviving_profile_id")
            or payload.get("profile_id_a")
        )
        merged_id = (
            payload.get("secondary_entity_id")
            or payload.get("merged_profile_id")
            or payload.get("profile_id_b")
        )

        if not tenant_id or not surviving_id:
            logger.warning(
                "identity_merged event missing required fields: tenant_id=%s surviving_id=%s event_id=%s",
                tenant_id, surviving_id, event.event_id,
            )
            return

        try:
            await self._rebuild_and_reattribute(tenant_id, str(surviving_id), reason="identity_merged")
        except Exception as exc:
            logger.error(
                "measurement identity_merged handler failed for profile=%s: %s",
                surviving_id, exc, exc_info=True,
            )

        # If the merged (consumed) profile had its own journeys, rebuild those too
        # so they reflect the current post-merge state of the surviving profile.
        if merged_id and str(merged_id) != str(surviving_id):
            try:
                await self._rebuild_and_reattribute(tenant_id, str(merged_id), reason="identity_merged_source")
            except Exception as exc:
                logger.warning(
                    "measurement identity_merged rebuild for consumed profile=%s failed: %s",
                    merged_id, exc,
                )

    async def _rebuild_and_reattribute(self, tenant_id: str, profile_id: str, reason: str) -> None:
        from services.measurement.engine.journey_compiler import JourneyCompiler
        from services.measurement.engine.attribution_engine import AttributionEngine

        compiler = JourneyCompiler()
        engine = AttributionEngine()

        rebuilt = await compiler.rebuild_affected_by_identity_change(tenant_id, profile_id)

        for journey_version in rebuilt:
            conversion_ids: list[Any] = journey_version.get("conversion_ids") or []
            for conv_id in conversion_ids:
                try:
                    await engine.run_for_conversion(
                        tenant_id,
                        str(conv_id),
                        trigger_reason=reason,
                    )
                except Exception as exc:
                    logger.warning(
                        "attribution recompute after identity change failed for conversion=%s: %s",
                        conv_id, exc,
                    )

        logger.info(
            "measurement identity change processed: tenant=%s profile=%s journeys_rebuilt=%d reason=%s",
            tenant_id, profile_id, len(rebuilt), reason,
        )

    def register(self, consumer: Any) -> None:
        """Register this handler with an EventConsumer instance."""
        consumer.subscribe(Topic.IDENTITY_MERGED, self.on_identity_merged)
        logger.info("MeasurementIdentityConsumer registered for IDENTITY_MERGED")
