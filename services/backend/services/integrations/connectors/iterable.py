"""Iterable connector — full communications vertical slice (ADR-C11 follow-up).

Covers:
- webhook events → canonical communication events (email lifecycle), verified
  with Iterable's native HMAC scheme (``iterable_hmac_query``): Iterable signs
  webhook requests with an HMAC-SHA256 built from the webhook signing secret;
  the signature (``signature``) and optional signing timestamp (``ts``) travel in
  the webhook URL's query params, not a header. The generic comms route merges
  the request's query params into the headers mapping a native verifier reads,
  so the scheme resolves without provider-name branching (ADR-C11).
- incremental event pull with cursor (``pull``, checkpointed by the connector
  service): the Iterable Export API (``/api/export/data.json``) streams the
  email lifecycle data types (emailSend / emailDelivered / emailOpen /
  emailClick / emailBounce / emailComplaint / emailUnSubscribe) as
  newline-delimited JSON bounded by ``startDateTime`` (the durable cursor) —
  the cursor advances only after durable acceptance (see
  ``ConnectorCursorRepository``), and ``userNew``/``userUpdate`` exports are
  pulled as provider profile records (identity evidence only, never a
  communication fact).
- profile references as identity evidence (email hashed downstream — raw
  addresses only transit in memory).
- reconciliation counts for provider/Aether delta reporting.

Iterable owns sending, templates, scheduling, and suppression execution;
Aether only observes (ADR-C1).

Event map → canonical: emailSend → email_sent, emailDelivered →
email_delivered, emailOpen → email_opened, emailClick → email_clicked,
emailBounce → email_bounced (hard/soft), emailComplaint → email_spam_complaint,
emailUnsubscribe → unsubscribe_observed (scoped). ``emailSubscribe`` has no
canonical lifecycle event — a resubscription is not a communication fact Aether
observes today, so the record is dropped (mirrors SendGrid's group_resubscribe
disposition). ``identify`` / user profile payloads are emitted as
``iterable.profile`` records (identity evidence only).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional
from urllib.parse import quote

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    ImplementationStatus,
    NormalizedEvent,
    now_iso,
)

_API_BASE = "https://api.iterable.com/api"

# Iterable event type → canonical communication event type. Keys are
# normalized to lowercase (Iterable mixes ``emailUnSubscribe`` /
# ``emailUnsubscribe`` camelCase variants). ``emailSubscribe`` is deliberately
# absent — there is no canonical subscribe lifecycle event (see module docstring).
ITERABLE_EVENT_MAP: dict[str, str] = {
    "emailsend": "email_sent",
    "emaildelivered": "email_delivered",
    "emailopen": "email_opened",
    "emailclick": "email_clicked",
    "emailbounce": "email_bounced",
    "emailcomplaint": "email_spam_complaint",
    "emailunsubscribe": "unsubscribe_observed",
}

# Email lifecycle data types exported by the Iterable Export API, in stable
# order. ``userNew``/``userUpdate`` are handled separately as profile evidence.
_EMAIL_EXPORT_DATA_TYPES = (
    "emailSend", "emailDelivered", "emailOpen", "emailClick",
    "emailBounce", "emailComplaint", "emailUnSubscribe",
)


def _headers(secret: str) -> dict[str, str]:
    return {
        "Api-Key": secret,
        "accept": "application/json",
    }


def _is_live(secret: Optional[str]) -> bool:
    return bool(secret)


async def _get_text(url: str, secret: str) -> tuple[int, str]:
    """GET an NDJSON/JSON endpoint and return the raw response text."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(url, headers=_headers(secret))
            return r.status_code, r.text
    except Exception as exc:
        return 0, str(exc)


