"""Event bridge — canonical AetherEvent → Bronze ingest + bus publish.

The bridge is the runtime's outbound seam: normalized
:class:`~shared.integration_contracts.events.AetherEvent` objects become durable
Bronze rows first, then an ``SDK_EVENTS_VALIDATED`` publish. Ordering and the
publish helper mirror ``services/comms/ingest.py::_ingest_communication``
EXACTLY (same topic enum, same ``get_registry().producer.publish`` helper, same
Bronze-before-publish ordering).

A publish failure NEVER fails ingestion: Bronze is durable, and a replay of the
Bronze range recovers the publish (same rationale as comms ingest).
"""

from __future__ import annotations

from collections.abc import Iterable

from shared.logger.logger import get_logger, metrics
from shared.integration_contracts.events import AetherEvent

logger = get_logger("aether.provider_runtime.bridge")

# Module-level import is safe (lake.py constructs only in-memory singletons).
from repositories.lake import BronzeRepository


async def _publish_event(tenant_id: str, event: AetherEvent) -> None:
    """Publish one canonical event to SDK_EVENTS_VALIDATED (mirrors comms)."""
    from dependencies.providers import get_registry
    from shared.events.events import Event, Topic

    registry = get_registry()
    await registry.producer.publish(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=tenant_id,
        source_service="provider_runtime.bridge",
        payload=event.model_dump(),
    ))


class EventBridge:
    """Canonical AetherEvent → Bronze ingest + bus publish (Bronze-before-publish)."""

    def __init__(self, bronze=None) -> None:
        # Default mirrors the lake.py convenience instance bronze_connectors.
        self.bronze = bronze if bronze is not None else BronzeRepository("connector_events")

    async def ingest_events(self, tenant_id: str, events: Iterable[AetherEvent]) -> int:
        """Persist each event to Bronze, then publish it; returns count ingested.

        Per-event: ``bronze.ingest(source=event.provider, ...,
        provider_record_id=event.event_id, payload=event.model_dump(),
        tenant_id=tenant_id)`` followed by an ``SDK_EVENTS_VALIDATED`` publish.
        Publish exceptions are caught and logged; they never fail ingestion.
        """
        count = 0
        for event in events:
            await self.bronze.ingest(
                source=event.provider,
                source_tag=f"provider:{event.provider}:{tenant_id}",
                provider_record_id=event.event_id,
                payload=event.model_dump(),
                tenant_id=tenant_id,
            )
            try:
                await _publish_event(tenant_id, event)
            except Exception as exc:
                # Bronze is durable; a replay of the Bronze range recovers the
                # publish. Never let a bus outage lose ingestion.
                logger.warning(
                    "provider_runtime_bridge_publish_failed event=%s: %s",
                    event.event_id, exc,
                )
                metrics.increment(
                    "provider_runtime_bridge_publish_failures_total",
                    labels={"tenant_id": tenant_id},
                )
            count += 1
        return count


__all__ = ["EventBridge"]
