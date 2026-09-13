"""Postmark connector — branded communications provider (ADR-C11).

Covers:
- Transactional webhooks (``RecordType`` discriminator) → canonical
  communication events: ``Delivery``, ``Bounce`` (``Type=Transient`` →
  email_deferred, ``Type=Unsubscribe`` → unsubscribe_observed), ``SpamComplaint``,
  ``Open``, ``Click``, and ``SubscriptionChange`` (suppression).
- Auth is Aether's durable server-controlled ``whe_`` endpoint id
  (``endpoint_secret`` scheme — Postmark authenticates with Basic-Auth
  credentials in the webhook URL; no body signature). Tenant ownership resolves
  server-side, never an ``X-Aether-Tenant-ID`` header.

Postmark owns sending and deliverability; Aether only observes (ADR-C1).
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    ImplementationStatus,
    NormalizedEvent,
    now_iso,
)

# Postmark ``RecordType`` → canonical communication event type.
POSTMARK_EVENT_MAP: dict[str, str] = {
    "delivery": "email_delivered",
    "open": "email_opened",
    "click": "email_clicked",
    "bounce": "email_bounced",
    "spamcomplaint": "email_spam_complaint",
}

# Postmark ``Bounce.Type`` refinement — the RecordType mapping is too coarse.
_POSTMARK_BOUNCE_SUBTYPES: dict[str, str] = {
    "transient": "email_deferred",
    "unsubscribe": "unsubscribe_observed",
}

# Postmark ``Bounce.Type`` → bounce_type classification.
_POSTMARK_BOUNCE_HARD = {"hardbounce", "blocked", "bademailaddress", "badsignature",
                         "manuallydeactivate", "unknown"}


def _first(props: dict[str, Any], *names: str) -> Any:
    for name in names:
        if props.get(name) is not None:
            return props[name]
    return None


def _occurred_at(record: dict[str, Any]) -> str:
    """Postmark timestamps are RFC3339 strings; normalize the ``Z`` suffix."""
    value = _first(
        record, "OpenedAt", "ClickedAt", "ReceivedAt", "BouncedAt", "DeliveredAt"
    )
    if not value:
        return now_iso()
    return str(value).replace("Z", "+00:00")


def normalize_postmark_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One Postmark webhook record → canonical event (or ``None``)."""
    record_type = str(record.get("RecordType") or "").strip().lower()

    if record_type == "subscriptionchange":
        return _normalize_subscription_change(record)

    event_type = POSTMARK_EVENT_MAP.get(record_type)
    if not event_type:
        return None

    if event_type == "email_bounced":
        bounce_subtype = str(record.get("Type") or "").strip().lower()
        event_type = _POSTMARK_BOUNCE_SUBTYPES.get(bounce_subtype, event_type)

    metadata = record.get("Metadata") or {}
    properties: dict[str, Any] = {
        "provider": "postmark",
        "provider_event_id": str(record.get("MessageID") or _first(record, "ID", "id") or ""),
        "channel": "email",
        "message_category": "transactional"
        if str(record.get("MessageStream") or "").lower() == "transactional"
        else "marketing",
        "recipient_email": _first(record, "Recipient", "Email"),
        "external_message_id": record.get("MessageID"),
        "link_id": record.get("Link"),
        "tag": record.get("Tag"),
        "message_stream": record.get("MessageStream"),
        "metadata": metadata if isinstance(metadata, dict) else None,
        "user_agent": _first(record, "UserAgent", "ClientName", "Browser"),
        "device_os": record.get("OS"),
        "device_platform": record.get("Platform"),
        "geo": record.get("Geo"),
        "bounce_type": _bounce_type(record.get("Type"))
        if event_type == "email_bounced" else None,
        "bounce_description": record.get("Description")
        if event_type == "email_bounced" else None,
    }
    if event_type == "unsubscribe_observed":
        properties["unsubscribe_scope"] = "marketing_channel"
    return NormalizedEvent(
        event_type=event_type,
        source="postmark",
        external_id=properties["provider_event_id"] or str(record.get("MessageID") or now_iso()),
        occurred_at=_occurred_at(record),
        properties={k: v for k, v in properties.items() if v is not None},
    )


def _bounce_type(postmark_type: Any) -> str:
    if str(postmark_type or "").strip().lower() in _POSTMARK_BOUNCE_HARD:
        return "hard"
    return "soft"


def _normalize_subscription_change(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """Postmark ``SubscriptionChange`` → suppression (or ``None`` on reactivation).

    Postmark signals list changes via ``SuppressSending`` + ``ChangeType``. A
    suppression (``SuppressSending=true``) is provider-scoped; reactivations
    carry no canonical lifecycle event and are dropped.
    """
    suppress_sending = bool(record.get("SuppressSending"))
    if not suppress_sending:
        return None
    return NormalizedEvent(
        event_type="email_suppressed",
        source="postmark",
        external_id=str(record.get("MessageID") or now_iso()),
        occurred_at=_occurred_at(record),
        properties={
            "provider": "postmark",
            "recipient_email": record.get("Recipient"),
            "suppression_reason": "recipient_suppression_request",
            "message_stream": record.get("MessageStream"),
            "change_type": record.get("ChangeType"),
        },
    )


class PostmarkConnector(BaseConnector):
    connector_type = "postmark"
    label = "Postmark"
    category = "marketing"
    description = (
        "Observe Postmark transactional email delivery and engagement events "
        "via webhooks. Aether never sends through this connector."
    )
    supports_webhook = True
    supports_pull = False            # events arrive only via webhook
    requires_secret = False          # the durable whe_ endpoint id is the credential
    supports_historical_backfill = False
    supports_reconciliation = False
    supports_account_discovery = False
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    manifest_data_outputs = (
        "comms.delivery_events", "comms.open_events", "comms.click_events",
        "comms.bounces", "comms.complaints", "comms.suppressions",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "email_delivered", "email_deferred", "email_opened", "email_clicked",
        "email_bounced", "email_spam_complaint", "unsubscribe_observed",
        "email_suppressed",
    )
    docs_slug = "operations/postmark-connector"
    signature_scheme = "endpoint_secret"
    # No vault secret — the durable endpoint id (minted server-side) authenticates.
    required_credentials: tuple[str, ...] = ()

    # ── Connection ───────────────────────────────────────────────────────────

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok:
            return base
        # No secret to probe: Postmark is authenticated by possession of the
        # high-entropy durable endpoint id, which the route resolves server-side
        # before any ingest. Enabled ⇒ ready.
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=True, status="ready",
            detail="Postmark webhook endpoint id is the credential (endpoint_secret)",
        )

    # ── Native webhook signature (endpoint_secret) ───────────────────────────

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str) -> bool:
        """Verified-by-possession: Postmark sends no body signature.

        Postmark authenticates with Basic-Auth credentials baked into the webhook
        URL; Aether's equivalent is the durable ``whe_`` endpoint id, resolved
        server-side before this code runs. A request that reached the route
        possessed the endpoint id — nothing to compare.
        """
        return True

    # ── Webhook ──────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified Postmark webhook to canonical communication events.

        Postmark posts one JSON object per record in an array. The generic ingest
        path wraps a bare array as ``{"items": [...]}``; a single record arrives
        as a dict with a ``RecordType``.
        """
        records: list[dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records = [r for r in items if isinstance(r, dict)]
        elif isinstance(payload, dict) and payload.get("RecordType"):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_postmark_event(record)
            if normalized:
                events.append(normalized)
        return events
