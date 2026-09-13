"""Braze connector — branded communications provider (ADR-C11 follow-up).

Pull-model-first. Braze does not sign REST webhooks with a provider-native HMAC
the way other comms providers do, and the durable email lifecycle surfaces
(hard bounces, unsubscribes) are exported through the REST API — so this
adapter's primary ingest path is a REST pull with a durable cursor. The
``parse_webhook`` path still maps REST-pushed message events (Currents-style
payloads and ``/users/track``-recorded custom events) for workspaces that
stream message events to Aether.

Covers:
- REST pull of email lifecycle events (``GET /email/hard_bounces``,
  ``GET /email/unsubscribes``) with a recency cursor, plus campaign + canvas
  catalog sync (``GET /campaigns/list``, ``GET /canvas/list``).
- Event map → canonical communication events (email sent / delivered / opened /
  clicked / bounced / dropped / spam / unsubscribe from Braze message-event and
  ``/users/track`` shapes).
- Suppression: Braze subscription-group unsubscribes and hard bounces flow
  through ``suppression_authority.record_from_event()`` downstream with the
  provider recorded as generic metadata (observe-only, ADR-C1).

Aether is observation-only (ADR-C1): this adapter never calls Braze write
endpoints (no ``POST /subscription/status/set``, no blocklist, no spam-list
removal).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, NoReturn, Optional
from urllib.parse import urlsplit

from shared.security.ssrf import validated_https_host

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    ImplementationStatus,
    NormalizedEvent,
    now_iso,
)

# Region-specific REST base. Real deployments configure ``rest_api_base`` in the
# non-secret connector config (iad-01 default); the region is a deployment fact,
# not a secret.
_API_BASE = "https://rest.iad-01.braze.com"
_EMAIL_LIST_BACKFILL_DAYS = 30

# SSRF hardening (WS8): ``rest_api_base`` is tenant-supplied, so the base URL
# is validated against this allowlist (exact or `.<suffix>` subdomain at a label
# boundary) BEFORE any URL is built. ``validated_https_host`` rejects IP
# literals (loopback / link-local / private / metadata), non-https schemes, and
# any host outside the allowlist, failing closed (None) — so a denied base
# never reaches ``_get``.
BRAZE_ALLOW_SUFFIXES = ("braze.com",)


def _err(connector_type: str, detail: str) -> ConnectionTestResult:
    return ConnectionTestResult(connector_type=connector_type, ok=False, status="error", detail=detail)  # type: ignore[arg-type]


def _raise_pull_denied(connector_type: str) -> NoReturn:
    """Typed pull-denial failure for a denied ``rest_api_base`` (F-4).

    Never a silent empty pull: delegates to the shared adapter helper (log +
    metrics + raise ``ConnectorPullDeniedError`` with a safe_message) so the
    sync surfaces as a failed run instead of "provider returned none".
    """
    from services.integrations.connectors.adapters import _raise_pull_denied as _impl
    _impl(connector_type)  # always raises; typed for static analyzers below

# Braze message-event names (Currents ``users.messages.email.*`` as they appear
# in event exports and REST pushes) → canonical communication event type.
# ``/users/track``-recorded custom event names are normalized (lowercased) below.
# Keys are lowercased to match the normalization lookup (event names are
# folded to lowercase before the map lookup).
BRAZE_EVENT_MAP: dict[str, str] = {
    "users.messages.email.send": "email_sent",
    "users.messages.email.delivered": "email_delivered",
    "users.messages.email.open": "email_opened",
    "users.messages.email.click": "email_clicked",
    "users.messages.email.bounce": "email_bounced",
    "users.messages.email.softbounce": "email_bounced",
    "users.messages.email.deliveryfailure": "email_dropped",
    "users.messages.email.spam": "email_spam_complaint",
    "users.messages.email.unsubscribe": "unsubscribe_observed",
    # Custom events recorded via /users/track that map onto the canonical
    # lifecycle (lowercase, hyphen/space tolerant).
    "email_sent": "email_sent",
    "email_delivered": "email_delivered",
    "email_opened": "email_opened",
    "email_clicked": "email_clicked",
    "email_bounced": "email_bounced",
    "email_dropped": "email_dropped",
    "email_unsubscribed": "unsubscribe_observed",
    "email_spam": "email_spam_complaint",
    "sent email": "email_sent",
    "delivered email": "email_delivered",
    "opened email": "email_opened",
    "clicked email": "email_clicked",
    "bounced email": "email_bounced",
    "unsubscribed": "unsubscribe_observed",
    "unsubscribed from email": "unsubscribe_observed",
}


def _first(props: dict[str, Any], *names: str) -> Any:
    for name in names:
        if props.get(name) is not None:
            return props[name]
    return None


def _email(record: dict[str, Any]) -> Optional[str]:
    user = record.get("user") or {}
    if isinstance(user, dict) and user.get("email_address"):
        return user["email_address"]
    return record.get("email") or record.get("email_address")


def _hash(value: Any) -> Optional[str]:
    if value is None:
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _derive_event_id(record: dict[str, Any], event_type: str) -> str:
    """Deterministic event id when Braze supplies none (idempotent replay)."""
    raw = "|".join(
        str(x or "") for x in (
            _email(record), event_type,
            record.get("time") or record.get("timestamp") or "",
            record.get("dispatch_id") or record.get("send_id") or "",
        )
    )
    return f"br-{_hash(raw) or 'unknown'}"[:64]


def _iso(ts: Any) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(ts or now_iso())


def normalize_braze_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One Braze event record → canonical event (or ``None``).

    Accepts three Braze shapes:

    - **Email-list export entries** returned by the REST pull endpoints
      (``GET /email/hard_bounces`` / ``GET /email/unsubscribes``): a flat dict
      with ``email`` plus ``hard_bounced_at`` / ``unsubscribed_at``.
    - **Message-event shapes** (Currents ``users.messages.email.*`` names as they
      appear in event exports and REST pushes): ``event_type`` + ``user`` block +
      epoch ``time`` + campaign/canvas/dispatch ids.
    - **``/users/track``-recorded custom events**: ``name`` + ``time``.

    Returns ``None`` for records carrying no canonical lifecycle signal.
    """
    if not isinstance(record, dict):
        return None

    # ── Email-list export entries (REST pull surfaces) ───────────────────────
    if record.get("hard_bounced_at"):
        return _list_event(record, "email_bounced",
                           {"bounce_type": "hard"}, "hard_bounced_at")
    if record.get("unsubscribed_at"):
        return _list_event(record, "unsubscribe_observed",
                           {"unsubscribe_scope": "marketing_channel"},
                           "unsubscribed_at")
    if record.get("spam_reported_at"):
        return _list_event(record, "email_spam_complaint", {}, "spam_reported_at")

    # ── Message-event / /users/track-recorded shapes ─────────────────────────
    event_name = str(
        record.get("event_type") or record.get("event") or record.get("name") or ""
    ).strip().lower()
    event_type = BRAZE_EVENT_MAP.get(event_name)
    if not event_type:
        return None

    user = record.get("user")
    if not isinstance(user, dict):
        user = {}
    occurred_at = _iso(record.get("time") or record.get("timestamp") or now_iso())
    provider_event_id = str(record.get("id") or record.get("event_id") or "")
    if not provider_event_id:
        provider_event_id = _derive_event_id(record, event_type)

    bounce_type = None
    if event_type == "email_bounced":
        # Hard-bounce names end in "bounce" but carry no "soft" marker; Braze's
        # SoftBounce must stay soft so it never becomes a hard suppression.
        bounce_type = "soft" if "soft" in event_name else "hard"

    device = record.get("device") if isinstance(record.get("device"), dict) else {}
    properties: dict[str, Any] = {
        "provider": "braze",
        "provider_event_id": provider_event_id,
        "channel": "email",
        "message_category": "marketing",
        "recipient_email": _email(record),
        "external_campaign_id": record.get("campaign_id"),
        "external_flow_id": record.get("canvas_id"),  # Braze canvases → flow slot
        "external_message_id": (
            record.get("message_variation_id") or record.get("dispatch_id")
            or record.get("send_id")
        ),
        "external_template_id": _first(record, "template_id", "template_name"),
        "variant_id": _first(record, "canvas_variation_id", "message_variation_id"),
        "sequence_step": record.get("canvas_step_id"),
        "link_id": _first(record, "link_id", "link_url"),
        "link_url_hash": _hash(record.get("link_url") or record.get("link")),
        "user_agent": device.get("user_agent"),
        "bounce_type": bounce_type,
        "provider_profile_id": user.get("braze_id") or user.get("external_id"),
    }
    if event_type == "unsubscribe_observed":
        properties["unsubscribe_scope"] = "marketing_channel"
    return NormalizedEvent(
        event_type=event_type,
        source="braze",
        external_id=provider_event_id or None,
        occurred_at=str(occurred_at),
        properties={k: v for k, v in properties.items() if v is not None},
    )


