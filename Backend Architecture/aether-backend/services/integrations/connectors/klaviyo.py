"""Klaviyo connector — full communications vertical slice (Phase 12).

Covers:
- webhook events → canonical communication events (email lifecycle),
- incremental event pull with cursor (``pull``, checkpointed by the service),
- campaign + flow sync into the canonical campaign registry (channel=email),
- message dimension sync,
- profile references as identity evidence (email hashed downstream —
  raw addresses only transit in memory),
- reconciliation counts for provider/Aether delta reporting.

Klaviyo owns sending, templates, scheduling, and suppression execution;
Aether only observes (ADR-C1).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectionTestResult,
    ConnectorConfig,
    ImplementationStatus,
    NormalizedEvent,
    now_iso,
)

_API_BASE = "https://a.klaviyo.com/api"
_API_REVISION = "2024-10-15"

# Klaviyo metric name → canonical communication event type.
KLAVIYO_METRIC_MAP: dict[str, str] = {
    "sent email": "email_sent",
    "delivered email": "email_delivered",
    "received email": "email_delivered",  # Klaviyo's legacy name for delivery
    "opened email": "email_opened",
    "clicked email": "email_clicked",
    "bounced email": "email_bounced",
    "dropped email": "email_dropped",
    "marked email as spam": "email_spam_complaint",
    "unsubscribed": "unsubscribe_observed",
    "unsubscribed from list": "unsubscribe_observed",
    "replied to email": "email_replied",
    "received sms": "message_received_observed",
    "sent sms": "message_sent_observed",
    "clicked sms": "notification_clicked",
}


def _headers(secret: str) -> dict[str, str]:
    return {
        "Authorization": f"Klaviyo-API-Key {secret}",
        "revision": _API_REVISION,
        "accept": "application/json",
    }


def _is_live(secret: Optional[str]) -> bool:
    import os
    return bool(secret)


async def _get(url: str, secret: str) -> tuple[int, dict]:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, headers=_headers(secret))
            return r.status_code, r.json() if r.content else {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def normalize_klaviyo_event(record: dict[str, Any]) -> Optional[NormalizedEvent]:
    """One Klaviyo event record (webhook or Events API) → canonical event.

    Accepts both the modern JSON:API shape (``{"type": "event",
    "attributes": {...}}``) and flattened webhook test payloads.
    """
    attrs = record.get("attributes") or record
    metric = attrs.get("metric") or {}
    if isinstance(metric, dict):
        metric_name = (
            (metric.get("data") or {}).get("attributes", {}).get("name")
            if "data" in metric else metric.get("name")
        ) or ""
    else:
        metric_name = str(metric)
    metric_name = metric_name or str(attrs.get("event") or attrs.get("metric_name") or "")

    event_type = KLAVIYO_METRIC_MAP.get(metric_name.strip().lower())
    if not event_type:
        return None

    event_props = attrs.get("event_properties") or attrs.get("properties") or {}
    profile = (
        (record.get("profile") or {}).get("attributes")
        or attrs.get("profile") or {}
    )
    provider_event_id = str(
        record.get("id") or attrs.get("event_id") or uuid.uuid4()
    )
    occurred_at = (
        attrs.get("datetime") or attrs.get("timestamp") or now_iso()
    )
    if isinstance(occurred_at, (int, float)):
        from datetime import datetime, timezone
        occurred_at = datetime.fromtimestamp(occurred_at, tz=timezone.utc).isoformat()

    bounce_type = None
    if event_type == "email_bounced":
        bounce_type = "hard" if str(event_props.get("Bounce Type", "")).lower() in ("hard", "hardbounce") else "soft"

    properties: dict[str, Any] = {
        "provider": "klaviyo",
        "provider_event_id": provider_event_id,
        "channel": "email" if event_type.startswith("email") or event_type == "unsubscribe_observed" else "message",
        "message_category": "marketing",
        "recipient_email": profile.get("email") or event_props.get("$email"),
        "external_campaign_id": _first(event_props, "$message", "Campaign ID", "campaign_id"),
        "external_flow_id": _first(event_props, "$flow", "Flow ID", "flow_id"),
        "external_message_id": _first(event_props, "$message", "Message ID", "message_id"),
        "external_template_id": _first(event_props, "Template ID", "template_id"),
        "variant_id": _first(event_props, "$variation", "Variation ID"),
        "link_id": _first(event_props, "URL", "url", "href"),
        "bounce_type": bounce_type,
        "user_agent": _first(event_props, "User Agent", "user_agent"),
        "provider_profile_id": record.get("profile_id") or profile.get("id"),
    }
    if event_type == "unsubscribe_observed":
        properties["unsubscribe_scope"] = (
            "list" if "list" in metric_name.lower() else "marketing_channel"
        )
    return NormalizedEvent(
        event_type=event_type,
        source="klaviyo",
        external_id=provider_event_id,
        occurred_at=str(occurred_at),
        properties={k: v for k, v in properties.items() if v is not None},
    )


def _first(props: dict[str, Any], *names: str) -> Any:
    for name in names:
        if props.get(name) is not None:
            return props[name]
    return None


class KlaviyoConnector(BaseConnector):
    connector_type = "klaviyo"
    label = "Klaviyo"
    category = "marketing"
    description = (
        "Observe Klaviyo email campaigns, flows, messages, and engagement "
        "events. Aether never sends through this connector."
    )
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    supports_historical_backfill = True
    supports_reconciliation = True          # reconcile() below
    supports_account_discovery = True       # Klaviyo account is provider-scoped
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    # Canonical comms capability surface projected onto the ProviderManifest
    # (§9). Expressed as data-output/destination tokens because the manifest
    # models capabilities as its typed outputs, not free-form booleans.
    manifest_data_outputs = (
        "comms.campaigns", "comms.flows", "comms.messages", "comms.profiles",
        "comms.delivery_events", "comms.open_events", "comms.click_events",
        "comms.bounces", "comms.complaints", "comms.unsubscribes",
        "comms.suppressions", "comms.replies",
    )
    manifest_product_destinations = ("campaign_360", "profile_360")
    ingest_event_types = (
        "email_sent", "email_delivered", "email_opened", "email_clicked",
        "email_bounced", "email_dropped", "email_replied",
        "email_spam_complaint", "unsubscribe_observed",
        "message_sent_observed", "message_received_observed",
        "notification_clicked",
        "klaviyo.profile", "klaviyo.campaign", "klaviyo.flow",
    )
    docs_slug = "operations/klaviyo-connector"
    # Pull-API protocol facts for the comms conformance ``build_request`` hook:
    # Klaviyo's pull API authenticates with the raw key in a provider-specific
    # header (see ``_headers``). Declared here so conformance builds an honest
    # synthetic request without branching on provider name (ADR-C11).
    pull_api_base = _API_BASE
    pull_auth_header = "Klaviyo-API-Key"

    # ── Connection ───────────────────────────────────────────────────────────

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, _ = await _get(f"{_API_BASE}/accounts/", secret)  # type: ignore[arg-type]
        if status == 200:
            return ConnectionTestResult(connector_type=self.connector_type, ok=True,
                                        status="ok", detail="Klaviyo API key valid")
        return ConnectionTestResult(connector_type=self.connector_type, ok=False,
                                    status="error", detail=f"HTTP {status}")

    # ── Webhook ──────────────────────────────────────────────────────────────

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        """Map a verified Klaviyo webhook to canonical communication events."""
        records: list[dict[str, Any]] = []
        data = payload.get("data")
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = [data]
        elif isinstance(payload.get("items"), list):
            records = payload["items"]
        elif payload:
            records = [payload]

        events: list[NormalizedEvent] = []
        for record in records:
            normalized = normalize_klaviyo_event(record)
            if normalized:
                events.append(normalized)
        return events

    # ── Incremental pull (events + campaigns + flows + profiles) ─────────────

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None,
                   secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        events: list[NormalizedEvent] = []
        events.extend(await self._pull_events(secret, since))  # type: ignore[arg-type]
        events.extend(await self._pull_campaigns(secret))  # type: ignore[arg-type]
        events.extend(await self._pull_flows(secret))  # type: ignore[arg-type]
        events.extend(await self._pull_profiles(secret, since))  # type: ignore[arg-type]
        return events

    async def _pull_events(self, secret: str, since: Optional[str]) -> list[NormalizedEvent]:
        url = f"{_API_BASE}/events/?include=metric,profile&page[size]=200&sort=datetime"
        if since:
            url += f"&filter=greater-than(datetime,{since})"
        out: list[NormalizedEvent] = []
        pages = 0
        while url and pages < 25:  # bounded per sync run; cursor resumes next run
            status, body = await _get(url, secret)
            if status == 429:
                break  # rate-limited: cursor stays put, next run resumes
            if status != 200:
                break
            included = {i.get("id"): i for i in body.get("included", [])}
            for record in body.get("data", []):
                rel = ((record.get("relationships") or {}).get("profile") or {}).get("data") or {}
                if rel.get("id") and rel["id"] in included:
                    record = {**record, "profile": included[rel["id"]]}
                metric_rel = ((record.get("relationships") or {}).get("metric") or {}).get("data") or {}
                if metric_rel.get("id") and metric_rel["id"] in included:
                    attrs = dict(record.get("attributes") or {})
                    attrs["metric"] = included[metric_rel["id"]].get("attributes", {})
                    record = {**record, "attributes": attrs}
                normalized = normalize_klaviyo_event(record)
                if normalized:
                    out.append(normalized)
            url = ((body.get("links") or {}).get("next")) or None
            pages += 1
        return out

    async def _pull_campaigns(self, secret: str) -> list[NormalizedEvent]:
        status, body = await _get(
            f"{_API_BASE}/campaigns/?filter=equals(messages.channel,'email')&page[size]=50",
            secret,
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="klaviyo.campaign",
                source="klaviyo",
                external_id=r.get("id"),
                occurred_at=(r.get("attributes") or {}).get("updated_at") or now_iso(),
                properties={
                    "external_campaign_id": r.get("id"),
                    "name": (r.get("attributes") or {}).get("name"),
                    "status": (r.get("attributes") or {}).get("status"),
                    "channel": "email",
                },
            )
            for r in body.get("data", [])
        ]

    async def _pull_flows(self, secret: str) -> list[NormalizedEvent]:
        status, body = await _get(f"{_API_BASE}/flows/?page[size]=50", secret)
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="klaviyo.flow",
                source="klaviyo",
                external_id=r.get("id"),
                occurred_at=(r.get("attributes") or {}).get("updated") or now_iso(),
                properties={
                    "external_flow_id": r.get("id"),
                    "name": (r.get("attributes") or {}).get("name"),
                    "status": (r.get("attributes") or {}).get("status"),
                    "channel": "email",
                },
            )
            for r in body.get("data", [])
        ]

    async def _pull_profiles(self, secret: str, since: Optional[str]) -> list[NormalizedEvent]:
        url = f"{_API_BASE}/profiles/?page[size]=100"
        if since:
            url += f"&filter=greater-than(updated,{since})"
        status, body = await _get(url, secret)
        if status != 200:
            return []
        out: list[NormalizedEvent] = []
        for r in body.get("data", []):
            attrs = r.get("attributes") or {}
            out.append(NormalizedEvent(
                event_type="klaviyo.profile",
                source="klaviyo",
                external_id=r.get("id"),
                occurred_at=attrs.get("updated") or now_iso(),
                properties={
                    # raw email transits in memory only; the comms/identity
                    # pipeline hashes it before any storage
                    "email": attrs.get("email"),
                    "provider_profile_id": r.get("id"),
                    "external_id": attrs.get("external_id"),
                },
            ))
        return out

    # ── Reconciliation ───────────────────────────────────────────────────────

    async def reconcile(
        self, config: ConnectorConfig, secret: Optional[str],
        *, external_campaign_id: str,
    ) -> dict[str, Any]:
        """Provider-side counts for one campaign, for provider/Aether delta."""
        if not _is_live(secret):
            return {"available": False, "reason": "local mode or missing credential"}
        status, body = await _get(
            f"{_API_BASE}/campaigns/{external_campaign_id}/", secret,  # type: ignore[arg-type]
        )
        if status != 200:
            return {"available": False, "reason": f"HTTP {status}"}
        attrs = body.get("data", {}).get("attributes", {})
        return {
            "available": True,
            "external_campaign_id": external_campaign_id,
            "provider_status": attrs.get("status"),
            "provider_updated_at": attrs.get("updated_at"),
        }
