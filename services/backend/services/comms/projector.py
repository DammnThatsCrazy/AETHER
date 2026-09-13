"""CommsProjector — authoritative Silver projector for communication events.

Bronze comm event → silver_comms_facts row (Phase 4). This projector:

- handles every canonical communication event type,
- normalizes provider lifecycle states (``EVENT_STATE_MAP``),
- classifies machine engagement deterministically (no model inference),
- hashes any raw recipient address before storage (never persists raw PII),
- derives deterministic idempotency from source evidence,
- owns canonical activity emission for comm events (ADR-C4) via the
  source-derived canonical key — the dispatcher suppresses activity emission
  from other projectors for these event types.

It is independent of frontend concepts and model inference by design.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from services.silver.projectors.base import BaseProjector, ProjectionResult
from services.comms.classification import classify_engagement, detect_automated_response
from services.comms.contracts import (
    COMMUNICATION_EVENT_TYPES,
    ENGAGEMENT_EVENTS,
    EVENT_CHANNEL_MAP,
    EVENT_DIRECTION_MAP,
    EVENT_STATE_MAP,
    ActorKind,
    CommunicationState,
    Direction,
    MessageCategory,
    SCHEMA_VERSION,
    actor_kind_from_provenance,
    canonical_activity_key,
    journey_role_for,
)
from services.comms.mailbox import build_email_alias

COMMS_TABLE = "silver_comms_facts"


def _prop(props: dict[str, Any], *names: str) -> Any:
    """Read a property by snake_case or camelCase name (connector vs SDK)."""
    for name in names:
        if name in props and props[name] is not None:
            return props[name]
    return None


def _snake_and_camel(name: str) -> tuple[str, str]:
    parts = name.split("_")
    camel = parts[0] + "".join(p.title() for p in parts[1:])
    return name, camel


def _p(props: dict[str, Any], name: str) -> Any:
    return _prop(props, *_snake_and_camel(name))


class CommsProjector(BaseProjector):
    """Projects communication events into silver_comms_facts."""

    handles: frozenset[str] = COMMUNICATION_EVENT_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        event_type = event.get("type", "")
        if event_type not in COMMUNICATION_EVENT_TYPES:
            return None

        ctx = event.get("context") or {}
        props = event.get("properties") or {}
        tenant_id = ctx.get("tenantId") or event.get("tenantId") or "default"

        source_event_id = event.get("messageId") or event.get("id")
        if not source_event_id:
            return ProjectionResult(
                table=COMMS_TABLE, rows=[], skipped=True,
                skip_reason="missing_message_id",
            )

        provider = _p(props, "provider") or ctx.get("sourceConnectorType") or "unknown"
        provider_account_id = _p(props, "provider_account_id")
        provider_event_id = _p(props, "provider_event_id") or str(source_event_id)

        # ── Privacy: raw recipient address → tenant-scoped alias hash ────────
        recipient_alias_id = _p(props, "recipient_alias_id")
        recipient_display = _p(props, "recipient_display")
        recipient_is_shared_mailbox = bool(_p(props, "recipient_is_shared_mailbox") or False)
        raw_email = _p(props, "recipient_email") or _p(props, "email")
        if raw_email:
            alias = build_email_alias(str(raw_email), tenant_id)
            if alias:
                recipient_alias_id = recipient_alias_id or alias.alias_hash
                recipient_display = recipient_display or alias.display
                recipient_is_shared_mailbox = alias.is_shared_mailbox

        # ── Classification ───────────────────────────────────────────────────
        channel = _p(props, "channel") or EVENT_CHANNEL_MAP.get(event_type, "email")
        direction = _p(props, "direction") or EVENT_DIRECTION_MAP.get(
            event_type, Direction.OUTBOUND
        )
        direction = direction.value if isinstance(direction, Direction) else str(direction)
        raw_category = _p(props, "message_category") or "marketing"
        try:
            category = MessageCategory(raw_category)
        except ValueError:
            category = MessageCategory.MARKETING
        state = EVENT_STATE_MAP.get(event_type, CommunicationState.OBSERVED)

        agent_id = _p(props, "agent_id") or ctx.get("agentId")
        actor_kind = _p(props, "actor_kind")
        if not actor_kind:
            actor_kind = actor_kind_from_provenance(
                direction=direction,
                agent_id=agent_id,
                sender_is_organization=bool(_p(props, "organization_id") or ctx.get("orgId")),
                category=category,
            ).value

        # ── Machine engagement (deterministic rules only) ────────────────────
        automated_kind: Optional[str] = None
        if event_type in ("email_replied", "message_replied_observed"):
            automated_kind = _p(props, "automated_response_kind") or detect_automated_response(
                subject=_p(props, "subject"),
                headers=_p(props, "headers") or {},
                from_address_local=_p(props, "from_address_local"),
            )

        classification = classify_engagement(
            event_type,
            user_agent=_p(props, "user_agent"),
            ip_class=_p(props, "ip_class"),
            seconds_since_delivery=_num(_p(props, "seconds_since_delivery")),
            clicked_all_links=bool(_p(props, "clicked_all_links") or False),
            has_follow_up_session=bool(_p(props, "has_follow_up_session") or False),
            has_authenticated_session=bool(_p(props, "has_authenticated_session") or False),
            provider_flags=_p(props, "provider_flags") or {},
        )
        is_engagement = event_type in ENGAGEMENT_EVENTS

        journey_role = journey_role_for(
            event_type,
            suspected_machine_activity=classification.suspected_machine_activity,
            is_automated_response=automated_kind is not None,
        )

        # ── Deterministic idempotency from source evidence (replay-safe) ─────
        idem_key = _p(props, "idempotency_key") or hashlib.sha256(
            f"{tenant_id}:{provider}:{provider_account_id or ''}:{provider_event_id}:{event_type}".encode()
        ).hexdigest()

        activity_key = canonical_activity_key(
            tenant_id, provider, provider_account_id, provider_event_id, event_type
        )

        occurred_at = event.get("timestamp") or datetime.now(timezone.utc).isoformat()

        row: dict[str, Any] = {
            # base lineage
            "tenant_id": tenant_id,
            "source_event_id": str(source_event_id),
            "source_event_type": event_type,
            "actor_id": ctx.get("actorId"),
            "user_id": event.get("userId"),
            "anonymous_id": event.get("anonymousId"),
            "org_id": ctx.get("orgId"),
            "occurred_at": occurred_at,
            "received_at": event.get("receivedAt") or occurred_at,
            "consent_snapshot_id": ctx.get("consentSnapshotId") or _p(props, "consent_snapshot_id"),
            "privacy_class": "behavioral_pii" if recipient_alias_id else "behavioral",
            "idempotency_key": idem_key,
            "payload": _safe_payload(props),
            # legacy columns (kept populated for backward compatibility)
            "comms_type": event_type,
            "deliverability": state.value,
            "message_id": _p(props, "external_message_id"),
            "support_case_id": _p(props, "support_case_id"),
            # provider
            "provider": provider,
            "provider_account_id": provider_account_id,
            "provider_event_id": provider_event_id,
            "source_connector_id": _p(props, "source_connector_id") or ctx.get("sourceConnectorId"),
            # classification
            "channel": channel,
            "direction": direction,
            "message_category": category.value,
            "communication_state": state.value,
            "journey_role": journey_role.value,
            "actor_kind": actor_kind,
            # identity references
            "sender_entity_id": _p(props, "sender_entity_id") or agent_id or ctx.get("orgId"),
            "recipient_entity_id": _p(props, "recipient_entity_id") or event.get("userId"),
            "recipient_alias_id": recipient_alias_id,
            "recipient_display": recipient_display,
            "recipient_is_shared_mailbox": recipient_is_shared_mailbox,
            "profile_id": _p(props, "profile_id") or event.get("userId"),
            "cluster_id": _p(props, "cluster_id") or ctx.get("clusterId"),
            "organization_id": _p(props, "organization_id") or ctx.get("orgId"),
            "agent_id": agent_id,
            # campaign references — campaign_id must be a canonical UUID or None;
            # the dispatcher resolves external evidence via CampaignResolver.
            "campaign_id": None,
            "external_campaign_id": _p(props, "external_campaign_id"),
            "external_flow_id": _p(props, "external_flow_id"),
            "external_message_id": _p(props, "external_message_id"),
            "external_thread_id": _p(props, "external_thread_id"),
            "external_template_id": _p(props, "external_template_id"),
            "sequence_step": _int(_p(props, "sequence_step")),
            "variant_id": _p(props, "variant_id"),
            "link_id": _p(props, "link_id"),
            "link_url_hash": _p(props, "link_url_hash"),
            "audience_id": _p(props, "audience_id"),
            "segment_id": _p(props, "segment_id"),
            # delivery / engagement detail
            "delivery_status": state.value,
            "bounce_type": _p(props, "bounce_type"),
            "suppression_scope": _p(props, "suppression_scope"),
            "unsubscribe_scope": _p(props, "unsubscribe_scope"),
            "engagement_type": event_type if is_engagement else None,
            "engagement_confidence": classification.engagement_confidence if is_engagement else None,
            "engagement_strength": classification.engagement_strength.value if is_engagement else None,
            "machine_activity_probability": classification.machine_activity_probability if is_engagement else None,
            "suspected_machine_activity": classification.suspected_machine_activity if is_engagement else False,
            "automated_response_kind": automated_kind,
            "classifier_version": classification.classifier_version if is_engagement else None,
            # resolution provenance
            "identity_resolution_method": _p(props, "identity_resolution_method") or ctx.get("identityResolutionMethod"),
            "identity_confidence": _num(_p(props, "identity_confidence") or ctx.get("identityConfidence")),
            "campaign_resolution_method": None,
            "campaign_resolution_confidence": None,
            "campaign_resolution_status": "pending" if _has_campaign_evidence(props) else "not_applicable",
            # evidence
            "raw_evidence_ref": _p(props, "raw_evidence_ref"),
            "evidence_ids": [str(source_event_id)],
            "provenance": {
                "source_event_type": event_type,
                "provider": provider,
                "classifier_signals": classification.signals,
            },
            "canonical_activity_key": activity_key,
            "schema_version": SCHEMA_VERSION,
            # resolver pass-through hints (popped by dispatcher before DB write)
            "_canonical_campaign_id_hint": _p(props, "campaign_id"),
            "_utm_id": None,
        }
        return ProjectionResult(table=COMMS_TABLE, rows=[row])


def _has_campaign_evidence(props: dict[str, Any]) -> bool:
    return bool(
        _p(props, "campaign_id") or _p(props, "external_campaign_id")
        or _p(props, "external_flow_id") or _p(props, "external_message_id")
    )


def _safe_payload(props: dict[str, Any]) -> dict[str, Any]:
    """Strip raw PII and oversized content before persisting evidence payload."""
    blocked = {
        "recipient_email", "email", "recipientEmail", "subject", "body",
        "html", "text", "content", "headers", "attachments",
    }
    return {k: v for k, v in props.items() if k not in blocked}


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
