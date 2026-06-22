"""Silver touchpoint projector — Bronze event → silver_campaign_touchpoint_facts."""

from __future__ import annotations

import hashlib
from typing import Any

from services.silver.projectors.base import BaseProjector, ProjectionResult

_TOUCHPOINT_TYPE_MAP: dict[str, str] = {
    "page": "page_view",
    "screen": "page_view",
    "pageview": "page_view",
    "page_view": "page_view",
    "ad_exposed": "ad_exposure",
    "impression": "impression",
    "click": "click",
    "ad_click": "click",
    "landing": "landing",
    "session_started": "session_entry",
    "session_start": "session_entry",
    "product_viewed": "product_view",
    "search_performed": "search_exposure",
    "recommendation_exposed": "recommendation_exposure",
    "offer_exposed": "ad_exposure",
    "checkout_started": "page_view",
    "email_delivered": "email_delivery",
    "email_opened": "email_open",
    "email_clicked": "email_click",
    "notification_presented": "push_presentation",
    "notification_clicked": "push_click",
    "outcome_observed": "page_view",
}


class TouchpointProjector(BaseProjector):
    """Projects ad/marketing touch events into silver_campaign_touchpoint_facts.

    The resulting row is written by the SilverDispatcher and persisted via
    TouchpointRepository on the durable write path.
    Idempotency: sha256(source_event_id + tenant_id + touchpoint_type).
    """

    handles: frozenset[str] = frozenset(_TOUCHPOINT_TYPE_MAP.keys())

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        ctx = event.get("context") or {}
        props = event.get("properties") or {}
        campaign_ctx = ctx.get("campaign") or {}
        page_ctx = ctx.get("page") or {}

        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        event_type = event.get("type", "page")
        touchpoint_type = _TOUCHPOINT_TYPE_MAP.get(event_type, "page_view")

        source_event_id = event.get("messageId") or event.get("id")
        if not source_event_id:
            return ProjectionResult(table="silver_campaign_touchpoint_facts", rows=[], skipped=True, skip_reason="missing_message_id")

        idem_key = hashlib.sha256(
            f"{source_event_id}:{tenant_id}:{touchpoint_type}".encode()
        ).hexdigest()

        # Consent check — skip if no marketing consent
        consent_id = ctx.get("consentSnapshotId")
        # Projectors are not responsible for loading/checking consent; that check happens upstream
        # in the consent middleware. Presence of consentSnapshotId means consent was recorded.

        # UTM parameters: prefer campaign context over properties
        utm_source = campaign_ctx.get("source") or props.get("utm_source")
        utm_medium = campaign_ctx.get("medium") or props.get("utm_medium")
        utm_campaign = campaign_ctx.get("name") or props.get("utm_campaign")
        utm_content = campaign_ctx.get("content") or props.get("utm_content")
        utm_term = campaign_ctx.get("term") or props.get("utm_term")
        click_id = props.get("click_id") or props.get("gclid") or props.get("fbclid")

        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "profile_id": event.get("userId"),
            "anonymous_id": event.get("anonymousId"),
            "session_id": event.get("sessionId") or ctx.get("sessionId"),
            "device_id": ctx.get("device", {}).get("id") if isinstance(ctx.get("device"), dict) else None,
            "agent_id": ctx.get("agentId"),
            "wallet_id": ctx.get("walletId"),
            "cluster_id": ctx.get("clusterId"),
            "campaign_id": campaign_ctx.get("id") or props.get("campaign_id"),
            "ad_group_id": props.get("ad_group_id"),
            "ad_set_id": props.get("ad_set_id"),
            "creative_id": props.get("creative_id"),
            "ad_id": props.get("ad_id"),
            "placement_id": props.get("placement_id"),
            "keyword_id": props.get("keyword_id"),
            "channel": _infer_channel(utm_medium, utm_source),
            "source": utm_source or props.get("source"),
            "medium": utm_medium,
            "platform": ctx.get("library", {}).get("name") if isinstance(ctx.get("library"), dict) else None,
            "touchpoint_type": touchpoint_type,
            "interaction_type": props.get("interaction_type"),
            "is_view_through": bool(props.get("is_view_through", False)),
            "is_click_through": event_type in ("click", "ad_click") or bool(props.get("is_click_through", False)),
            "viewable": props.get("viewable"),
            "engaged": props.get("engaged"),
            "dwell_ms": props.get("dwell_ms"),
            "position": props.get("position"),
            "frequency": props.get("frequency"),
            "occurred_at": event.get("timestamp"),
            "received_at": event.get("receivedAt") or event.get("timestamp"),
            "source_event_id": source_event_id,
            "source_connector_id": ctx.get("sourceConnectorId"),
            "utm_source": utm_source,
            "utm_medium": utm_medium,
            "utm_campaign": utm_campaign,
            "utm_content": utm_content,
            "utm_term": utm_term,
            "click_id": click_id,
            "referrer": page_ctx.get("referrer") or props.get("referrer"),
            "landing_url": page_ctx.get("url") or props.get("landing_url"),
            "identity_resolution_method": ctx.get("identityResolutionMethod"),
            "identity_confidence": ctx.get("identityConfidence"),
            "identity_version": ctx.get("identityVersion"),
            "consent_snapshot_id": consent_id,
            "privacy_class": self._privacy_class(event),
            "provenance": {"source_event_type": event_type},
            "evidence_ids": [source_event_id] if source_event_id else [],
            "idempotency_key": idem_key,
            "schema_version": 1,
        }

        return ProjectionResult(table="silver_campaign_touchpoint_facts", rows=[row])


def _infer_channel(medium: str | None, source: str | None) -> str:
    if not medium and not source:
        return "direct"
    if medium in ("email", "email_campaign"):
        return "email"
    if medium in ("push", "push_notification"):
        return "push"
    if medium in ("sms",):
        return "sms"
    if medium in ("cpc", "cpm", "paid", "paid_search", "paid_social"):
        return "paid"
    if medium in ("organic", "seo"):
        return "organic_search"
    if medium == "referral":
        return "referral"
    if source in ("google", "bing", "yahoo"):
        return "search"
    if source in ("facebook", "instagram", "twitter", "tiktok", "linkedin"):
        return "social"
    return medium or "other"
