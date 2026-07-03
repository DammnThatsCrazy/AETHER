"""Comms ingest bridge — routes normalized provider events into the standard
Bronze → bus → Silver pipeline (Phase 12).

Connectors and the generic signed webhook normalize provider payloads into
canonical communication events; this module gives them one durable entry
point that matches the /v1/batch contract:

    durable Bronze write → SDK_EVENTS_VALIDATED publish → worker fan-out

Campaign/flow catalog records (klaviyo.campaign, klaviyo.flow, …) register
in the canonical campaign registry instead — no second registry (ADR-C9).
Nothing here calls a model; the critical path is
authenticate → verify → validate → dedupe → durable write → acknowledge.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics
from services.comms.contracts import COMMUNICATION_EVENT_TYPES

logger = get_logger("aether.comms.ingest")

# Connector catalog record types → campaign registry sync.
_CATALOG_EVENT_SUFFIXES = (".campaign", ".flow")


async def ingest_normalized_events(
    tenant_id: str,
    events: list[Any],
    *,
    source_connector_id: Optional[str] = None,
) -> dict[str, int]:
    """Persist and publish a batch of connector-normalized events.

    ``events`` are NormalizedEvent instances or dicts with
    event_type/external_id/occurred_at/properties. Returns counters:
    ``{"communications": n, "catalog": n, "skipped": n}``.
    """
    counts = {"communications": 0, "catalog": 0, "skipped": 0}
    for event in events:
        data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
        event_type = data.get("event_type", "")
        if event_type in COMMUNICATION_EVENT_TYPES:
            await _ingest_communication(tenant_id, data, source_connector_id)
            counts["communications"] += 1
        elif any(event_type.endswith(s) for s in _CATALOG_EVENT_SUFFIXES):
            await _register_catalog_record(tenant_id, data, source_connector_id)
            counts["catalog"] += 1
        else:
            counts["skipped"] += 1
    if counts["communications"]:
        metrics.increment(
            "comms_events_ingested_total", counts["communications"],
            labels={"tenant_id": tenant_id, "source": data.get("source", "unknown")},
        )
    return counts


async def _ingest_communication(
    tenant_id: str, data: dict[str, Any], source_connector_id: Optional[str],
) -> None:
    """Durable Bronze write, then bus publish (mirrors /v1/batch ordering)."""
    properties = dict(data.get("properties") or {})
    if source_connector_id:
        properties.setdefault("source_connector_id", source_connector_id)
    event_id = str(data.get("external_id") or uuid.uuid4())
    provider = properties.get("provider") or data.get("source") or "webhook"
    # Deterministic event id namespaced by provider so replays dedupe.
    normalized = {
        "event_id": f"{provider}:{event_id}",
        "tenant_id": tenant_id,
        "event_type": data.get("event_type"),
        "event_family": "comms",
        "session_id": properties.get("session_id"),
        "anonymous_id": properties.get("anonymous_id"),
        "user_id": properties.get("recipient_entity_id") or properties.get("profile_id"),
        "properties": properties,
        "context": {"tenantId": tenant_id, "sourceConnectorId": source_connector_id},
        "timestamp": data.get("occurred_at"),
        "received_at": _now(),
        "ingested_at": _now(),
        "batch_id": f"connector:{provider}",
        "schema_version": "1.0.0",
        "source": "connector",
    }

    from repositories.lake import BronzeRepository
    bronze = BronzeRepository("sdk_events")
    await bronze.ingest(
        source="connector",
        source_tag=f"connector:{provider}:{tenant_id}",
        provider_record_id=normalized["event_id"],
        payload=normalized,
        schema_version="1.0.0",
        entity_id=normalized.get("user_id") or "",
        entity_type="user",
        tenant_id=tenant_id,
    )

    try:
        from dependencies.providers import get_registry
        from shared.events.events import Event, Topic
        registry = get_registry()
        await registry.producer.publish(Event(
            topic=Topic.SDK_EVENTS_VALIDATED,
            tenant_id=tenant_id,
            source_service="comms.ingest",
            payload=normalized,
        ))
    except Exception as exc:
        # Bronze is durable; a replay of the Bronze range recovers the publish.
        logger.warning("comms_ingest_publish_failed event=%s: %s", normalized["event_id"], exc)
        metrics.increment("comms_ingest_publish_failures_total", labels={"tenant_id": tenant_id})


async def _register_catalog_record(
    tenant_id: str, data: dict[str, Any], source_connector_id: Optional[str],
) -> None:
    """Campaign/flow catalog record → canonical campaign registry + message dims."""
    properties = data.get("properties") or {}
    provider = data.get("source", "unknown")
    external_id = (
        properties.get("external_campaign_id")
        or properties.get("external_flow_id")
        or data.get("external_id")
    )
    if not external_id:
        return
    try:
        from services.campaign.registry import CampaignRegistryService
        registry = CampaignRegistryService()
        campaign = await registry.upsert_external_campaign(
            tenant_id,
            platform=provider,
            external_account_id=properties.get("provider_account_id") or provider,
            external_campaign_id=str(external_id),
            external_campaign_name=properties.get("name"),
            external_status=properties.get("status"),
            source_connector_id=source_connector_id,
            channel=properties.get("channel") or "email",
        )
        # Message dimension rows ride along when the provider includes them.
        for message in properties.get("messages") or []:
            from services.comms.repository import CampaignMessageRepository
            await CampaignMessageRepository().upsert_message({
                "tenant_id": tenant_id,
                "campaign_id": str(campaign["campaign_id"]),
                "provider": provider,
                "provider_account_id": properties.get("provider_account_id"),
                "external_message_id": str(message.get("id") or message.get("external_message_id")),
                "external_template_id": message.get("template_id"),
                "name": message.get("name"),
                "sequence_step": message.get("sequence_step"),
                "variant_id": message.get("variant_id"),
                "channel": properties.get("channel") or "email",
                "source_connector_id": source_connector_id,
            })
    except Exception as exc:
        logger.warning(
            "comms_catalog_register_failed provider=%s external_id=%s: %s",
            provider, external_id, exc,
        )
        metrics.increment("comms_catalog_failures_total", labels={"tenant_id": tenant_id})


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
