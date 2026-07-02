"""Delivery infrastructure models — Pydantic v2.

Covers: DeliveryIntent, DeliveryJob, DeliveryAttempt, ProviderReceipt,
ExternalResourceLink, ExternalOutcomeEvent, WebhookInbox, ConnectorCursor.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ─── helpers ────────────────────────────────────────────────────────────────

def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_idempotency_key(*parts: str) -> str:
    """Deterministic idempotency key — SHA-256 of colon-joined parts."""
    raw = ":".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode()).hexdigest()


# ─── enums ──────────────────────────────────────────────────────────────────

class DeliveryChannel(str, Enum):
    SLACK = "slack"
    WEBHOOK = "webhook"
    LINEAR = "linear"
    JIRA = "jira"
    EMAIL = "email"
    CRM = "crm"
    MARKETING = "marketing"
    TICKETING = "ticketing"
    AGENT_ASSIST = "agent_assist"
    NOTIFICATION = "notification"


class DeliveryIntentStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryJobState(str, Enum):
    QUEUED = "queued"
    LEASED = "leased"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class DeliveryAttemptOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRYABLE = "retryable"


class ExternalOutcomeType(str, Enum):
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    FAILED = "failed"
    RESOLVED = "resolved"


class DeliveryJobPriority(int, Enum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3
    INFO = 9


# ─── DeliveryIntent ─────────────────────────────────────────────────────────

class DeliveryIntent(BaseModel):
    """Top-level intent to deliver a notification or suggestion to one or more channels."""

    id: str = Field(default_factory=_new_id)
    tenant_id: str
    source_type: str  # "suggestion" | "notification" | "action"
    source_id: str
    channels: list[str] = Field(default_factory=list)
    status: DeliveryIntentStatus = DeliveryIntentStatus.PENDING
    idempotency_key: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @model_validator(mode="after")
    def _set_idempotency_key(self) -> "DeliveryIntent":
        if not self.idempotency_key:
            self.idempotency_key = generate_idempotency_key(
                self.tenant_id, self.source_type, self.source_id
            )
        return self


# ─── DeliveryJob ────────────────────────────────────────────────────────────

class DeliveryJob(BaseModel):
    """Single-channel delivery unit spawned from a DeliveryIntent."""

    id: str = Field(default_factory=_new_id)
    intent_id: str
    tenant_id: str
    channel: DeliveryChannel
    provider_adapter: str  # e.g. "slack", "webhook", "linear"
    priority: DeliveryJobPriority = DeliveryJobPriority.P3
    state: DeliveryJobState = DeliveryJobState.QUEUED
    payload: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(default_factory=dict)
    attempt_count: int = 0
    max_attempts: int = 5
    next_attempt_at: str = Field(default_factory=_now_iso)
    leased_by: Optional[str] = None
    lease_expires_at: Optional[str] = None
    idempotency_key: str = ""
    last_error: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)

    @model_validator(mode="after")
    def _set_idempotency_key(self) -> "DeliveryJob":
        if not self.idempotency_key:
            self.idempotency_key = generate_idempotency_key(
                self.intent_id, self.channel.value, str(self.priority.value)
            )
        return self


# ─── DeliveryAttempt ────────────────────────────────────────────────────────

class DeliveryAttempt(BaseModel):
    """Record of a single dispatch attempt for a DeliveryJob."""

    id: str = Field(default_factory=_new_id)
    job_id: str
    intent_id: str
    tenant_id: str
    attempt_number: int
    outcome: DeliveryAttemptOutcome
    provider_adapter: str
    http_status: Optional[int] = None
    error_message: Optional[str] = None
    external_id: Optional[str] = None  # provider-assigned ID if success
    duration_ms: Optional[int] = None
    raw_response: Optional[dict[str, Any]] = None
    created_at: str = Field(default_factory=_now_iso)


# ─── ProviderReceipt ────────────────────────────────────────────────────────

class ProviderReceipt(BaseModel):
    """Proof of delivery from the provider — must carry a real external_id."""

    id: str = Field(default_factory=_new_id)
    job_id: str
    intent_id: str
    tenant_id: str
    provider_adapter: str
    external_id: str  # provider-assigned; must not be empty or sim-prefixed
    channel: DeliveryChannel
    delivered_at: str = Field(default_factory=_now_iso)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)

    @field_validator("external_id")
    @classmethod
    def _reject_simulated_ids(cls, v: str) -> str:
        if not v:
            raise ValueError("ProviderReceipt.external_id must not be empty")
        if v.startswith("sim-"):
            raise ValueError(
                f"ProviderReceipt.external_id {v!r} starts with 'sim-' — "
                "simulated IDs are not accepted as proof of delivery. "
                "Use a real provider external_id."
            )
        return v


# ─── ExternalResourceLink ───────────────────────────────────────────────────

class ExternalResourceLink(BaseModel):
    """Links a delivered item to its external system URL (e.g., Jira issue, Linear ticket)."""

    id: str = Field(default_factory=_new_id)
    tenant_id: str
    intent_id: str
    receipt_id: str
    provider: str
    external_id: str
    external_url: Optional[str] = None
    resource_type: str = ""  # "issue", "ticket", "message", etc.
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)


# ─── ExternalOutcomeEvent ───────────────────────────────────────────────────

class ExternalOutcomeEvent(BaseModel):
    """Inbound outcome event from an external provider (webhook callback)."""

    id: str = Field(default_factory=_new_id)
    tenant_id: str
    provider: str
    external_id: str  # matches ProviderReceipt.external_id
    intent_id: Optional[str] = None
    receipt_id: Optional[str] = None
    outcome_type: ExternalOutcomeType
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: str = Field(default_factory=_now_iso)
    ingested_at: str = Field(default_factory=_now_iso)


# ─── WebhookInbox ───────────────────────────────────────────────────────────

class WebhookInbox(BaseModel):
    """Raw inbound webhook payload before processing."""

    id: str = Field(default_factory=_new_id)
    tenant_id: str
    provider: str
    headers: dict[str, str] = Field(default_factory=dict)
    raw_body: str = ""  # base64-encoded bytes
    signature: Optional[str] = None
    timestamp: Optional[str] = None
    verified: bool = False
    processed: bool = False
    processing_error: Optional[str] = None
    received_at: str = Field(default_factory=_now_iso)
    created_at: str = Field(default_factory=_now_iso)


# ─── ConnectorCursor ────────────────────────────────────────────────────────

class ConnectorCursor(BaseModel):
    """Tracks the last-synced position for a connector pull."""

    id: str = Field(default_factory=_new_id)
    tenant_id: str
    connector_type: str
    cursor_value: Optional[str] = None  # ISO timestamp or opaque token
    last_synced_at: Optional[str] = None
    last_event_count: int = 0
    updated_at: str = Field(default_factory=_now_iso)

    @model_validator(mode="after")
    def _set_id(self) -> "ConnectorCursor":
        # Stable ID from tenant+connector so upsert is deterministic
        if not self.id or self.id == "":
            self.id = generate_idempotency_key(self.tenant_id, self.connector_type)
        return self
