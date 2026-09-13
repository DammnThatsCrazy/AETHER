"""Silver touchpoint projector — Bronze event → silver_campaign_touchpoint_facts."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from config.settings import settings
from services.silver.projectors.base import BaseProjector, ProjectionResult
from services.traffic.classifier import SourceClassifier

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
    "email_replied": "email_reply",
    "message_replied_observed": "email_reply",
    "notification_presented": "push_presentation",
    "notification_clicked": "push_click",
    "outcome_observed": "page_view",
    "deep_link_opened": "deep_link_open",
    "app_install_attributed": "app_install",
    "deferred_attribution_resolved": "app_install",
}

# Positive-engagement touchpoint types that must never be created from
# machine-generated activity (scanner clicks, proxy opens) or automated
# replies. Delivery observations are population evidence, not engagement,
# so they pass through regardless (Phase 7 engagement policy).
_ENGAGEMENT_TOUCHPOINT_TYPES = frozenset({
    "email_open", "email_click", "email_reply", "push_click",
})

_source_classifier = SourceClassifier()


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
        # The Web SDK currently emits ``trafficSource`` while newer/server SDKs
        # may emit ``acquisitionEvidence``.  Merge both contracts so the same
        # canonical classifier consumes every supported SDK generation; richer
        # acquisitionEvidence fields win when both are present.
        traffic_source: dict[str, Any] = ctx.get("trafficSource") or {}
        acq_ev: dict[str, Any] = {
            **traffic_source,
            **(ctx.get("acquisitionEvidence") or {}),
        }

        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"
        event_type = event.get("type", "page")
        touchpoint_type = _TOUCHPOINT_TYPE_MAP.get(event_type, "page_view")

        source_event_id = event.get("messageId") or event.get("id")
        if not source_event_id:
            return ProjectionResult(table="silver_campaign_touchpoint_facts", rows=[], skipped=True, skip_reason="missing_message_id")

        # Comms classification propagated by the dispatcher (CommsProjector
        # runs first — ADR-C3 ordering). Machine-generated engagement and
        # automated replies never become positive engagement touchpoints.
        comms_fact: dict[str, Any] = event.get("_comms_fact") or {}
        if touchpoint_type in _ENGAGEMENT_TOUCHPOINT_TYPES:
            if comms_fact.get("suspected_machine_activity"):
                return ProjectionResult(
                    table="silver_campaign_touchpoint_facts", rows=[],
                    skipped=True, skip_reason="machine_activity_excluded",
                )
            if comms_fact.get("automated_response_kind"):
                return ProjectionResult(
                    table="silver_campaign_touchpoint_facts", rows=[],
                    skipped=True, skip_reason="automated_response_excluded",
                )

        idem_key = hashlib.sha256(
            f"{source_event_id}:{tenant_id}:{touchpoint_type}".encode()
        ).hexdigest()
        # Allocate stable identities before canonical-activity emission. The
        # dispatcher emits the activity before SilverFactWriter persists the
        # row, so repository-only UUID defaults would sever the activity ↔
        # touchpoint/revision lineage and make replays create duplicate facts.
        touchpoint_id = str(uuid5(
            NAMESPACE_URL, f"aether:touchpoint:{tenant_id}:{idem_key}"
        ))

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

        # Paid-click evidence is accepted in the canonical acquisition object,
        # a nested properties object, or as legacy top-level properties. Merge
        # all supported shapes before classification so a persisted gclid/fbclid
        # cannot be misclassified as Direct.
        click_id_candidates: dict[str, Any] = {}
        for candidate in (
            acq_ev.get("clickIds"),
            props.get("clickIds"),
            props.get("click_ids"),
        ):
            if isinstance(candidate, dict):
                click_id_candidates.update(candidate)
        for click_id_key in _source_classifier.CLICK_ID_MAP:
            if props.get(click_id_key) and not click_id_candidates.get(click_id_key):
                click_id_candidates[click_id_key] = props[click_id_key]
        click_ids = {
            click_id_key: click_id_candidates[click_id_key]
            for click_id_key in _source_classifier.CLICK_ID_MAP
            if click_id_candidates.get(click_id_key)
        }
        click_id = (
            props.get("click_id")
            or next(iter(click_ids.values()), None)
        )

        raw_referrer = (
            page_ctx.get("referrer")
            or acq_ev.get("referrer")
            or props.get("referrer")
            or ""
        )
        referrer_domain = (
            acq_ev.get("referrerDomain")
            or props.get("referrer_domain")
            or ""
        )
        persisted_referrer_path_hash = (
            page_ctx.get("referrerPathHash")
            or page_ctx.get("referrer_path_hash")
            or acq_ev.get("referrerPathHash")
            or acq_ev.get("referrer_path_hash")
            or props.get("referrer_path_hash")
        )
        verified_referral = (
            acq_ev.get("verifiedReferral")
            or ctx.get("verifiedReferral")
            or event.get("_verified_referral")
        )
        explicit_actor_type = (
            ctx.get("actorType")
            or props.get("actor_type")
            or ("agent" if ctx.get("agentId") else None)
        )
        classified = _source_classifier.classify(
            referrer=raw_referrer,
            referrer_domain=referrer_domain,
            utm_source=utm_source,
            utm_medium=utm_medium,
            utm_campaign=utm_campaign,
            click_ids=click_ids,
            landing_page=(
                page_ctx.get("url")
                or acq_ev.get("landingPage")
                or props.get("landing_url")
                or ""
            ),
            user_agent=(
                ctx.get("userAgent")
                or ctx.get("user_agent")
                or props.get("user_agent")
                or ""
            ),
            verified_referral=verified_referral,
            explicit_actor_type=explicit_actor_type,
            declared_entry_method=(
                acq_ev.get("entryMethod") or acq_ev.get("entry_method")
            ),
        )
        destination_domain = (
            acq_ev.get("destinationDomain") or acq_ev.get("destination_domain")
        )
        destination_path_hash = (
            acq_ev.get("destinationPathHash") or acq_ev.get("destination_path_hash")
        )
        classification_id = str(uuid5(
            NAMESPACE_URL,
            f"aether:source-classification:{touchpoint_id}:{classified.classifier_version}",
        ))

        # Campaign identity evidence — drive resolution in the dispatcher.
        # canonicalCampaignId is an Aether UUID already validated upstream (e.g. from
        # a server-side connector write); the dispatcher validates tenant ownership.
        canonical_campaign_id_hint: str | None = (
            campaign_ctx.get("canonicalCampaignId") or acq_ev.get("canonicalCampaignId")
        )
        # Connector-normalized comm events carry provider campaign evidence in
        # snake_case properties; SDK web events carry it in context/acq evidence.
        external_campaign_id: str | None = (
            campaign_ctx.get("externalCampaignId") or acq_ev.get("externalCampaignId")
            or props.get("external_campaign_id") or props.get("external_flow_id")
        )
        external_account_id: str | None = (
            campaign_ctx.get("externalAccountId") or acq_ev.get("externalAccountId")
            or props.get("provider_account_id")
        )
        # marketing platform (google, meta, …) — distinct from the SDK library name
        marketing_platform: str | None = (
            campaign_ctx.get("platform") or acq_ev.get("platform")
            or props.get("provider")
        )

        row: dict[str, Any] = {
            "touchpoint_id": touchpoint_id,
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
            "channel": _silver_channel(classified.channel),
            "source": classified.source,
            "medium": classified.medium,
            "platform": marketing_platform,
            # Source/referral classification is orthogonal to campaign identity.
            # These dimensions travel beside campaign_id; they never populate it.
            "source_class": classified.source_class,
            "traffic_origin": classified.traffic_origin,
            "economic_class": classified.economic_class,
            "channel_family": classified.channel_family,
            "entry_method": classified.entry_method,
            "proof_level": classified.proof_level,
            "evidence_conflicts": list(classified.evidence_conflicts),
            "referral_mediation_type": classified.referral_mediation_type,
            "ai_provider": classified.ai_provider,
            "ai_product": classified.ai_product,
            "actor_type": classified.actor_type,
            "journey_role": classified.journey_role,
            "evidence_confidence": classified.confidence,
            "verification_level": classified.verification_level,
            "source_classifier_version": classified.classifier_version,
            "source_classified_at": event.get("receivedAt") or event.get("timestamp"),
            "normalized_referrer_domain": classified.normalized_referrer_domain,
            "referrer_path_hash": (
                classified.referrer_path_hash or persisted_referrer_path_hash
            ),
            "source_classification_evidence": classified.evidence_payload(),
            "source_classification_id": classification_id,
            "attribution_eligible": classified.attribution_eligible,
            "verified_referral_link_id": classified.verified_referral_link_id,
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
            # Never persist a raw referrer path/query; the classifier emits an
            # origin-only representation plus a one-way path hash above.
            "referrer": classified.normalized_referrer or None,
            "landing_url": page_ctx.get("url") or acq_ev.get("landingPage") or props.get("landing_url"),
            # Resolution evidence fields — populated here; status/method set by dispatcher
            "external_campaign_id": external_campaign_id,
            "external_account_id": external_account_id,
            # utm_source/utm_medium alone are NOT campaign evidence; the
            # dispatcher only overwrites this when campaign evidence exists.
            "campaign_resolution_status": "not_applicable",
            "campaign_resolution_method": None,
            "campaign_resolution_confidence": None,
            "campaign_resolution_version": None,
            # Private pass-through for dispatcher resolver; popped before DB write
            "_canonical_campaign_id_hint": canonical_campaign_id_hint,
            "_utm_id": utm_id,
            # Comms lineage — links this touchpoint back to the authoritative
            # communication fact for the same real-world event (ADR-C4).
            "communication_fact_id": comms_fact.get("idempotency_key"),
            "external_message_id": comms_fact.get("external_message_id") or props.get("external_message_id"),
            "sequence_step": comms_fact.get("sequence_step"),
            "variant_id": comms_fact.get("variant_id"),
            "link_id": comms_fact.get("link_id") or props.get("link_id"),
            "engagement_confidence": comms_fact.get("engagement_confidence"),
            "machine_activity_probability": comms_fact.get("machine_activity_probability"),
            # WS-C / Invariant #4 (subject-hints-only, default OFF): when ON the
            # client is no longer an authority on identity resolution, so its
            # self-asserted resolution method/confidence/version never persist
            # verbatim; server-side resolution derives them. Legacy mode keeps
            # the client claims until the coordinator flips the flag.
            "identity_resolution_method": None if settings.subject_hints.enabled else ctx.get("identityResolutionMethod"),
            "identity_confidence": None if settings.subject_hints.enabled else ctx.get("identityConfidence"),
            "identity_version": None if settings.subject_hints.enabled else ctx.get("identityVersion"),
            "consent_snapshot_id": consent_id,
            "privacy_class": self._privacy_class(event),
            "provenance": {
                "source_event_type": event_type,
                "source_classifier_version": classified.classifier_version,
                "source_evidence_signals": list(classified.evidence),
                "source_evidence_conflicts": list(classified.evidence_conflicts),
                "raw_referrer_present": bool(raw_referrer),
                # Destination evidence is navigation context, never a
                # classification input (classification stays source-only).
                "destination_domain": destination_domain,
                "destination_path_hash": destination_path_hash,
            },
            "evidence_ids": [source_event_id] if source_event_id else [],
            "idempotency_key": idem_key,
            "schema_version": 2,
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


def _silver_channel(channel: str) -> str:
    """Translate classifier display channels into the established Silver vocabulary.

    v3 splits the historical blanket "paid" channel into paid_search /
    paid_social / display and replaces the unsupported "direct" claim with
    direct_unknown. Downstream consumers (journey channel sequences, gold
    materialization, attribution channel columns) treat these values as opaque
    labels; legacy rows retain their historical values until repaired.
    """
    mapping = {
        "Paid Search": "paid_search",
        "Paid Social": "paid_social",
        "Display": "display",
        "Organic Search": "organic_search",
        "Organic Social": "social",
        "Email": "email",
        "Affiliate": "affiliate",
        "Partner": "partner",
        "Referral": "referral",
        "AI Referral": "ai_referral",
        "Agent Referral": "agent_referral",
        "AI Crawler": "ai_crawler",
        "Machine Referral": "machine_referral",
        "Direct": "direct_unknown",
        "Direct / Unknown": "direct_unknown",
    }
    return mapping.get(channel, channel.lower().replace(" ", "_") if channel else "other")
