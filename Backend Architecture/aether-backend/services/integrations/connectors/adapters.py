"""14 production-shaped inbound connector adapters.

Each adapter declares its descriptor + a representative event mapping. Real
provider API calls are credential-gated TODOs; in local/disabled mode the base
mocked behavior applies. None store secrets in config.
"""
from __future__ import annotations

from typing import Any

from services.integrations.connectors.base import BaseConnector, NormalizedEvent


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


ALL_CONNECTORS: list[type[BaseConnector]] = [
    SlackConnector, WebhookConnector, ShopifyConnector, StripeConnector, HubSpotConnector,
    SalesforceConnector, KlaviyoConnector, SegmentConnector, PostHogConnector, GA4Connector,
    JiraConnector, LinearConnector, ZendeskConnector, IntercomConnector,
]
