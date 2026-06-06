"""14 production-shaped inbound connector adapters.

Each adapter overrides test_connection() and pull() with real HTTP calls when
a secret is provided (non-local mode). In local/test mode the base mocked
behavior applies. Secrets are never stored in config — they are resolved by
ConnectorService from the vault and passed per-request.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from services.integrations.connectors.base import (
    BaseConnector,
    ConnectorConfig,
    ConnectionTestResult,
    NormalizedEvent,
    now_iso,
)


def _is_live(secret: Optional[str]) -> bool:
    """Return True when a real API call should be made."""
    return bool(secret) and os.getenv("AETHER_ENV", "local").lower() != "local"


async def _http_get(url: str, headers: dict) -> tuple[int, dict]:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            return r.status_code, r.json() if r.content else {}
    except Exception as exc:
        return 0, {"error": str(exc)}


async def _http_post(url: str, headers: dict, json: dict) -> tuple[int, dict]:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, headers=headers, json=json)
            return r.status_code, r.json() if r.content else {}
    except Exception as exc:
        return 0, {"error": str(exc)}


def _ok(connector_type: str, detail: str = "ok") -> ConnectionTestResult:
    return ConnectionTestResult(connector_type=connector_type, ok=True, status="ok", detail=detail)  # type: ignore[arg-type]


def _err(connector_type: str, detail: str) -> ConnectionTestResult:
    return ConnectionTestResult(connector_type=connector_type, ok=False, status="error", detail=detail)  # type: ignore[arg-type]


class SlackConnector(BaseConnector):
    connector_type = "slack"
    label = "Slack"
    category = "messaging"
    description = "Ingest Slack messages, reactions, and channel activity as graph signals."
    supports_webhook = True
    supports_pull = False
    requires_secret = True
    ingest_event_types = ("slack.message", "slack.reaction", "slack.channel")
    docs_slug = "operations/slack-connector"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        ev = payload.get("event") or {}
        return [NormalizedEvent(event_type=f"slack.{ev.get('type', 'message')}", source="slack",
                                external_id=ev.get("client_msg_id") or payload.get("event_id"),
                                properties={"channel": ev.get("channel"), "user": ev.get("user")})]

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, body = await _http_get(
            "https://slack.com/api/auth.test",
            {"Authorization": f"Bearer {secret}"},
        )
        if status == 200 and body.get("ok"):
            return _ok(self.connector_type, f"Slack workspace: {body.get('team', 'connected')}")
        return _err(self.connector_type, body.get("error", f"HTTP {status}"))


class WebhookConnector(BaseConnector):
    connector_type = "webhook"
    label = "Generic Signed Webhook"
    category = "webhook"
    description = "Ingest events from any system via an HMAC-signed webhook."
    supports_webhook = True
    supports_pull = False
    requires_secret = True
    ingest_event_types = ("webhook.event",)
    docs_slug = "operations/webhook-ingestion"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok:
            return base
        if secret:
            return _ok(self.connector_type, "HMAC signing secret configured")
        return base


class ShopifyConnector(BaseConnector):
    connector_type = "shopify"
    label = "Shopify"
    category = "commerce"
    description = "Ingest Shopify orders, customers, and checkout events."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("shopify.order", "shopify.customer", "shopify.checkout")
    docs_slug = "operations/shopify-connector"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        topic = str(payload.get("topic") or "shopify.order")
        return [NormalizedEvent(event_type=f"shopify.{topic}", source="shopify",
                                external_id=str(payload.get("id")) if payload.get("id") else None,
                                properties={"email": payload.get("email"), "total": payload.get("total_price")})]

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        shop = config.config.get("shop_domain", "")
        if not shop:
            return _err(self.connector_type, "shop_domain missing from config")
        status, body = await _http_get(
            f"https://{shop}/admin/api/2023-10/shop.json",
            {"X-Shopify-Access-Token": secret or ""},
        )
        if status == 200 and body.get("shop"):
            return _ok(self.connector_type, f"Shopify shop: {body['shop'].get('name', shop)}")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        shop = config.config.get("shop_domain", "")
        if not shop:
            return []
        params = "?status=any&limit=50"
        if since:
            params += f"&updated_at_min={since}"
        status, body = await _http_get(
            f"https://{shop}/admin/api/2023-10/orders.json{params}",
            {"X-Shopify-Access-Token": secret or ""},
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="shopify.order",
                source="shopify",
                external_id=str(order.get("id")),
                occurred_at=order.get("updated_at", now_iso()),
                properties={"email": order.get("email"), "total": order.get("total_price"), "status": order.get("financial_status")},
            )
            for order in body.get("orders", [])
        ]


class StripeConnector(BaseConnector):
    connector_type = "stripe"
    label = "Stripe (ingestion)"
    category = "billing"
    description = "Ingest Stripe payment, invoice, and subscription events as graph signals."
    supports_webhook = True
    supports_pull = False
    requires_secret = True
    ingest_event_types = ("stripe.invoice.paid", "stripe.customer.created", "stripe.charge.succeeded")
    docs_slug = "operations/stripe-connector"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        return [NormalizedEvent(event_type=f"stripe.{payload.get('type', 'event')}", source="stripe",
                                external_id=str(payload.get("id")) if payload.get("id") else None,
                                properties={"object": (payload.get("data") or {}).get("object", {}).get("object")})]

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, body = await _http_get(
            "https://api.stripe.com/v1/balance",
            {"Authorization": f"Bearer {secret}"},
        )
        if status == 200:
            return _ok(self.connector_type, "Stripe API key valid")
        return _err(self.connector_type, (body.get("error") or {}).get("message", f"HTTP {status}"))


class HubSpotConnector(BaseConnector):
    connector_type = "hubspot"
    label = "HubSpot"
    category = "crm"
    description = "Ingest HubSpot contacts, companies, and deals."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    premium = True
    ingest_event_types = ("hubspot.contact", "hubspot.company", "hubspot.deal")
    docs_slug = "operations/hubspot-connector"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, body = await _http_get(
            "https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
            {"Authorization": f"Bearer {secret}"},
        )
        if status == 200:
            return _ok(self.connector_type, "HubSpot token valid")
        return _err(self.connector_type, body.get("message", f"HTTP {status}"))

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        params = "?limit=50&properties=email,firstname,lastname"
        if since:
            params += f"&updatedAfter={since}"
        status, body = await _http_get(
            f"https://api.hubapi.com/crm/v3/objects/contacts{params}",
            {"Authorization": f"Bearer {secret}"},
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="hubspot.contact",
                source="hubspot",
                external_id=str(r.get("id")),
                occurred_at=r.get("updatedAt", now_iso()),
                properties=r.get("properties", {}),
            )
            for r in body.get("results", [])
        ]


class SalesforceConnector(BaseConnector):
    connector_type = "salesforce"
    label = "Salesforce"
    category = "crm"
    description = "Ingest Salesforce leads, accounts, and opportunities."
    supports_webhook = False
    supports_pull = True
    requires_secret = True
    premium = True
    ingest_event_types = ("salesforce.lead", "salesforce.account", "salesforce.opportunity")
    docs_slug = "operations/salesforce-connector"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        instance_url = config.config.get("instance_url", "")
        if not instance_url:
            return _err(self.connector_type, "instance_url missing from config")
        status, body = await _http_get(
            f"{instance_url}/services/data/v57.0",
            {"Authorization": f"Bearer {secret}"},
        )
        if status == 200:
            return _ok(self.connector_type, "Salesforce instance reachable")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        instance_url = config.config.get("instance_url", "")
        if not instance_url:
            return []
        soql = "SELECT+Id,Email,FirstName,LastName,Company+FROM+Lead+ORDER+BY+LastModifiedDate+DESC+LIMIT+50"
        if since:
            soql = f"SELECT+Id,Email,FirstName,LastName,Company+FROM+Lead+WHERE+LastModifiedDate+>={since}+ORDER+BY+LastModifiedDate+DESC+LIMIT+50"
        status, body = await _http_get(
            f"{instance_url}/services/data/v57.0/query?q={soql}",
            {"Authorization": f"Bearer {secret}"},
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="salesforce.lead",
                source="salesforce",
                external_id=str(r.get("Id")),
                properties={"email": r.get("Email"), "company": r.get("Company")},
            )
            for r in body.get("records", [])
        ]


class KlaviyoConnector(BaseConnector):
    connector_type = "klaviyo"
    label = "Klaviyo"
    category = "marketing"
    description = "Ingest Klaviyo profiles and metric events."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("klaviyo.profile", "klaviyo.metric")
    docs_slug = "operations/klaviyo-connector"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, body = await _http_get(
            "https://a.klaviyo.com/api/accounts/",
            {"Authorization": f"Klaviyo-API-Key {secret}", "revision": "2023-10-15"},
        )
        if status == 200:
            return _ok(self.connector_type, "Klaviyo API key valid")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        url = "https://a.klaviyo.com/api/profiles/?page[size]=50"
        status, body = await _http_get(
            url,
            {"Authorization": f"Klaviyo-API-Key {secret}", "revision": "2023-10-15"},
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="klaviyo.profile",
                source="klaviyo",
                external_id=r.get("id"),
                occurred_at=r.get("attributes", {}).get("updated", now_iso()),
                properties=r.get("attributes", {}),
            )
            for r in body.get("data", [])
        ]


class SegmentConnector(BaseConnector):
    connector_type = "segment"
    label = "Segment"
    category = "product_analytics"
    description = "Ingest Segment track/identify/page events."
    supports_webhook = True
    supports_pull = False
    requires_secret = True
    ingest_event_types = ("segment.track", "segment.identify", "segment.page")
    docs_slug = "operations/segment-connector"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        return [NormalizedEvent(event_type=f"segment.{payload.get('type', 'track')}", source="segment",
                                external_id=payload.get("messageId"),
                                properties={"event": payload.get("event"), "userId": payload.get("userId")})]

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok:
            return base
        if secret:
            return _ok(self.connector_type, "Segment write key configured (webhook-only, no pull API)")
        return base


class PostHogConnector(BaseConnector):
    connector_type = "posthog"
    label = "PostHog"
    category = "product_analytics"
    description = "Ingest PostHog product-usage events and persons."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("posthog.event", "posthog.person")
    docs_slug = "operations/posthog-connector"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        host = config.config.get("host", "https://app.posthog.com")
        status, body = await _http_get(
            f"{host}/api/projects/",
            {"Authorization": f"Bearer {secret}"},
        )
        if status == 200:
            return _ok(self.connector_type, "PostHog API key valid")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        host = config.config.get("host", "https://app.posthog.com")
        project_id = config.config.get("project_id", "")
        if not project_id:
            return []
        url = f"{host}/api/projects/{project_id}/persons/?limit=50"
        status, body = await _http_get(url, {"Authorization": f"Bearer {secret}"})
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="posthog.person",
                source="posthog",
                external_id=str(r.get("id")),
                occurred_at=r.get("created_at", now_iso()),
                properties={"distinct_ids": r.get("distinct_ids", []), "properties": r.get("properties", {})},
            )
            for r in body.get("results", [])
        ]


class GA4Connector(BaseConnector):
    connector_type = "ga4"
    label = "Google Analytics 4"
    category = "product_analytics"
    description = "Ingest GA4 events via the Data API (pull)."
    supports_webhook = False
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("ga4.event",)
    docs_slug = "operations/ga4-connector"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        property_id = config.config.get("property_id", "")
        if not property_id:
            return _err(self.connector_type, "property_id missing from config")
        # Validate OAuth token via GA4 Data API metadata endpoint
        status, body = await _http_get(
            f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}/metadata",
            {"Authorization": f"Bearer {secret}"},
        )
        if status == 200:
            return _ok(self.connector_type, f"GA4 property {property_id} reachable")
        return _err(self.connector_type, (body.get("error") or {}).get("message", f"HTTP {status}"))

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        property_id = config.config.get("property_id", "")
        if not property_id:
            return []
        # Run a basic active_users report
        status, body = await _http_post(
            f"https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport",
            {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            {
                "dimensions": [{"name": "eventName"}],
                "metrics": [{"name": "eventCount"}],
                "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}],
                "limit": 50,
            },
        )
        if status != 200:
            return []
        rows = body.get("rows", [])
        return [
            NormalizedEvent(
                event_type="ga4.event",
                source="ga4",
                properties={
                    "event_name": (r.get("dimensionValues") or [{}])[0].get("value"),
                    "event_count": (r.get("metricValues") or [{}])[0].get("value"),
                },
            )
            for r in rows
        ]


class JiraConnector(BaseConnector):
    connector_type = "jira"
    label = "Jira"
    category = "project"
    description = "Ingest Jira issue and workflow events."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("jira.issue_created", "jira.issue_updated")
    docs_slug = "operations/jira-linear-connectors"

    def _base_url(self, config: ConnectorConfig) -> str:
        domain = config.config.get("domain", "")
        return f"https://{domain}.atlassian.net" if domain else ""

    def _auth_header(self, config: ConnectorConfig, secret: str) -> str:
        import base64
        email = config.config.get("user_email", "")
        token = base64.b64encode(f"{email}:{secret}".encode()).decode()
        return f"Basic {token}"

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        base_url = self._base_url(config)
        if not base_url:
            return _err(self.connector_type, "domain missing from config")
        status, body = await _http_get(
            f"{base_url}/rest/api/3/myself",
            {"Authorization": self._auth_header(config, secret or ""),
             "Accept": "application/json"},
        )
        if status == 200:
            return _ok(self.connector_type, f"Jira user: {body.get('displayName', 'authenticated')}")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        base_url = self._base_url(config)
        if not base_url:
            return []
        jql = "ORDER BY updated DESC"
        if since:
            jql = f"updated >= '{since}' ORDER BY updated DESC"
        status, body = await _http_get(
            f"{base_url}/rest/api/3/search?jql={jql}&maxResults=50&fields=summary,status,assignee,updated",
            {"Authorization": self._auth_header(config, secret or ""), "Accept": "application/json"},
        )
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="jira.issue_updated",
                source="jira",
                external_id=issue.get("id"),
                occurred_at=(issue.get("fields") or {}).get("updated", now_iso()),
                properties={
                    "key": issue.get("key"),
                    "summary": (issue.get("fields") or {}).get("summary"),
                    "status": ((issue.get("fields") or {}).get("status") or {}).get("name"),
                },
            )
            for issue in body.get("issues", [])
        ]


class LinearConnector(BaseConnector):
    connector_type = "linear"
    label = "Linear"
    category = "project"
    description = "Ingest Linear issues and comments."
    supports_webhook = True
    supports_pull = False
    requires_secret = True
    ingest_event_types = ("linear.issue", "linear.comment")
    docs_slug = "operations/jira-linear-connectors"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        action = payload.get("action", "update")
        data = payload.get("data") or {}
        return [NormalizedEvent(event_type=f"linear.{payload.get('type', 'issue').lower()}",
                                source="linear",
                                external_id=data.get("id"),
                                properties={"title": data.get("title"), "state": (data.get("state") or {}).get("name"),
                                            "action": action})]

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, body = await _http_post(
            "https://api.linear.app/graphql",
            {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
            {"query": "{ viewer { id name } }"},
        )
        if status == 200 and body.get("data", {}).get("viewer"):
            name = body["data"]["viewer"].get("name", "authenticated")
            return _ok(self.connector_type, f"Linear user: {name}")
        return _err(self.connector_type, f"HTTP {status}")


class ZendeskConnector(BaseConnector):
    connector_type = "zendesk"
    label = "Zendesk"
    category = "support"
    description = "Ingest Zendesk ticket and support events."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("zendesk.ticket", "zendesk.comment")
    docs_slug = "operations/zendesk-intercom-connectors"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        return [NormalizedEvent(event_type="zendesk.ticket", source="zendesk",
                                external_id=str(payload.get("id")) if payload.get("id") else None,
                                properties={"subject": payload.get("subject"), "status": payload.get("status")})]

    def _base_url(self, config: ConnectorConfig) -> str:
        domain = config.config.get("domain", "")
        return f"https://{domain}.zendesk.com" if domain else ""

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        base_url = self._base_url(config)
        if not base_url:
            return _err(self.connector_type, "domain missing from config")
        status, body = await _http_get(
            f"{base_url}/api/v2/users/me",
            {"Authorization": f"Bearer {secret}", "Accept": "application/json"},
        )
        if status == 200 and body.get("user"):
            return _ok(self.connector_type, f"Zendesk user: {body['user'].get('name', 'authenticated')}")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        base_url = self._base_url(config)
        if not base_url:
            return []
        url = f"{base_url}/api/v2/tickets.json?sort_by=updated_at&sort_order=desc&per_page=50"
        status, body = await _http_get(url, {"Authorization": f"Bearer {secret}"})
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="zendesk.ticket",
                source="zendesk",
                external_id=str(t.get("id")),
                occurred_at=t.get("updated_at", now_iso()),
                properties={"subject": t.get("subject"), "status": t.get("status"), "priority": t.get("priority")},
            )
            for t in body.get("tickets", [])
        ]


class IntercomConnector(BaseConnector):
    connector_type = "intercom"
    label = "Intercom"
    category = "support"
    description = "Ingest Intercom conversations and contacts."
    supports_webhook = True
    supports_pull = True
    requires_secret = True
    ingest_event_types = ("intercom.conversation", "intercom.contact")
    docs_slug = "operations/zendesk-intercom-connectors"

    def parse_webhook(self, payload: dict[str, Any]) -> list[NormalizedEvent]:
        topic = payload.get("topic", "conversation.user.created")
        data = (payload.get("data") or {}).get("item") or {}
        return [NormalizedEvent(event_type=f"intercom.{topic.split('.')[0]}", source="intercom",
                                external_id=data.get("id"),
                                properties={"type": data.get("type"), "state": data.get("state")})]

    async def test_connection(self, config: ConnectorConfig, secret: Optional[str] = None) -> ConnectionTestResult:
        base = await super().test_connection(config, secret)
        if not base.ok or not _is_live(secret):
            return base
        status, body = await _http_get(
            "https://api.intercom.io/me",
            {"Authorization": f"Bearer {secret}", "Accept": "application/json"},
        )
        if status == 200 and body.get("type") == "admin":
            return _ok(self.connector_type, f"Intercom admin: {body.get('name', 'authenticated')}")
        return _err(self.connector_type, f"HTTP {status}")

    async def pull(self, config: ConnectorConfig, since: Optional[str] = None, secret: Optional[str] = None) -> list[NormalizedEvent]:
        if not _is_live(secret):
            return []
        url = "https://api.intercom.io/conversations?order=updated_at&sort=desc&per_page=50"
        status, body = await _http_get(url, {"Authorization": f"Bearer {secret}", "Accept": "application/json"})
        if status != 200:
            return []
        return [
            NormalizedEvent(
                event_type="intercom.conversation",
                source="intercom",
                external_id=str(c.get("id")),
                occurred_at=c.get("updated_at", now_iso()),
                properties={"state": c.get("state"), "open": c.get("open")},
            )
            for c in body.get("conversations", [])
        ]


ALL_CONNECTORS: list[type[BaseConnector]] = [
    SlackConnector, WebhookConnector, ShopifyConnector, StripeConnector, HubSpotConnector,
    SalesforceConnector, KlaviyoConnector, SegmentConnector, PostHogConnector, GA4Connector,
    JiraConnector, LinearConnector, ZendeskConnector, IntercomConnector,
]
