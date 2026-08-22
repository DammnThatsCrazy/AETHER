"""Customer.io connector — branded communications provider (ADR-C11).

Covers:
- Reporting webhooks → canonical communication events (email lifecycle),
  verified with Customer.io's native HMAC scheme (``customerio_hmac_v0``):
  ``X-CIO-Signature`` is hex HMAC-SHA256 over ``v0:{X-CIO-Timestamp}:{raw_body}``.
- Webhook tenant ownership is resolved server-side from the durable ``whe_``
  endpoint registry (never an ``X-Aether-Tenant-ID`` header).

Webhook-first adapter: Customer.io's reporting webhooks are the realtime ingest
path; a certified pull/backfill API is not part of this cohort, so the manifest
honestly declares webhook-only support.

Customer.io owns sending and deliverability; Aether only observes (ADR-C1).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    ImplementationStatus,
    NormalizedEvent,
    now_iso,
)

_API_BASE = "https://track.customer.io/api/v1"

# Customer.io reporting-webhook event names → canonical communication event type.
CUSTOMERIO_EVENT_MAP: dict[str, str] = {
    "email_sent": "email_sent",
    "email_delivered": "email_delivered",
    "email_opened": "email_opened",
    "email_clicked": "email_clicked",
    "email_bounced": "email_bounced",
    "email_spammed": "email_spam_complaint",
    "email_dropped": "email_dropped",
    "unsubscribed": "unsubscribe_observed",
    # email_failed / email_converted have no canonical lifecycle event and are
    # dropped rather than mis-mapped.
}

# Reporting webhooks may also carry a short ``metric`` name; resolve both.
_CUSTOMERIO_METRIC_MAP: dict[str, str] = {
    "sent": "email_sent",
    "delivered": "email_delivered",
    "opened": "email_opened",
    "clicked": "email_clicked",
    "bounced": "email_bounced",
    "spammed": "email_spam_complaint",
    "dropped": "email_dropped",
    "unsubscribed": "unsubscribe_observed",
}


def _bounce_type(record: dict[str, Any]) -> Optional[str]:
    data = record.get("data") or {}
    btype = str(data.get("bounce_type") or record.get("bounce_type") or "").lower()
    if btype in ("hard", "hard_bounce", "permanent"):
        return "hard"
    return "soft"


def normalize_customerio_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One Customer.io reporting-webhook record → canonical event (or ``None``)."""
    event_name = str(record.get("event") or record.get("event_type") or "").strip().lower()
    event_type = CUSTOMERIO_EVENT_MAP.get(event_name)
    if not event_type:
        metric = str(record.get("metric") or "").strip().lower()
        full = _CUSTOMERIO_METRIC_MAP.get(metric)
        if not full:
            return None
        event_type = CUSTOMERIO_EVENT_MAP.get(full) or None
        if not event_type:
            return None

    data = record.get("data") or {}
    occurred_at = data.get("timestamp") or record.get("timestamp") or now_iso()
    if isinstance(occurred_at, (int, float)):
        from datetime import datetime, timezone
        occurred_at = datetime.fromtimestamp(occurred_at, tz=timezone.utc).isoformat()

    properties: dict[str, Any] = {
        "provider": "customerio",
        "provider_event_id": str(
            record.get("event_id") or data.get("delivery_id") or data.get("event_id") or ""
        ),
        "channel": "email",
        "message_category": "marketing",
        "recipient_email": data.get("email_address") or data.get("email"),
        "external_campaign_id": data.get("campaign_id"),
        "external_flow_id": data.get("action_id"),
        "external_message_id": data.get("delivery_id") or data.get("broadcast_id"),
        "link_id": data.get("link"),
        "provider_account_id": str(data.get("broadcast_id") or "") or None,
        "bounce_type": _bounce_type(record) if event_type == "email_bounced" else None,
    }
    return NormalizedEvent(
        event_type=event_type,
        source="customerio",
        external_id=properties["provider_event_id"] or str(data.get("customer_id") or now_iso()),
        occurred_at=str(occurred_at),
        properties={k: v for k, v in properties.items() if v is not None},
    )


class CustomerIOConnector(BaseConnector):
    connector_type = "customerio"
    label = "Customer.io"
    category = "marketing"
    description = (
        "Observe Customer.io email delivery and engagement events via reporting "
        "webhooks (HMAC-verified). Aether never sends through this connector."
    )
    supports_webhook = True
    supports_pull = False            # reporting webhooks are the ingest path
    requires_secret = True
    supports_historical_backfill = False
    supports_reconciliation = False
    supports_account_discovery = False
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    manifest_data_outputs = (
        "comms.delivery_events", "comms.open_events", "comms.click_events",
        "comms.bounces", "comms.complaints", "comms.unsubscribes",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "email_sent", "email_delivered", "email_opened", "email_clicked",
        "email_bounced", "email_dropped", "email_spam_complaint",
        "unsubscribe_observed",
    )
    docs_slug = "operations/customerio-connector"
    signature_scheme = "customerio_hmac_v0"
    # The credential is the Customer.io webhook signing secret.
    required_credentials = ("webhook_signing_secret",)

    # ── Connection ───────────────────────────────────────────────────────────

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not secret:
            return base
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=True, status="credential_present",
            detail="Customer.io webhook signing secret configured",
        )

    # ── Native webhook signature (customerio_hmac_v0) ────────────────────────

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str) -> bool:
        """Verify Customer.io's reporting-webhook HMAC (``X-CIO-Signature``).

        The signed string is ``v0:{X-CIO-Timestamp}:{raw_body}`` — the ``v0:``
        prefix and colons are part of the payload. Replay window ±300s.
        """
        from services.integrations.providers.payment_rails.signature_verify import (
            CUSTOMERIO_HMAC_V0,
            verify_signature,
        )

        signature = str(headers.get("X-CIO-Signature") or "").strip()
        timestamp = str(headers.get("X-CIO-Timestamp") or "").strip()
        return verify_signature(
            CUSTOMERIO_HMAC_V0, [secret], raw_body, signature, timestamp=timestamp,
            now_epoch=int(time.time()), tolerance_s=300,
        ).ok

    # ── Webhook ──────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified Customer.io reporting webhook to canonical events."""
        records: list[dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records = [r for r in items if isinstance(r, dict)]
        elif isinstance(payload, dict) and (payload.get("event") or payload.get("metric")):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_customerio_event(record)
            if normalized:
                events.append(normalized)
        return events
