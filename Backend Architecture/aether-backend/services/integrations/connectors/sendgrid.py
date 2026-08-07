"""SendGrid (Twilio) connector — branded communications provider (ADR-C11).

Covers:
- Event Webhook → canonical communication events (email lifecycle), verified
  with SendGrid's native **ECDSA** signing (``sendgrid_ecdsa``): the stored
  credential is the account's public key — the private key never leaves Twilio,
  so a leaked "secret" cannot forge events.
- Webhook tenant ownership is resolved server-side from the durable ``whe_``
  endpoint registry (never an ``X-Aether-Tenant-ID`` header).

SendGrid has no event export API — event telemetry arrives only through the
Event Webhook — so this adapter is webhook-first (no pull/backfill), honestly
declared on the manifest.

SendGrid owns sending, templates, scheduling, and suppression execution;
Aether only observes (ADR-C1).
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

_API_BASE = "https://api.sendgrid.com/v3"

# SendGrid Event Webhook ``event`` → canonical communication event type.
SENDGRID_EVENT_MAP: dict[str, str] = {
    "processed": "email_processed",
    "deferred": "email_deferred",
    "delivered": "email_delivered",
    "open": "email_opened",
    "click": "email_clicked",
    "bounce": "email_bounced",
    "dropped": "email_dropped",
    "spamreport": "email_spam_complaint",
    "unsubscribe": "unsubscribe_observed",
    "group_unsubscribe": "unsubscribe_observed",
    # group_resubscribe has no canonical event — a resubscription is not a
    # lifecycle change Aether observes today; the record is dropped.
}


def _first(props: dict[str, Any], *names: str) -> Any:
    for name in names:
        if props.get(name) is not None:
            return props[name]
    return None


def _bounce_type(status: Any, reason: Any) -> Optional[str]:
    """SendGrid reports SMTP status in ``status`` (``5.x.x`` hard, ``4.x.x`` soft)."""
    code = str(status or "")
    if code.startswith("5"):
        return "hard"
    if code.startswith("4"):
        return "soft"
    if "hard" in str(reason or "").lower():
        return "hard"
    return "soft"


def normalize_sendgrid_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One SendGrid Event Webhook record → canonical event (or ``None``).

    SendGrid posts one JSON object per event in an array. Fields follow the
    documented Event Webhook schema (``sg_event_id``, unix ``timestamp``,
    ``email``, ``event``, ``url`` for clicks, ``useragent``, SMTP ``status``).
    """
    event_name = str(record.get("event") or "").strip().lower()
    event_type = SENDGRID_EVENT_MAP.get(event_name)
    if not event_type:
        return None

    occurred_at = record.get("timestamp") or now_iso()
    if isinstance(occurred_at, (int, float)):
        from datetime import datetime, timezone
        occurred_at = datetime.fromtimestamp(occurred_at, tz=timezone.utc).isoformat()

    properties: dict[str, Any] = {
        "provider": "sendgrid",
        "provider_event_id": str(record.get("sg_event_id") or record.get("sg_message_id") or ""),
        "channel": "email",
        "message_category": "marketing",
        "recipient_email": record.get("email"),
        "external_campaign_id": record.get("marketing_campaign_id"),
        "external_message_id": record.get("sg_message_id") or record.get("smtp-id"),
        "link_id": record.get("url"),
        "user_agent": record.get("useragent"),
        "bounce_type": _bounce_type(record.get("status"), record.get("reason"))
        if event_type == "email_bounced" else None,
    }
    if event_type == "unsubscribe_observed":
        properties["unsubscribe_scope"] = (
            "list" if event_name == "group_unsubscribe" else "marketing_channel"
        )
    return NormalizedEvent(
        event_type=event_type,
        source="sendgrid",
        external_id=properties["provider_event_id"] or str(record.get("timestamp") or now_iso()),
        occurred_at=str(occurred_at),
        properties={k: v for k, v in properties.items() if v is not None},
    )


class SendGridConnector(BaseConnector):
    connector_type = "sendgrid"
    label = "SendGrid"
    category = "marketing"
    description = (
        "Observe Twilio SendGrid email delivery and engagement events via the "
        "Event Webhook (ECDSA-verified). Aether never sends through this connector."
    )
    supports_webhook = True
    supports_pull = False            # SendGrid has no event export API — webhook-only
    requires_secret = True
    supports_historical_backfill = False
    supports_reconciliation = False
    supports_account_discovery = False
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    # Canonical comms capability surface projected onto the ProviderManifest.
    manifest_data_outputs = (
        "comms.delivery_events", "comms.open_events", "comms.click_events",
        "comms.bounces", "comms.complaints", "comms.unsubscribes",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "email_processed", "email_deferred", "email_delivered", "email_opened",
        "email_clicked", "email_bounced", "email_dropped",
        "email_spam_complaint", "unsubscribe_observed",
    )
    docs_slug = "operations/sendgrid-connector"
    signature_scheme = "sendgrid_ecdsa"
    # The credential is the account's ECDSA *public* key used to verify webhooks.
    required_credentials = ("webhook_signing_secret",)

    # ── Connection ───────────────────────────────────────────────────────────

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not secret:
            return base
        # The public key cannot be "probed" live without a signed payload; a
        # configured secret is accepted only after it verifies a provider-signed
        # webhook. Offline, we report credential-present.
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=True, status="credential_present",
            detail="SendGrid public key configured (verified on first signed webhook)",
        )

    # ── Native webhook signature (sendgrid_ecdsa) ────────────────────────────

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str) -> bool:
        """Verify SendGrid's ECDSA-signed Event Webhook.

        ``X-Twilio-Email-Event-Webhook-Signature`` is base64 DER ECDSA over
        SHA-256(``X-Twilio-Email-Event-Webhook-Timestamp`` + raw body); ``secret``
        is the account's public key (base64 DER or PEM). Replay window ±300s.
        """
        from services.integrations.providers.payment_rails.signature_verify import (
            SENDGRID_ECDSA,
            verify_signature,
        )

        signature = str(headers.get("X-Twilio-Email-Event-Webhook-Signature") or "").strip()
        timestamp = str(headers.get("X-Twilio-Email-Event-Webhook-Timestamp") or "").strip()
        return verify_signature(
            SENDGRID_ECDSA, [secret], raw_body, signature, timestamp=timestamp,
            now_epoch=int(time.time()), tolerance_s=300,
        ).ok

    # ── Webhook ──────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified SendGrid Event Webhook to canonical communication events.

        The generic ingest path wraps a bare array as ``{"items": [...]}``;
        a single-event dict is handled directly.
        """
        records: list[dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records = [r for r in items if isinstance(r, dict)]
        elif isinstance(payload, dict) and payload.get("event"):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_sendgrid_event(record)
            if normalized:
                events.append(normalized)
        return events
