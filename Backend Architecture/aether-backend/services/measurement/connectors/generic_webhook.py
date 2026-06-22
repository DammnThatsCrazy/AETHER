"""Generic webhook connector — accepts spend/conversion events via HTTP POST."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from services.measurement.connectors.base import BaseConnector, ConnectorHealth, SyncResult
from services.measurement.repositories.conversion_repo import ConversionRepository
from services.measurement.repositories.spend_repo import SpendRepository
from services.measurement.repositories.touchpoint_repo import TouchpointRepository

logger = logging.getLogger("aether.measurement.connectors.generic_webhook")

_CONNECTOR_TYPE = "generic_webhook"


class GenericWebhookConnector(BaseConnector):
    """Connector that processes pre-parsed webhook payloads.

    Unlike platform-specific connectors, this connector is called synchronously
    during webhook request handling rather than on a scheduled sync interval.
    sync_incremental() and backfill() are no-ops here — data arrives push-based.

    Payload types supported (via process_event):
      - "spend_record" → writes to spend_records
      - "conversion" → writes to canonical_conversions
      - "touchpoint" → writes to silver_campaign_touchpoint_facts
    """

    connector_type = _CONNECTOR_TYPE

    def __init__(self, connector_id: str, tenant_id: str, config: dict[str, Any], cursor_state: dict[str, Any]) -> None:
        super().__init__(connector_id, tenant_id, config, cursor_state)
        self._spend_repo = SpendRepository()
        self._conversion_repo = ConversionRepository()
        self._touchpoint_repo = TouchpointRepository()

    async def process_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route and persist an incoming webhook payload.

        Returns a status dict with the record type and ID written.
        """
        event_type = payload.get("type") or payload.get("event_type")

        if event_type == "spend_record":
            return await self._handle_spend(payload)
        elif event_type in ("conversion", "order_completed", "payment_confirmed"):
            return await self._handle_conversion(payload)
        elif event_type in ("touchpoint", "pageview", "click", "impression"):
            return await self._handle_touchpoint(payload)
        else:
            logger.warning("Unknown webhook event_type=%s connector=%s", event_type, self.connector_id)
            return {"status": "ignored", "event_type": event_type}

    async def _handle_spend(self, payload: dict[str, Any]) -> dict[str, Any]:
        idem_key = payload.get("idempotency_key") or hashlib.sha256(
            f"{self.tenant_id}:{payload.get('campaign_id')}:{payload.get('period_start')}:{payload.get('source_record_id')}".encode()
        ).hexdigest()

        row = {**payload, "tenant_id": self.tenant_id, "idempotency_key": idem_key,
               "source_connector_id": self.connector_id}
        await self._spend_repo.upsert(row)
        return {"status": "written", "type": "spend_record", "idempotency_key": idem_key}

    async def _handle_conversion(self, payload: dict[str, Any]) -> dict[str, Any]:
        dedup_key = payload.get("deduplication_key") or hashlib.sha256(
            f"{self.tenant_id}:{payload.get('conversion_type')}:{payload.get('source_event_id') or payload.get('order_id')}".encode()
        ).hexdigest()
        row = {
            **payload,
            "tenant_id": self.tenant_id,
            "deduplication_key": dedup_key,
            "source_connector_id": self.connector_id,
            "authority_rank": int(payload.get("authority_rank", 50)),
        }
        await self._conversion_repo.upsert(row)
        return {"status": "written", "type": "conversion", "deduplication_key": dedup_key}

    async def _handle_touchpoint(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = {**payload, "tenant_id": self.tenant_id, "source_connector_id": self.connector_id}
        written = await self._touchpoint_repo.upsert(row)
        return {"status": "written", "type": "touchpoint", "touchpoint_id": written.get("touchpoint_id")}

    async def sync_incremental(self, cursor: dict[str, Any]) -> SyncResult:
        # Webhook connector is push-based; no pull sync needed
        return SyncResult(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            spend_records_written=0,
            conversion_records_written=0,
            touchpoint_records_written=0,
            cursor_state=cursor,
        )

    async def backfill(self, start: datetime, end: datetime) -> SyncResult:
        return SyncResult(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            spend_records_written=0,
            conversion_records_written=0,
            touchpoint_records_written=0,
            cursor_state={},
        )

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.connector_id,
            connector_type=_CONNECTOR_TYPE,
            healthy=True,
            status_message="Webhook endpoint active",
        )

    async def validate_credentials(self) -> bool:
        return True