def _list_event(
    record: dict[str, Any], event_type: str, extra: dict[str, Any], ts_field: str
) -> NormalizedEvent:
    """Build a canonical event from a REST email-list export entry."""
    occurred_at = _iso(record.get(ts_field) or now_iso())
    email = record.get("email")
    provider_event_id = _derive_event_id(record, event_type)
    properties: dict[str, Any] = {
        "provider": "braze",
        "provider_event_id": provider_event_id,
        "channel": "email",
        "message_category": "marketing",
        "recipient_email": email,
        **extra,
    }
    return NormalizedEvent(
        event_type=event_type,
        source="braze",
        external_id=provider_event_id or None,
        occurred_at=str(occurred_at),
        properties={k: v for k, v in properties.items() if v is not None},
    )


def _headers(secret: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret}",
        "accept": "application/json",
    }


def _is_live(secret: Optional[str]) -> bool:
    return bool(secret)


async def _get(url: str, secret: str) -> tuple[int, dict]:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=_headers(secret))
            return r.status_code, r.json() if r.content else {}
    except Exception as exc:
        return 0, {"error": str(exc)}


class BrazeConnector(BaseConnector):
    connector_type = "braze"
    label = "Braze"
    category = "marketing"
    description = (
        "Observe Braze email delivery and engagement via REST pull (hard "
        "bounces, unsubscribes) and pushed message events. Aether never sends "
        "through this connector."
    )
    supports_webhook = True
    supports_pull = True              # pull-model-first (REST email lists + catalog)
    requires_secret = True
    supports_historical_backfill = True
    supports_reconciliation = False   # no REST per-suppression reconcile surface
    supports_account_discovery = False
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    manifest_data_outputs = (
        "comms.campaigns", "comms.messages", "comms.delivery_events",
        "comms.open_events", "comms.click_events", "comms.bounces",
        "comms.complaints", "comms.unsubscribes", "comms.suppressions",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "email_sent", "email_delivered", "email_opened", "email_clicked",
        "email_bounced", "email_dropped", "email_spam_complaint",
        "unsubscribe_observed", "braze.campaign", "braze.canvas",
    )
    docs_slug = "operations/braze-connector"
    # Braze does not sign REST webhooks with a provider-native HMAC. The primary
    # ingest path is REST pull; any webhook path verifies through Aether's
    # generic timestamped HMAC (the honest generic scheme, matching the catalog
    # entry). This is deliberately NOT a Braze-native scheme — none exists.
    signature_scheme = "hmac"
    # The credential is the Braze REST API key, resolved through the
    # CredentialAuthority (never the payment-rail slot registry).
    required_credentials = ("api_key",)
    # Pull-API protocol facts for the comms conformance ``build_request`` hook:
    # Braze authenticates with ``Authorization: Bearer <REST API key>`` (the
    # standard form → ``pull_auth_header=None``).
    pull_api_base = _API_BASE
    pull_auth_header = None

    # ── Connection ───────────────────────────────────────────────────────────

    @staticmethod
    def _base_for(config: ConnectorConfig) -> str:
        """Allowlisted Braze REST base URL (or ``""`` when the configured
        ``rest_api_base`` is missing-or-rejected; falls back to ``_API_BASE``,
        which is itself an allowlisted subdomain).

        The tenant-configured PATH PREFIX is preserved (F-1 regression fix):
        only the HOST is validated against the allowlist, then the URL is
        reconstructed as ``https://<host><path>`` with the original path
        stripped of a trailing slash only. A denied base still fails closed to
        ``""`` — the path can never smuggle a host change past the gate because
        ``validated_https_host`` rejects userinfo/port/query/fragment tricks and
        the allowlist binds the hostname.
        """
        base = (config.config or {}).get("rest_api_base") or _API_BASE
        raw = str(base)
        host = validated_https_host(raw, allow_suffixes=BRAZE_ALLOW_SUFFIXES)
        if host is None:
            return ""
        # ``urlsplit`` of a scheme-less bare host assigns the whole value to
        # ``path``; only a real URL path (leading ``/``) is preserved.
        parts = urlsplit(raw)
        path = parts.path.rstrip("/") if parts.path.startswith("/") else ""
        return f"https://{host}{path}"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base_result = await super().test_connection(config, secret)
        if not base_result.ok or not _is_live(secret):
            return base_result
        base = self._base_for(config)
        if not base:
            return _err(self.connector_type, "braze: invalid rest_api_base URL")
        status, _ = await _get(
            f"{base}/campaigns/list?page=0", secret  # type: ignore[arg-type]
        )
        if status == 200:
            return ConnectionTestResult(connector_type=self.connector_type, ok=True,
                                        status="ok", detail="Braze REST API key valid")
        return ConnectionTestResult(connector_type=self.connector_type, ok=False,
                                    status="error", detail=f"HTTP {status}")

    # ── Webhook (REST-pushed message events) ────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map Braze REST-pushed message events to canonical communication events.

        Accepts a single message-event dict, a bare array (wrapped as
        ``{"items": [...]}`` by the generic ingest path), a Braze batch
        (``{"events": [...]}``), and email-list export responses
        (``{"emails": [...]}``) for reuse in the pull path.
        """
        records: list[dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, list):
            records = [r for r in items if isinstance(r, dict)]
        elif isinstance(payload, dict) and isinstance(payload.get("events"), list):
            records = [r for r in payload["events"] if isinstance(r, dict)]
        elif isinstance(payload, dict) and isinstance(payload.get("emails"), list):
            records = [r for r in payload["emails"] if isinstance(r, dict)]
        elif isinstance(payload, dict) and (
            payload.get("event_type") or payload.get("name")
            or payload.get("hard_bounced_at") or payload.get("unsubscribed_at")
        ):
            records = [payload]
        elif isinstance(payload, list):
            records = [r for r in payload if isinstance(r, dict)]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_braze_event(record)
            if normalized:
                events.append(normalized)
        return events

    # ── Incremental pull (email lists + campaign/canvas catalog) ────────────

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None,
                   secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        events: list[NormalizedEvent] = []
        events.extend(await self._pull_email_lists(config, since, secret))  # type: ignore[arg-type]
        events.extend(await self._pull_campaigns(config, secret))  # type: ignore[arg-type]
        events.extend(await self._pull_canvases(config, secret))  # type: ignore[arg-type]
        return events

    async def _pull_email_lists(
        self, config: ConnectorConfig, since: Optional[str], secret: str
    ) -> list[NormalizedEvent]:
        """Export hard-bounce + unsubscribe entries over the recency window.

        Braze requires an ``end_date`` plus a ``start_date`` (or ``email``); the
        ``since`` cursor (previous durable position) is the ``start_date``. The
        cursor advances only after durable acceptance (the service layer upserts
        ``ConnectorCursor`` after bronze+comms ingest) — a failed/rate-limited
        run leaves the cursor put and the next run resumes from here.
        """
        base = self._base_for(config)
        if not base:
            _raise_pull_denied(self.connector_type)
        today = datetime.now(timezone.utc).date().isoformat()
        if since:
            # Accept ISO datetime cursors (service stamps ``now_iso()``) and
            # take only the date portion — Braze windows are date-granular.
            start = str(since)[:10]
        else:
            start = (datetime.now(timezone.utc).date()
                     - timedelta(days=_EMAIL_LIST_BACKFILL_DAYS)).isoformat()
        out: list[NormalizedEvent] = []
        out.extend(await self._pull_list(
            f"{base}/email/hard_bounces", start, today, secret))
        out.extend(await self._pull_list(
            f"{base}/email/unsubscribes", start, today, secret))
        return out

    async def _pull_list(
        self, url: str, start: str, end: str, secret: str
    ) -> list[NormalizedEvent]:
        out: list[NormalizedEvent] = []
        offset = 0
        while offset < 10_000:  # bounded per sync run; cursor resumes next run
            status, body = await _get(
                f"{url}?start_date={start}&end_date={end}&limit=500&offset={offset}",
                secret,
            )
            if status == 429:
                break  # rate-limited: cursor stays put, next run resumes
            if status != 200:
                break
            entries = body.get("emails") or []
            for entry in entries:
                if isinstance(entry, dict):
                    normalized = normalize_braze_event(entry)
                    if normalized:
                        out.append(normalized)
            if len(entries) < 500:
                break
            offset += len(entries)
        return out

    async def _pull_campaigns(self, config: ConnectorConfig, secret: str) -> list[NormalizedEvent]:
        base = self._base_for(config)
        if not base:
            _raise_pull_denied(self.connector_type)
        status, body = await _get(
            f"{base}/campaigns/list?page=0", secret,
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="braze.campaign",
                source="braze",
                external_id=r.get("id"),
                occurred_at=now_iso(),
                properties={
                    "external_campaign_id": r.get("id"),
                    "name": r.get("name"),
                    "status": "api_campaign" if r.get("is_api_campaign") else "active",
                    "channel": "email",
                },
            )
            for r in (body.get("campaigns") or [])
            if r.get("id")
        ]

    async def _pull_canvases(self, config: ConnectorConfig, secret: str) -> list[NormalizedEvent]:
        base = self._base_for(config)
        if not base:
            _raise_pull_denied(self.connector_type)
        status, body = await _get(
            f"{base}/canvas/list?page=0", secret,
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="braze.canvas",
                source="braze",
                external_id=r.get("id"),
                occurred_at=now_iso(),
                properties={
                    "external_flow_id": r.get("id"),
                    "name": r.get("name"),
                    "channel": "email",
                },
            )
            for r in (body.get("canvases") or [])
            if r.get("id")
        ]
