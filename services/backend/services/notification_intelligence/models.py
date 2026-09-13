"""Notification Intelligence — Data Models"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NotificationLifecycleState(str, Enum):
    DETECTED        = "detected"
    VALIDATED       = "validated"
    QUEUED          = "queued"
    OPERATOR_REVIEW = "operator_review"
    APPROVED        = "approved"
    PROPAGATED      = "propagated"
    SUPPRESSED      = "suppressed"
    EXPIRED         = "expired"


# Valid forward-only transitions
LIFECYCLE_TRANSITIONS: dict[NotificationLifecycleState, list[NotificationLifecycleState]] = {
    NotificationLifecycleState.DETECTED:        [NotificationLifecycleState.VALIDATED, NotificationLifecycleState.SUPPRESSED],
    NotificationLifecycleState.VALIDATED:       [NotificationLifecycleState.QUEUED, NotificationLifecycleState.SUPPRESSED],
    NotificationLifecycleState.QUEUED:          [NotificationLifecycleState.OPERATOR_REVIEW, NotificationLifecycleState.PROPAGATED, NotificationLifecycleState.SUPPRESSED],
    NotificationLifecycleState.OPERATOR_REVIEW: [NotificationLifecycleState.APPROVED, NotificationLifecycleState.SUPPRESSED, NotificationLifecycleState.EXPIRED],
    NotificationLifecycleState.APPROVED:        [NotificationLifecycleState.PROPAGATED],
    NotificationLifecycleState.PROPAGATED:      [],
    NotificationLifecycleState.SUPPRESSED:      [],
    NotificationLifecycleState.EXPIRED:         [NotificationLifecycleState.SUPPRESSED],
}


class OperatorActionType(str, Enum):
    APPROVE   = "approve"
    SUPPRESS  = "suppress"
    ESCALATE  = "escalate"
    ANNOTATE  = "annotate"


class NotificationSeverity(str, Enum):
    P0   = "P0"
    P1   = "P1"
    P2   = "P2"
    P3   = "P3"
    INFO = "info"


class NotificationClass(str, Enum):
    ALERT          = "alert"
    ACTION_REQUEST = "action-request"
    OPERATIONAL    = "operational"
    DIGEST         = "digest"


class ChannelType(str, Enum):
    SLACK   = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"


# ─────────────────────────────────────────────────────────────────────────────
# Core notification event
# ─────────────────────────────────────────────────────────────────────────────

class IntelligenceNotificationEvent(BaseModel):
    # Identity
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    deduplication_key: str
    idempotency_key: str

    # Source provenance
    source_topic: str
    source_event_id: str
    source_service: str = ""
    correlation_id: str = ""

    # Classification
    lifecycle_state: NotificationLifecycleState = NotificationLifecycleState.DETECTED
    severity: NotificationSeverity
    notification_class: NotificationClass

    # Human-readable content
    title: str
    body: str
    what: str
    why: str
    impact: str
    recommended_action: Optional[str] = None
    reversible: Optional[bool] = None
    deep_link: str = "/mission"

    # Routing / delivery
    routing_policy: dict[str, Any] = Field(default_factory=dict)
    slack_payload: Optional[dict[str, Any]] = None

    # Redacted mobile push projection (M1a, decision-log D11). These snake_case
    # fields are the ONLY content a push may carry; they are populated when the
    # notification is created/read for push (see projection.build_projection) or
    # computed at the push boundary. They never store raw payload or PII.
    push_title: Optional[str] = None
    push_body: Optional[str] = None
    push_summary: Optional[str] = None
    push_deep_link_class: Optional[str] = None
    push_category: Optional[str] = None

    # Operator context
    operator_context: dict[str, Any] = Field(default_factory=dict)

    # Graph propagation
    graph_propagation: Optional[dict[str, Any]] = None

    # Audit trail (append-only)
    audit_trail: list[dict[str, Any]] = Field(default_factory=list)

    # Timestamps
    detected_at: str = Field(default_factory=_utc_now)
    expires_at: Optional[str] = None

    def attach_projection(self) -> "IntelligenceNotificationEvent":
        """Populate the redacted push-projection fields from this record.

        Lazy import avoids a module-level dependency on the projection service.
        The projection is derived/redacted and safe to persist alongside the
        canonical record (never raw payload / PII).
        """
        from services.notification_intelligence.projection import build_projection

        proj = build_projection(
            title=self.title,
            body=self.body,
            what=self.what,
            category=self.notification_class.value
            if hasattr(self.notification_class, "value")
            else None,
            notification_class=self.notification_class.value
            if hasattr(self.notification_class, "value")
            else None,
            severity=self.severity.value if hasattr(self.severity, "value") else None,
            deep_link=self.deep_link,
        )
        self.push_title = proj.push_title
        self.push_body = proj.push_body
        self.push_summary = proj.push_summary
        self.push_deep_link_class = proj.push_deep_link_class
        self.push_category = proj.push_category
        return self


def make_dedup_key(source_topic: str, source_event_id: str, tenant_id: str) -> str:
    raw = f"{source_topic}:{source_event_id}:{tenant_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Operator action
# ─────────────────────────────────────────────────────────────────────────────

class OperatorAction(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    notification_id: str
    tenant_id: str
    action_type: OperatorActionType
    actor_user_id: str
    annotation: Optional[str] = None
    propagate_to_graph: bool = True
    timestamp: str = Field(default_factory=_utc_now)


# ─────────────────────────────────────────────────────────────────────────────
# Tenant notification config
# ─────────────────────────────────────────────────────────────────────────────

class TenantNotificationConfig(BaseModel):
    tenant_id: str
    slack_bot_token_ref: Optional[str] = None
    slack_channel_map: dict[str, str] = Field(default_factory=dict)
    rate_limit_per_minute: int = 10
    quiet_hours: Optional[dict[str, str]] = None
    # M3c: notification delivery preferences (preferences persistence on the
    # existing /v1/notifications/config surface — no second preferences system).
    timezone: Optional[str] = None
    digest: Optional[dict[str, Any]] = None
    operator_review_required: list[str] = Field(default_factory=lambda: ["P0", "P1"])
    auto_propagate_on_approve: bool = True
    auto_suppress_on_expire: bool = True
    sla_minutes: dict[str, int] = Field(
        default_factory=lambda: {"P0": 5, "P1": 15, "P2": 60, "P3": 240, "info": 1440}
    )
    rbac_approve_roles: list[str] = Field(
        default_factory=lambda: ["kyber_executive_operator", "kyber_engineering_command"]
    )
    rbac_suppress_roles: list[str] = Field(
        default_factory=lambda: ["kyber_executive_operator", "kyber_engineering_command"]
    )
    rbac_escalate_roles: list[str] = Field(
        default_factory=lambda: [
            "kyber_specialist_operator",
            "kyber_executive_operator",
            "kyber_engineering_command",
        ]
    )

    def slack_channel_for(self, severity: str) -> str:
        return self.slack_channel_map.get(severity) or self.slack_channel_map.get("default", "#aether-ops")

    def sla_for(self, severity: str) -> int:
        return self.sla_minutes.get(severity, 1440)


# ─────────────────────────────────────────────────────────────────────────────
# End-user notification channel
# ─────────────────────────────────────────────────────────────────────────────

class UserNotificationChannel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str
    user_id: Optional[str] = None
    channel_type: ChannelType
    channel_name: Optional[str] = None
    credentials_ref: str
    channel_config: dict[str, Any] = Field(default_factory=dict)
    severity_filter: list[str] = Field(default_factory=lambda: ["P0", "P1", "P2"])
    event_type_filter: Optional[list[str]] = None
    active: bool = True
    verified_at: Optional[str] = None
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


class RegisterChannelRequest(BaseModel):
    channel_type: ChannelType
    channel_name: Optional[str] = None
    channel_config: dict[str, Any] = Field(default_factory=dict)
    severity_filter: list[str] = Field(default_factory=lambda: ["P0", "P1", "P2"])
    event_type_filter: Optional[list[str]] = None


class UpdateChannelRequest(BaseModel):
    channel_name: Optional[str] = None
    severity_filter: Optional[list[str]] = None
    event_type_filter: Optional[list[str]] = None
    active: Optional[bool] = None


# ─────────────────────────────────────────────────────────────────────────────
# Delivery result
# ─────────────────────────────────────────────────────────────────────────────

class DeliveryResult(BaseModel):
    channel_id: Optional[str] = None
    channel_type: str
    success: bool
    message_ref: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Webhook payload schema (versioned outbound contract)
# ─────────────────────────────────────────────────────────────────────────────

class NotificationWebhookPayload(BaseModel):
    schema_version: str = "1.0"
    notification_id: str
    tenant_id: str
    severity: str
    notification_class: str = Field(alias="class")
    title: str
    what: str
    why: str
    impact: str
    recommended_action: Optional[str] = None
    lifecycle_state: str
    source_topic: str
    deep_link: str
    detected_at: str
    correlation_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ─────────────────────────────────────────────────────────────────────────────
# API request/response helpers
# ─────────────────────────────────────────────────────────────────────────────

class EmitNotificationRequest(BaseModel):
    tenant_id: str
    source_topic: str
    source_event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_service: str = ""
    correlation_id: str = ""
    severity: NotificationSeverity
    notification_class: NotificationClass
    title: str
    body: str
    what: str
    why: str
    impact: str
    recommended_action: Optional[str] = None
    reversible: Optional[bool] = None
    deep_link: str = "/mission"
    operator_context: dict[str, Any] = Field(default_factory=dict)
    graph_propagation: Optional[dict[str, Any]] = None


class AnnotateRequest(BaseModel):
    annotation: str


class UpdateConfigRequest(BaseModel):
    slack_bot_token: Optional[str] = None
    slack_channel_map: Optional[dict[str, str]] = None
    rate_limit_per_minute: Optional[int] = None
    quiet_hours: Optional[dict[str, str]] = None
    # M3c: notification delivery preferences — persisted on the existing
    # /v1/notifications/config model (timezone + digest alongside quiet_hours).
    timezone: Optional[str] = None
    digest: Optional[dict[str, Any]] = None
    operator_review_required: Optional[list[str]] = None
    auto_propagate_on_approve: Optional[bool] = None
    auto_suppress_on_expire: Optional[bool] = None
    sla_minutes: Optional[dict[str, int]] = None
    rbac_approve_roles: Optional[list[str]] = None
    rbac_suppress_roles: Optional[list[str]] = None
    rbac_escalate_roles: Optional[list[str]] = None
