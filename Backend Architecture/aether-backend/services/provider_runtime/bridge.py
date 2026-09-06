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

        WS-B3 (C class): when ``provider_runtime_consent_enforcement_enabled``,
        each event is scrubbed (in place, before the durable dump) and gated by
        the shared ingress decision — fingerprint/data-policy removal always,
        and a per-subject (S) server-receipt check when the event type resolves
        a purpose AND a subject is present AND the authoritative flag is on. A
        denied event is rejected (no Bronze, no publish, metric + warning) while
        the provider RAW record stays intact for replay; the delivery is never
        silently failed wholesale.
        """
        count = 0
        for event in events:
            if await self._consent_allows(tenant_id, event) is False:
                continue
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

    async def _consent_allows(self, tenant_id: str, event: AetherEvent) -> bool:
        """WS-B3 ingress consent gate for one canonical event (scrub + decide).

        Returns True when the event may be ingested. Scrub redacts sensitive
        values in ``data``/``context`` in place so the Bronze dump and the
        publish both carry only scrubbed payloads. Never raises.
        """
        from config.settings import settings
        from services.ingestion.generated_registry import EVENT_CONSENT_PURPOSE
        from services.ingestion.validation import (
            evaluate_ingress_decision,
            scrub_sensitive_fields,
        )

        if not settings.ingress_consent.provider_runtime_consent_enforcement_enabled:
            return True
        event.data, _ = scrub_sensitive_fields(event.data or {})
        event.context, _ = scrub_sensitive_fields(event.context or {})
        subject = str(event.subject_id or "").strip() or None
        allowed, reason_code, _decisions = await evaluate_ingress_decision(
            tenant_id=tenant_id,
            subject_id=subject,
            anonymous_id=None,
            purpose=EVENT_CONSENT_PURPOSE.get(event.event_type),
            fingerprint_obj={"data": event.data, "context": event.context},
        )
        if not allowed:
            logger.warning(
                "provider_runtime_consent_denied event=%s tenant=%s type=%s reason=%s",
                event.event_id, tenant_id, event.event_type, reason_code,
            )
            metrics.increment(
                "provider_runtime_consent_blocked_total",
                labels={"reason": reason_code or "unknown", "tenant_id": tenant_id},
            )
            return False
        return True


__all__ = ["EventBridge"]
