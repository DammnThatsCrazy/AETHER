"""Pydantic request/response schemas for identity resolution API endpoints."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Resolve ───────────────────────────────────────────────────────────────────

class IdentityResolveRequest(BaseModel):
    """Direct identity resolution request (not via /v1/batch)."""
    event_id: str = Field(..., min_length=1)
    tenant_id: Optional[str] = None        # overridden from auth middleware
    user_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    session_id: Optional[str] = None
    email: Optional[str] = None            # normalized + hashed by resolver
    phone: Optional[str] = None            # normalized + hashed by resolver
    wallet_address: Optional[str] = None
    wallet_signature_verified: bool = False
    external_id: Optional[str] = None
    agent_id: Optional[str] = None
    org_id: Optional[str] = None
    campaign_id: Optional[str] = None
    journey_id: Optional[str] = None
    consent_snapshot: Optional[dict[str, Any]] = None
    properties: Optional[dict[str, Any]] = Field(default_factory=dict)
    context: Optional[dict[str, Any]] = Field(default_factory=dict)


class IdentityResolveResponse(BaseModel):
    tenant_id: str
    canonical_entity_id: str
    decision: str
    confidence: float
    confidence_tier: str
    reason_codes: list[str]
    linked_aliases: list[str] = Field(default_factory=list)
    candidate_entity_ids: list[str] = Field(default_factory=list)
    conflict_id: Optional[str] = None
    source_event_ids: list[str] = Field(default_factory=list)
    graph_edges_written: list[str] = Field(default_factory=list)
    blocked_reason: Optional[str] = None
    audit_id: Optional[str] = None
    is_new_entity: bool = False


# ── Entity ────────────────────────────────────────────────────────────────────

class IdentityEntityResponse(BaseModel):
    id: str
    tenant_id: str
    canonical_entity_id: str
    entity_type: str
    status: str
    first_seen_at: str
    last_seen_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentityAliasResponse(BaseModel):
    id: str
    tenant_id: str
    canonical_entity_id: str
    alias_type: str
    alias_display_value_redacted: str      # raw value NEVER returned
    source: str
    confidence: float
    confidence_tier: str
    first_seen_at: str
    last_seen_at: str
    revoked_at: Optional[str] = None


class IdentityGraphResponse(BaseModel):
    canonical_entity_id: str
    tenant_id: str
    edges: list[dict[str, Any]] = Field(default_factory=list)


class IdentityAuditResponse(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


# ── Conflict ──────────────────────────────────────────────────────────────────

class IdentityConflictResponse(BaseModel):
    id: str
    tenant_id: str
    candidate_entity_ids: list[str]
    conflict_type: str
    confidence: float
    reason_codes: list[str]
    status: str
    created_at: str
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None


# ── Merge / Split ─────────────────────────────────────────────────────────────

class IdentityMergeRequest(BaseModel):
    primary_entity_id: str = Field(..., min_length=1)
    secondary_entity_id: str = Field(..., min_length=1)
    reason: str = "manual_merge"


class IdentityMergeResponse(BaseModel):
    canonical_entity_id: str
    decision: str
    confidence: float
    confidence_tier: str
    reason_codes: list[str]
    audit_id: Optional[str] = None
    graph_edges_written: list[str] = Field(default_factory=list)


class IdentitySplitRequest(BaseModel):
    original_entity_id: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    source_merge_event_id: Optional[str] = None


class IdentitySplitResponse(BaseModel):
    allowed: bool
    split_event_id: Optional[str] = None
    original_entity_id: Optional[str] = None
    new_entity_id: Optional[str] = None
    revoked_edge_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    error: Optional[str] = None


# ── Recompute ─────────────────────────────────────────────────────────────────

class IdentityRecomputeRequest(BaseModel):
    entity_id: Optional[str] = None
    event_ids: Optional[list[str]] = None
    reason: str = "recompute"


class IdentityRecomputeResponse(BaseModel):
    status: str
    tenant_id: str
    entity_id: Optional[str] = None
    event_ids: list[str] = Field(default_factory=list)
    reason: str
    events_replayed: int = 0
    decisions: list[dict] = Field(default_factory=list)
    errors: int = 0
    note: Optional[str] = None


# ── Suppression ───────────────────────────────────────────────────────────────

_VALID_SIGNAL_TYPES: frozenset[str] = frozenset({
    "user_id", "anonymous_id", "session_id",
    "email_hash", "phone_hash",
    "wallet_address", "wallet",
    "external_id", "customer_id",
    "device_id", "install_id", "browser_id",
    "fingerprint_id", "ip_hash",
    "oauth_subject", "siwx_session",
})


class IdentitySuppressRequest(BaseModel):
    identifier_type: str = Field(..., min_length=1)
    identifier_hash: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    subject_id: Optional[str] = None
    expires_at: Optional[str] = None

    @field_validator("identifier_type")
    @classmethod
    def validate_identifier_type(cls, v: str) -> str:
        if v not in _VALID_SIGNAL_TYPES:
            raise ValueError(
                f"identifier_type must be one of: {', '.join(sorted(_VALID_SIGNAL_TYPES))}"
            )
        return v


class IdentitySuppressResponse(BaseModel):
    suppression_id: str
    tenant_id: str
    identifier_type: str
    reason: str
    revoked_alias_ids: list[str] = Field(default_factory=list)
    created_at: str = ""
    expires_at: Optional[str] = None


class IdentityUnsuppressResponse(BaseModel):
    revoked: bool = False
    suppression_id: str
    revoked_by: str = ""
    error: Optional[str] = None


# ── Health ────────────────────────────────────────────────────────────────────

class IdentityHealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"] = "healthy"
    resolver_enabled: bool = True
    total_entities: int = 0
    total_aliases: int = 0
    total_clusters: int = 0
    open_conflicts: int = 0
    recent_merges: int = 0
    recent_splits: int = 0
    blocked_consent: int = 0
    blocked_cross_tenant: int = 0
    blocked_fingerprint_only: int = 0
    resolver_error_rate: float = 0.0
    graph_write_error_rate: float = 0.0
    tenant_id: Optional[str] = None
