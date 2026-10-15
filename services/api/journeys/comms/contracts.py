"""Canonical communication contract — provider-neutral taxonomy and payload.

Source of truth for the event taxonomy is
``packages/shared/contracts/event-registry.json`` (family ``comms``); this
module defines the semantic layer on top of it: message categories,
directions, actor kinds, journey roles, engagement strengths, lifecycle
state normalization, activity-family routing, and the shared
``CommunicationEventPayload`` all providers normalize into (ADR-C2).

No provider-specific logic belongs here.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


# ── Enums ─────────────────────────────────────────────────────────────────────

class MessageCategory(str, Enum):
    MARKETING = "marketing"
    SALES = "sales"
    TRANSACTIONAL = "transactional"
    SECURITY = "security"
    ACCOUNT = "account"
    SUPPORT = "support"
    OPERATIONAL = "operational"
    AGENT_GENERATED = "agent_generated"


class Direction(str, Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"
    INTERNAL = "internal"
    SYSTEM_GENERATED = "system_generated"


class ActorKind(str, Enum):
    HUMAN = "human"
    ORGANIZATION = "organization"
    AGENT = "agent"
    SERVICE = "service"
    SYSTEM = "system"


class JourneyRole(str, Enum):
    CONTEXT = "context"
    ACTIVE_STEP = "active_step"
    STATE_ONLY = "state_only"
    OUTCOME = "outcome"
    EXCLUDED = "excluded"


class EngagementStrength(str, Enum):
    NONE = "none"
    WEAK = "weak"
    PROBABLE = "probable"
    STRONG = "strong"
    DETERMINISTIC = "deterministic"


class CommunicationState(str, Enum):
    """Normalized provider lifecycle state for a communication fact."""
    QUEUED = "queued"
    PROCESSED = "processed"
    SENT = "sent"
    DELIVERED = "delivered"
    DEFERRED = "deferred"
    BOUNCED = "bounced"
    DROPPED = "dropped"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    COMPLAINED = "complained"
    SUPPRESSED = "suppressed"
    UNSUBSCRIBED = "unsubscribed"
    RECEIVED = "received"
    OBSERVED = "observed"


class SuppressionScope(str, Enum):
    MESSAGE = "message"
    CAMPAIGN = "campaign"
    LIST = "list"
    SEGMENT = "segment"
    PROVIDER_ACCOUNT = "provider_account"
    MARKETING_CHANNEL = "marketing_channel"
    TENANT_WIDE = "tenant_wide"
    ALIAS_WIDE = "alias_wide"


# ── Event taxonomy ────────────────────────────────────────────────────────────

# All canonical communication event types this domain owns. Must stay a
# subset of the comms family in event-registry.json (enforced by
# tests/unit/comms/test_comms_contracts.py).
EMAIL_LIFECYCLE_EVENTS: frozenset[str] = frozenset({
    "email_queued", "email_processed", "email_sent", "email_delivered",
    "email_deferred", "email_bounced", "email_dropped", "email_opened",
    "email_clicked", "email_replied", "email_spam_complaint",
    "email_suppressed", "unsubscribe_observed",
})

CHANNEL_NEUTRAL_EVENTS: frozenset[str] = frozenset({
    "message_sent_observed", "message_received_observed",
    "message_replied_observed",
    "notification_delivered", "notification_opened", "notification_clicked",
})

COMMUNICATION_EVENT_TYPES: frozenset[str] = EMAIL_LIFECYCLE_EVENTS | CHANNEL_NEUTRAL_EVENTS

# event type → normalized lifecycle state
EVENT_STATE_MAP: dict[str, CommunicationState] = {
    "email_queued": CommunicationState.QUEUED,
    "email_processed": CommunicationState.PROCESSED,
    "email_sent": CommunicationState.SENT,
    "email_delivered": CommunicationState.DELIVERED,
    "email_deferred": CommunicationState.DEFERRED,
    "email_bounced": CommunicationState.BOUNCED,
    "email_dropped": CommunicationState.DROPPED,
    "email_opened": CommunicationState.OPENED,
    "email_clicked": CommunicationState.CLICKED,
    "email_replied": CommunicationState.REPLIED,
    "email_spam_complaint": CommunicationState.COMPLAINED,
    "email_suppressed": CommunicationState.SUPPRESSED,
    "unsubscribe_observed": CommunicationState.UNSUBSCRIBED,
    "message_sent_observed": CommunicationState.SENT,
    "message_received_observed": CommunicationState.RECEIVED,
    "message_replied_observed": CommunicationState.REPLIED,
    "notification_delivered": CommunicationState.DELIVERED,
    "notification_opened": CommunicationState.OPENED,
    "notification_clicked": CommunicationState.CLICKED,
}

# event type → default channel (may be overridden by payload.channel)
EVENT_CHANNEL_MAP: dict[str, str] = {
    **{t: "email" for t in EMAIL_LIFECYCLE_EVENTS},
    "notification_delivered": "push",
    "notification_opened": "push",
    "notification_clicked": "push",
    "message_sent_observed": "message",
    "message_received_observed": "message",
    "message_replied_observed": "message",
}

# event type → default direction
EVENT_DIRECTION_MAP: dict[str, Direction] = {
    **{t: Direction.OUTBOUND for t in EMAIL_LIFECYCLE_EVENTS},
    "email_replied": Direction.INBOUND,
    "message_sent_observed": Direction.OUTBOUND,
    "message_received_observed": Direction.INBOUND,
    "message_replied_observed": Direction.INBOUND,
    "notification_delivered": Direction.OUTBOUND,
    "notification_opened": Direction.OUTBOUND,
    "notification_clicked": Direction.OUTBOUND,
}

# Engagement interactions (recipient acted) vs delivery lifecycle states.
ENGAGEMENT_EVENTS: frozenset[str] = frozenset({
    "email_opened", "email_clicked", "email_replied",
    "message_replied_observed", "notification_opened", "notification_clicked",
})

NEGATIVE_OUTCOME_EVENTS: frozenset[str] = frozenset({
    "email_spam_complaint", "unsubscribe_observed",
})


# ── Journey-role policy (ADR-C5) ──────────────────────────────────────────────

_BASE_JOURNEY_ROLE: dict[str, JourneyRole] = {
    "email_queued": JourneyRole.STATE_ONLY,
    "email_processed": JourneyRole.STATE_ONLY,
    "email_sent": JourneyRole.CONTEXT,
    "email_delivered": JourneyRole.CONTEXT,
    "email_deferred": JourneyRole.STATE_ONLY,
    "email_bounced": JourneyRole.STATE_ONLY,
    "email_dropped": JourneyRole.STATE_ONLY,
    "email_opened": JourneyRole.CONTEXT,
    "email_clicked": JourneyRole.ACTIVE_STEP,
    "email_replied": JourneyRole.ACTIVE_STEP,
    "email_spam_complaint": JourneyRole.OUTCOME,
    "email_suppressed": JourneyRole.STATE_ONLY,
    "unsubscribe_observed": JourneyRole.OUTCOME,
    "message_sent_observed": JourneyRole.CONTEXT,
    "message_received_observed": JourneyRole.CONTEXT,
    "message_replied_observed": JourneyRole.ACTIVE_STEP,
    "notification_delivered": JourneyRole.CONTEXT,
    "notification_opened": JourneyRole.CONTEXT,
    "notification_clicked": JourneyRole.ACTIVE_STEP,
}


def journey_role_for(
    event_type: str,
    *,
    suspected_machine_activity: bool = False,
    is_automated_response: bool = False,
) -> JourneyRole:
    """Resolve the journey role for a communication event.

    Machine-generated engagement (scanner clicks, proxy opens) and automated
    replies (DSN, out-of-office, mail loops) are excluded from journeys
    regardless of the base role.
    """
    role = _BASE_JOURNEY_ROLE.get(event_type, JourneyRole.CONTEXT)
    if suspected_machine_activity and event_type in ENGAGEMENT_EVENTS:
        return JourneyRole.EXCLUDED
    if is_automated_response and event_type in ("email_replied", "message_replied_observed"):
        return JourneyRole.EXCLUDED
    return role


# ── Activity-family routing (ADR-C4 / Phase 6) ────────────────────────────────

_CATEGORY_FAMILY: dict[MessageCategory, str] = {
    MessageCategory.MARKETING: "campaign",
    MessageCategory.SALES: "campaign",
    MessageCategory.TRANSACTIONAL: "commerce",
    MessageCategory.SECURITY: "web2",
    MessageCategory.ACCOUNT: "web2",
    MessageCategory.SUPPORT: "web2",
    MessageCategory.OPERATIONAL: "web2",
    MessageCategory.AGENT_GENERATED: "agent",
}


def activity_family_for(
    category: MessageCategory | str | None,
    *,
    actor_kind: ActorKind | str | None = None,
) -> str:
    """Route a communication to a canonical activity family by business meaning.

    Agent participation (either side) routes to the agent family; otherwise
    the message category decides. Unknown categories default to web2 rather
    than inventing a new family.
    """
    if actor_kind in (ActorKind.AGENT, "agent"):
        return "agent"
    try:
        cat = MessageCategory(category) if category else None
    except ValueError:
        cat = None
    if cat is None:
        return "web2"
    return _CATEGORY_FAMILY[cat]


def actor_kind_from_provenance(
    *,
    direction: Direction | str | None,
    agent_id: Optional[str] = None,
    sender_is_organization: bool = False,
    category: MessageCategory | str | None = None,
) -> ActorKind:
    """Determine the acting party's kind from provenance, never by default.

    Outbound provider sends act on behalf of the sending organization (or an
    agent when agent_id is present). Inbound replies are human unless an
    agent is the correspondent.
    """
    if agent_id:
        return ActorKind.AGENT
    if category in (MessageCategory.AGENT_GENERATED, "agent_generated"):
        return ActorKind.AGENT
    if direction in (Direction.INBOUND, "inbound"):
        return ActorKind.HUMAN
    if sender_is_organization or direction in (Direction.OUTBOUND, "outbound",
                                               Direction.SYSTEM_GENERATED, "system_generated"):
        return ActorKind.ORGANIZATION
    return ActorKind.SYSTEM


# ── Consent purpose mapping (ADR-C7) ──────────────────────────────────────────

CATEGORY_CONSENT_PURPOSE: dict[MessageCategory, str] = {
    MessageCategory.MARKETING: "marketing",
    MessageCategory.SALES: "marketing",
    MessageCategory.TRANSACTIONAL: "commerce",
    MessageCategory.SECURITY: "analytics",
    MessageCategory.ACCOUNT: "analytics",
    MessageCategory.SUPPORT: "analytics",
    MessageCategory.OPERATIONAL: "analytics",
    MessageCategory.AGENT_GENERATED: "agent",
}


# ── Canonical payload ─────────────────────────────────────────────────────────

class CommunicationEventPayload(BaseModel):
    """Provider-neutral communication event payload (ADR-C2).

    Connectors normalize provider webhooks/pulls into this shape before the
    event enters Bronze. All fields except the identity of the event itself
    are optional — providers vary widely — but the more that is populated,
    the stronger resolution and attribution become.
    """

    # Identity
    tenant_id: str
    sender_entity_id: Optional[str] = None
    recipient_entity_id: Optional[str] = None
    recipient_alias_id: Optional[str] = None  # tenant-scoped hash, never raw
    profile_id: Optional[str] = None
    cluster_id: Optional[str] = None
    organization_id: Optional[str] = None
    agent_id: Optional[str] = None

    # Provider
    provider: str
    provider_account_id: Optional[str] = None
    provider_event_id: str
    source_connector_id: Optional[str] = None

    # Campaign
    campaign_id: Optional[str] = None  # canonical Aether UUID only
    external_campaign_id: Optional[str] = None
    external_flow_id: Optional[str] = None
    external_message_id: Optional[str] = None
    external_thread_id: Optional[str] = None
    external_template_id: Optional[str] = None
    sequence_step: Optional[int] = None
    variant_id: Optional[str] = None
    link_id: Optional[str] = None
    link_url_hash: Optional[str] = None
    audience_id: Optional[str] = None
    segment_id: Optional[str] = None

    # Classification
    channel: str = "email"
    direction: Direction = Direction.OUTBOUND
    message_category: MessageCategory = MessageCategory.MARKETING
    actor_kind: Optional[ActorKind] = None
    communication_state: Optional[CommunicationState] = None
    engagement_type: Optional[str] = None
    journey_role: Optional[JourneyRole] = None

    # Quality
    engagement_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    machine_activity_probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    suspected_machine_activity: bool = False
    identity_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    campaign_resolution_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Governance
    consent_snapshot_id: Optional[str] = None
    suppression_scope: Optional[SuppressionScope] = None
    unsubscribe_scope: Optional[SuppressionScope] = None
    privacy_class: str = "behavioral"
    retention_class: str = "standard_180d"

    # Timing
    occurred_at: str
    received_at: Optional[str] = None
    provider_sequence: Optional[int] = None
    provider_version: Optional[str] = None

    # Evidence
    source_event_id: Optional[str] = None
    raw_evidence_ref: Optional[str] = None
    evidence_ids: list[str] = Field(default_factory=list)
    idempotency_key: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    # Bounce/engagement detail
    bounce_type: Optional[str] = None  # hard | soft
    user_agent: Optional[str] = None
    ip_class: Optional[str] = None  # datacenter | residential | proxy | unknown
    is_automated_response: bool = False


# ── Canonical activity key (ADR-C4) ──────────────────────────────────────────

def canonical_activity_key(
    tenant_id: str,
    source_system: str,
    provider_account_id: Optional[str],
    provider_event_id: str,
    semantic_event_type: str,
) -> str:
    """Source-derived canonical activity key.

    One real-world event maps to exactly one canonical activity, regardless
    of how many Silver projections it produces or how many times it replays.
    """
    raw = ":".join([
        tenant_id, source_system, provider_account_id or "", provider_event_id,
        semantic_event_type,
    ])
    return hashlib.sha256(raw.encode()).hexdigest()
