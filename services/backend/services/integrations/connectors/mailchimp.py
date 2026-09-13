"""Mailchimp connector — branded communications provider (ADR-C11).

Covers:
- Marketing webhooks → canonical communication events, covering the lifecycle
  surfaces Mailchimp actually signals (``unsubscribe`` → unsubscribe_observed,
  ``cleaned`` → email_suppressed). Identity/campaign events (``subscribe``,
  ``upemail``, ``profile``, ``campaign``) carry no canonical lifecycle signal and
  are dropped rather than mis-mapped.
- Bodies are ``application/x-www-form-urlencoded`` (not JSON) with ``data[…]``
  bracketed keys; ``service.ingest_webhook`` flattens single values to scalars,
  and this adapter un-flattens ``data[field]`` back to a nested dict.
- Auth is Aether's durable server-controlled ``whe_`` endpoint id
  (``endpoint_secret`` scheme — Mailchimp itself authenticates with a ``secret``
  query parameter in the webhook URL; no HMAC). Tenant ownership resolves
  server-side, never an ``X-Aether-Tenant-ID`` header.
- Setup validation: Mailchimp GET-probes a webhook URL when it is configured and
  expects 200 — handled by ``supports_get_validation``.

Mailchimp owns sending and list hygiene; Aether only observes (ADR-C1).
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

# Mailchimp webhook ``type`` → canonical communication event type.
MAILCHIMP_EVENT_MAP: dict[str, str] = {
    "unsubscribe": "unsubscribe_observed",
    "cleaned": "email_suppressed",
    # subscribe / upemail / profile / campaign are identity + campaign evidence
    # with no canonical lifecycle event — dropped, never mis-mapped.
}

# ``cleaned`` action values → suppression reason.
MAILCHIMP_CLEANED_REASON_MAP: dict[str, str] = {
    "hard": "hard_bounce",
    "abuse": "abuse_complaint",
}


def _unflatten_data(payload: dict[str, Any]) -> dict[str, Any]:
    """Un-flatten Mailchimp's bracketed form keys (``data[email]`` → ``data``).

    ``ingest_webhook`` flattens single-value ``parse_qs`` results to scalars, so
    the adapter receives ``{"type": "unsubscribe", "data[email]": "…"}``. Nested
    keys like ``data[merges][FNAME]`` collapse onto the leaf name (``FNAME``).
    """
    data: dict[str, Any] = {}
    for key, value in payload.items():
        if key.startswith("data[") and key.endswith("]"):
            data[key[len("data["):-1]] = value
    return data


def normalize_mailchimp_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One Mailchimp webhook payload → canonical event (or ``None``).

    ``record`` is either the flat form-encoded dict (``type`` + ``data[field]``
    keys) or a nested ``{"type": …, "data": {…}}`` (e.g. from tests or a future
    JSON transport). Identity/campaign events return ``None``.
    """
    event_type = MAILCHIMP_EVENT_MAP.get(str(record.get("type") or "").strip().lower())
    if not event_type:
        return None

    data = record.get("data")
    if not isinstance(data, dict):
        data = _unflatten_data(record)

    properties: dict[str, Any] = {
        "provider": "mailchimp",
        "provider_event_id": str(data.get("id") or data.get("email") or ""),
        "channel": "email",
        "message_category": "marketing",
        "recipient_email": data.get("email"),
        "external_list_id": data.get("list_id"),
        "external_campaign_id": data.get("campaign_id"),
        "ip_address": data.get("ip_opt") or data.get("ip_signup"),
        "member_rating": data.get("rating"),
    }
    if event_type == "unsubscribe_observed":
        properties["unsubscribe_scope"] = "list"
        if data.get("reason"):
            properties["reason"] = data["reason"]
    elif event_type == "email_suppressed":
        action = str(data.get("action") or "").strip().lower()
        properties["suppression_reason"] = (
            MAILCHIMP_CLEANED_REASON_MAP.get(action, "hard_bounce")
            if action else "hard_bounce"
        )
    return NormalizedEvent(
        event_type=event_type,
        source="mailchimp",
        # Mailchimp's own member id is the stable provider id.
        external_id=properties["provider_event_id"] or None,
        # Mailchimp webhooks carry no timestamp — occurrence is genuinely
        # unknown at normalize time. Emit the "unknown" sentinel (empty) so
        # normalization stays a pure function of the input (idempotency) and
        # let the ingest layer stamp the received time in its place.
        occurred_at="",
        properties={k: v for k, v in properties.items() if v is not None},
    )


class MailchimpConnector(BaseConnector):
    connector_type = "mailchimp"
    label = "Mailchimp"
    category = "marketing"
    description = (
        "Observe Mailchimp list lifecycle events via Marketing webhooks. "
        "Aether never sends through this connector."
    )
    supports_webhook = True
    supports_pull = False            # lifecycle events arrive only via webhook
    requires_secret = False          # the durable whe_ endpoint id is the credential
    supports_historical_backfill = False
    supports_reconciliation = False
    supports_account_discovery = False
    supports_get_validation = True   # Mailchimp GET-probes the URL on setup
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    manifest_data_outputs = (
        "comms.bounces", "comms.unsubscribes", "comms.suppressions",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "unsubscribe_observed", "email_suppressed",
    )
    docs_slug = "operations/mailchimp-connector"
    signature_scheme = "endpoint_secret"
    # No vault secret — the durable endpoint id (minted server-side) authenticates.
    required_credentials: tuple[str, ...] = ()

    # ── Connection ───────────────────────────────────────────────────────────

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok:
            return base
        # No secret to probe: Mailchimp is authenticated by possession of the
        # high-entropy durable endpoint id, which the route resolves server-side
        # before any ingest. Enabled ⇒ ready.
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=True, status="ready",
            detail="Mailchimp webhook endpoint id is the credential (endpoint_secret)",
        )

    # ── Native webhook signature (endpoint_secret) ───────────────────────────

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str) -> bool:
        """Verified-by-possession: Mailchimp sends no body signature.

        Mailchimp authenticates with a ``secret`` query parameter baked into the
        webhook URL; Aether's equivalent is the durable ``whe_`` endpoint id,
        resolved server-side before this code runs. A request that reached the
        route possessed the endpoint id — nothing to compare.
        """
        return True

    # ── Webhook ──────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified Mailchimp webhook to canonical communication events.

        The form-encoded body arrives flat (``type`` + ``data[field]`` keys); a
        nested ``{"type": …, "data": {…}}`` (tests, JSON transport) is handled too.
        """
        records: list[dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records = [r for r in items if isinstance(r, dict)]
        elif isinstance(payload, dict) and (payload.get("type") or payload.get("data")):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_mailchimp_event(record)
            if normalized:
                events.append(normalized)
        return events
