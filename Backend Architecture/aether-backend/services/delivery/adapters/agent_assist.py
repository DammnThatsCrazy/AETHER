"""Agent Assist adapter — publishes a delivery event to the internal event bus.

Used when a suggestion or notification should be routed to an AI agent
rather than an external provider. Publishes to Topic.AGENT_ESCALATION_RAISED
or Topic.SUGGESTION_DELIVERED via the shared EventProducer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from shared.logger.logger import get_logger

from services.delivery.adapters.base import (
    AdapterReceipt,
    ConfigurationError,
    ProviderAdapter,
    ProviderError,
)

logger = get_logger("aether.delivery.adapters.agent_assist")


class AgentAssistAdapter(ProviderAdapter):
    """Publishes a delivery event to the internal Aether event bus."""

    adapter_name = "agent_assist"

    async def dispatch(
        self,
        payload: dict[str, Any],
        provider_config: dict[str, Any],
        *,
        credential: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> AdapterReceipt:
        tenant_id = payload.get("tenant_id") or provider_config.get("tenant_id")
        if not tenant_id:
            raise ConfigurationError(
                "AgentAssistAdapter requires payload.tenant_id or provider_config.tenant_id"
            )

        topic_name = provider_config.get("topic", "aether.agent.escalation_raised")
        event_id = idempotency_key or str(uuid.uuid4())

        event_payload = {
            "event_id": event_id,
            "tenant_id": tenant_id,
            "source": "delivery_worker",
            "payload": payload,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            from shared.events.events import Event, EventProducer, Topic

            # Map topic_name string to Topic enum
            topic = None
            for t in Topic:
                if t.value == topic_name:
                    topic = t
                    break
            if topic is None:
                # Fall back to AGENT_ESCALATION_RAISED
                topic = Topic.AGENT_ESCALATION_RAISED

            producer = EventProducer()
            event = Event(
                topic=topic,
                payload=event_payload,
                tenant_id=tenant_id,
                event_id=event_id,
                source_service="delivery_worker",
            )
            await producer.publish(event)
            logger.info(
                f"AgentAssist event published: topic={topic.value!r} "
                f"event_id={event_id!r} tenant={tenant_id!r}"
            )
        except Exception as exc:
            raise ProviderError(
                f"AgentAssistAdapter failed to publish event: {exc}"
            ) from exc

        return AdapterReceipt(
            external_id=f"agent:{event_id}",
            raw_response={"event_id": event_id, "topic": topic_name},
            http_status=200,
        )
