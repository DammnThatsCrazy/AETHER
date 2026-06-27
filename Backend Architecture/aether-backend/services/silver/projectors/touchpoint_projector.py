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
        # AcquisitionEvidence injected by SDK on landing; camelCase keys from JS
        acq_ev: dict[str, Any] = ctx.get("acquisitionEvidence") or {}

        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        event_type = event.get("type", "page")
        touchpoint_type = _TOUCHPOINT_TYPE_MAP.get(event_type, "page_view")

        source_event_id = event.get("messageId") or event.get("id")
        if not source_event_id:
            return ProjectionResult(table="silver_campaign_touchpoint_facts", rows=[], skipped=True, skip_reason="missing_message_id")

        idem_key = hashlib.sha256(
            f"{source_event_id}:{tenant_id}:{touchpoint_type}".encode()
        ).hexdigest()

        consent_id = ctx.get("consentSnapshotId")

        # UTM parameters: prefer campaign context over acquisitionEvidence over properties.
        # campaign_ctx.get("campaign") is the utm_campaign token;
        # campaign_ctx.get("name") is the deprecated field kept for backward compat.
        # AcquisitionEvidence uses camelCase keys (utmSource, utmMedium, …).
        # Fallback to snake_case for backward compat with older SDK payloads.
        utm_source = (
            campaign_ctx.get("source")
            or acq_ev.get("utmSource") or acq_ev.get("source")
            or props.get("utm_source")
        )
        utm_medium = (
            campaign_ctx.get("medium")
            or acq_ev.get("utmMedium") or acq_ev.get("medium")
            or props.get("utm_medium")
        )
        utm_campaign = (
            campaign_ctx.get("campaign")
            or campaign_ctx.get("name")  # deprecated; removed after one SDK release window
            or acq_ev.get("utmCampaign") or acq_ev.get("campaign")
            or props.get("utm_campaign")
        )
        utm_content = (
            campaign_ctx.get("content")
            or acq_ev.get("utmContent") or acq_ev.get("content")
            or props.get("utm_content")
        )
        utm_term = (
            campaign_ctx.get("term")
            or acq_ev.get("utmTerm") or acq_ev.get("term")
            or props.get("utm_term")
        )
        utm_id = campaign_ctx.get("utmId") or acq_ev.get("utmId") or props.get("utm_id")

        click_ids = acq_ev.get("clickIds") or {}
        click_id = (
            props.get("click_id")
            or click_ids.get("gclid")
            or props.get("gclid")
            or click_ids.get("fbclid")
            or props.get("fbclid")
        )

        # Campaign identity evidence — drive resolution in the dispatcher.
        # canonicalCampaignId is an Aether UUID already validated upstream (e.g. from
        # a server-side connector write); the dispatcher validates tenant ownership.
        canonical_campaign_id_hint: str | None = (
            campaign_ctx.get("canonicalCampaignId") or acq_ev.get("canonicalCampaignId")
        )
        external_campaign_id: str | None = (
            campaign_ctx.get("externalCampaignId") or acq_ev.get("externalCampaignId")
        )
        external_account_id: str | None = (
            campaign_ctx.get("externalAccountId") or acq_ev.get("externalAccountId")
        )
        # marketing platform (google, meta, …) — distinct from the SDK library name
        marketing_platform: str | None = (
            campaign_ctx.get("platform") or acq_ev.get("platform")
        )

        has_campaign_evidence = bool(
            canonical_campaign_id_hint or external_campaign_id or utm_id or utm_campaign
        )

        row: dict[str, Any] = {
            "tenant_id": tenant_id,
            "profile_id": event.get("userId"),
            "anonymous_id": event.get("anonymousId"),
            "session_id": event.get("sessionId") or ctx.get("sessionId"),
            "device_id": ctx.get("device", {}).get("id") if isinstance(ctx.get("device"), dict) else None,
            "agent_id": ctx.get("agentId"),
            "wallet_id": ctx.get("walletId"),
            "cluster_id": ctx.get("clusterId"),
            # campaign_id is always a canonical Aether UUID or None.
            # The dispatcher calls CampaignResolver and writes the resolved UUID.
            "campaign_id": None,
            "ad_group_id": props.get("ad_group_id"),
            "ad_set_id": props.get("ad_set_id"),
            "creative_id": props.get("creative_id"),
            "ad_id": props.get("ad_id"),
            "placement_id": props.get("placement_id"),
            "keyword_id": props.get("keyword_id"),
            "channel": _infer_channel(utm_medium, utm_source),
            "source": utm_source or props.get("source"),
            "medium": utm_medium,
            "platform": marketing_platform,
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
            "referrer": page_ctx.get("referrer") or acq_ev.get("referrer") or props.get("referrer"),
            "landing_url": page_ctx.get("url") or acq_ev.get("landingPage") or props.get("landing_url"),
            # Resolution evidence fields — populated here; status/method set by dispatcher
            "external_campaign_id": external_campaign_id,
            "external_account_id": external_account_id,
            "campaign_resolution_status": "not_applicable" if not has_campaign_evidence else "not_applicable",
            "campaign_resolution_method": None,
            "campaign_resolution_confidence": None,
            "campaign_resolution_version": None,
            # Private pass-through for dispatcher resolver; popped before DB write
            "_canonical_campaign_id_hint": canonical_campaign_id_hint,
            "_utm_id": utm_id,
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