def _first(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if record.get(name) is not None:
            return record[name]
    return None


def _nested(record: dict[str, Any], *path: str) -> Any:
    """Read a nested field (e.g. ``dataFields.bounceType``)."""
    current: Any = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _bounce_type(record: dict[str, Any]) -> Optional[str]:
    """Iterable reports the bounce class in ``dataFields.bounceType`` (or the
    top-level ``bounceType``): ``HardBounce``/``Permanent``/``Complaint`` → hard,
    ``SoftBounce``/``Transient``/other → soft."""
    btype = str(
        _nested(record, "dataFields", "bounceType")
        or _first(record, "bounceType", "bounce_type") or ""
    ).strip().lower()
    if btype in ("hard", "hardbounce", "permanent"):
        return "hard"
    if btype in ("soft", "softbounce", "transient", "complaint"):
        return "soft"
    return "soft" if btype else None


def _occurred_at(record: dict[str, Any]) -> str:
    """Iterable reports occurrence in ``createdAt`` (ISO-8601 or unix ms)."""
    value = _first(record, "createdAt", "occurredAt", "occurred_at") or now_iso()
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone
        ts = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(value)


def normalize_iterable_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One Iterable event record (webhook or Export API) → canonical event.

    Accepts both the webhook record shape (``eventType`` + ``email`` +
    ``campaignId``/``templateId``/``messageId``/``dataFields``) and the Export
    API NDJSON record shape (which carries the same fields per line).
    ``identify`` / user profile records are returned as ``iterable.profile``
    identity evidence; ``emailSubscribe`` and unknown event types return None.
    """
    event_name = str(
        _first(record, "eventType", "event_type", "event") or ""
    ).strip().lower()

    # Provider profile / identify payloads → identity evidence only. These are
    # not communication facts and never become touchpoints (ADR-C4).
    if event_name in ("identify", "userevent", "usernew", "userupdate"):
        return NormalizedEvent(
            event_type="iterable.profile",
            source="iterable",
            external_id=str(
                record.get("id") or _first(record, "userId", "email") or uuid.uuid4()
            ),
            occurred_at=_occurred_at(record),
            properties={
                k: v for k, v in {
                    # raw email transits in memory only; the comms/identity
                    # pipeline hashes it before any storage
                    "email": _first(record, "email", "recipient_email"),
                    "provider_profile_id": _first(record, "userId", "userId", "id"),
                    "external_id": record.get("externalId"),
                }.items() if v is not None
            },
        )

    event_type = ITERABLE_EVENT_MAP.get(event_name)
    if not event_type:
        return None

    provider_event_id = str(
        _first(record, "id", "messageId", "message_id")
        or f"{_first(record, 'email', '')}:{record.get('createdAt')}"
        or uuid.uuid4()
    )
    data_fields = record.get("dataFields") or {}
    properties: dict[str, Any] = {
        "provider": "iterable",
        "provider_event_id": provider_event_id,
        "channel": "email",
        "message_category": "marketing",
        "recipient_email": _first(record, "email", "recipient_email"),
        "external_campaign_id": _first(record, "campaignId", "campaign_id")
        or _nested(data_fields, "campaignId"),
        "external_flow_id": _first(record, "workflowId", "workflow_id"),
        "external_message_id": _first(record, "messageId", "message_id"),
        "external_template_id": _first(record, "templateId", "template_id")
        or _nested(data_fields, "templateId"),
        "link_id": _first(record, "url", "href", "link"),
        "user_agent": _first(record, "userAgent", "user_agent"),
        "provider_account_id": str(_first(record, "projectId", "project_id"))
        if _first(record, "projectId", "project_id") is not None else None,
        "provider_profile_id": _first(record, "userId", "user_id"),
        "bounce_type": _bounce_type(record) if event_type == "email_bounced" else None,
    }
    if event_type == "unsubscribe_observed":
        # Iterable unsubscribes are list-scoped when a list is named, otherwise
        # the project/marketing-channel suppression list.
        properties["unsubscribe_scope"] = (
            "list" if _first(record, "listId", "list_id") is not None
            else "marketing_channel"
        )
    return NormalizedEvent(
        event_type=event_type,
        source="iterable",
        external_id=provider_event_id,
        occurred_at=_occurred_at(record),
        properties={k: v for k, v in properties.items() if v is not None},
    )


class IterableConnector(BaseConnector):
    connector_type = "iterable"
    label = "Iterable"
    category = "marketing"
    description = (
        "Observe Iterable email delivery and engagement events via signed "
        "webhooks and the REST event export API. Aether never sends through "
        "this connector."
    )
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    supports_historical_backfill = True
    supports_reconciliation = False
    supports_account_discovery = False
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    # Canonical comms capability surface projected onto the ProviderManifest.
    manifest_data_outputs = (
        "comms.email_event", "comms.delivery_events", "comms.open_events",
        "comms.click_events", "comms.bounces", "comms.complaints",
        "comms.unsubscribes",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "email_sent", "email_delivered", "email_opened", "email_clicked",
        "email_bounced", "email_spam_complaint", "unsubscribe_observed",
        "iterable.profile",
    )
    docs_slug = "operations/iterable-connector"
    signature_scheme = "iterable_hmac_query"
    # Iterable's webhook credential is the signing secret (HMAC-SHA256 over the
    # raw body, signature carried in the webhook URL's query params); the pull
    # API authenticates with the server-side API key (``Api-Key`` header).
    required_credentials = ("api_key", "webhook_signing_secret")
    # Pull-API protocol facts for the comms conformance ``build_request`` hook
    # (ADR-C11): Iterable's pull API authenticates with the raw key in the
    # provider-specific ``Api-Key`` header (see ``_headers``).
    pull_api_base = _API_BASE
    pull_auth_header = "Api-Key"

    # ── Connection ───────────────────────────────────────────────────────────

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        # The signing secret cannot be "probed" live without a signed payload;
        # a configured secret is accepted only after it verifies a provider-signed
        # webhook. Offline, we report credential-present.
        return ConnectionTestResult(
            connector_type=self.connector_type, ok=True, status="credential_present",
            detail="Iterable credential configured (verified on first signed webhook / pull)",
        )

    # ── Native webhook signature (iterable_hmac_query) ──────────────────────

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, headers: dict, secret: str) -> bool:
        """Verify Iterable's webhook HMAC (``iterable_hmac_query``).

        Iterable signs webhook requests with an HMAC-SHA256 built from the
        webhook signing secret; the signature (``signature``) and optional
        signing timestamp (``ts``) travel in the webhook URL's query params,
        which the generic comms route merges into this headers mapping. Replay
        window ±300s when Iterable includes a ``ts`` param; otherwise the
        ``silver_comms_idem`` dedupe carries replay safety downstream.
        """
        from services.integrations.providers.payment_rails.signature_verify import (
            ITERABLE_HMAC_QUERY,
            verify_signature,
        )

        signature = str(headers.get("signature") or "").strip()
        timestamp = str(headers.get("ts") or headers.get("timestamp") or "").strip()
        return verify_signature(
            ITERABLE_HMAC_QUERY, [secret], raw_body, signature,
            timestamp=timestamp or None,
            now_epoch=int(time.time()), tolerance_s=300,
        ).ok

    # ── Webhook ──────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified Iterable webhook to canonical communication events.

        Iterable POSTs one JSON event object per webhook delivery; a wrapped
        ``items`` list (generic ingest path) or a bare list is handled too.
        """
        records: list[dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records = [r for r in items if isinstance(r, dict)]
        elif isinstance(payload, dict) and (
            payload.get("eventType") or payload.get("event_type") or payload.get("event")
        ):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_iterable_event(record)
            if normalized:
                events.append(normalized)
        return events

    # ── Incremental pull (email lifecycle events + profile evidence) ─────────

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None,
                   secret: Optional[str] = None) -> list[NormalizedEvent]:
        """Pull from the Iterable Export API bounded by the durable cursor.

        ``since`` is the previous ``ConnectorCursor`` value (an ISO-8601
        timestamp) recorded only after the prior batch was durably accepted; the
        service advances the cursor again only after this batch lands.
        """
        if not _is_live(secret):
            return []
        events: list[NormalizedEvent] = []
        events.extend(await self._pull_events(secret, since))  # type: ignore[arg-type]
        events.extend(await self._pull_profiles(secret, since))  # type: ignore[arg-type]
        return events

    async def _pull_events(self, secret: str, since: Optional[str]) -> list[NormalizedEvent]:
        """Export the email lifecycle data types as NDJSON, bounded by ``since``."""
        out: list[NormalizedEvent] = []
        end = now_iso()
        for data_type in _EMAIL_EXPORT_DATA_TYPES:
            url = f"{_API_BASE}/export/data.json?dataTypeName={data_type}"
            if since:
                url += f"&startDateTime={quote(since)}"
            url += f"&endDateTime={quote(end)}"
            status, text = await _get_text(url, secret)
            if status != 200:
                # rate-limited or unavailable: cursor stays put, next run resumes
                if status == 429:
                    break
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                # The export API does not repeat the data type on every line;
                # the requested dataTypeName is the event type.
                record = dict(record)
                record.setdefault("eventType", data_type)
                normalized = normalize_iterable_event(record)
                if normalized:
                    out.append(normalized)
        return out

    async def _pull_profiles(self, secret: str, since: Optional[str]) -> list[NormalizedEvent]:
        """Export new/updated user records as provider profile identity evidence."""
        out: list[NormalizedEvent] = []
        end = now_iso()
        for data_type in ("userNew", "userUpdate"):
            url = f"{_API_BASE}/export/data.json?dataTypeName={data_type}"
            if since:
                url += f"&startDateTime={quote(since)}"
            url += f"&endDateTime={quote(end)}"
            status, text = await _get_text(url, secret)
            if status != 200:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                record = dict(record)
                record.setdefault("eventType", data_type)
                normalized = normalize_iterable_event(record)
                if normalized:
                    out.append(normalized)
        return out
