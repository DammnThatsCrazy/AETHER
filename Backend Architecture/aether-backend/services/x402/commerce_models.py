"""
Aether Service — Agentic Commerce Canonical Domain Models
Shared across control plane, approvals, verification, settlement, entitlements,
policy engine, resources, facilitators, and treasury. Wire-level schemas for
events, graph mutations, and Kyber adapters.

All models are Pydantic v2 compatible and tenant-isolated via tenant_id field.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# ─── Enums ────────────────────────────────────────────────────────────

class ResourceClass(str, Enum):
    API = "api"
    AGENT_TOOL = "agent_tool"
    PRICED_ENDPOINT = "priced_endpoint"
    SERVICE_PLAN = "service_plan"
    INTERNAL_CAPABILITY = "internal_capability"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ApprovalPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class SettlementState(str, Enum):
    PENDING = "pending"
    VERIFYING = "verifying"
    SETTLED = "settled"
    FAILED = "failed"
    DISPUTED = "disputed"


class EntitlementStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    REDUCE_SCOPE = "reduce_scope"


class FacilitatorMode(str, Enum):
    FACILITATOR = "facilitator"
    LOCAL = "local"
    HYBRID = "hybrid"


class AssetChain(str, Enum):
    BASE = "eip155:8453"
    SOLANA = "solana:mainnet"


# ─── Protected Resource ───────────────────────────────────────────────

class ProtectedResource(BaseModel):
    """A resource that requires payment to access."""
    resource_id: str = Field(default_factory=lambda: _new_id("res"))
    tenant_id: str = ""
    name: str
    resource_class: ResourceClass
    path_pattern: str = ""  # URL pattern for API resources
    owner_service: str = ""
    description: str = ""
    price_usd: float
    accepted_assets: list[str] = Field(default_factory=list)  # symbols
    accepted_chains: list[str] = Field(default_factory=list)  # CAIP-2
    approval_required: bool = True  # Day-1 GA: always true
    entitlement_ttl_seconds: int = 900  # default 15m
    active: bool = True
    registered_at: str = Field(default_factory=_now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ─── Stablecoin Asset ─────────────────────────────────────────────────

class StablecoinAsset(BaseModel):
    """A supported stablecoin asset on a specific network."""
    asset_id: str = Field(default_factory=lambda: _new_id("ast"))
    symbol: str
    chain: str  # CAIP-2
    network: str
    issuer: str
    contract_address: str
    decimals: int = 6
    settlement_scheme: str = "facilitator"  # on-chain|facilitator|hybrid
    facilitator_ids: list[str] = Field(default_factory=list)
    active: bool = True
    risk_score: float = 0.0
    registered_at: str = Field(default_factory=_now_iso)


# ─── Facilitator ──────────────────────────────────────────────────────

class Facilitator(BaseModel):
    """A payment facilitator that verifies and/or settles payments."""
    facilitator_id: str = Field(default_factory=lambda: _new_id("fac"))
    name: str
    endpoint_url: str = ""
    mode: FacilitatorMode = FacilitatorMode.HYBRID
    supported_assets: list[str] = Field(default_factory=list)
    supported_chains: list[str] = Field(default_factory=list)
    approved_by_tenants: list[str] = Field(default_factory=list)
    health_status: str = "healthy"  # healthy|degraded|down
    avg_latency_ms: float = 0.0
    success_rate: float = 1.0
    active: bool = True
    registered_at: str = Field(default_factory=_now_iso)


# ─── Payment Requirement (Challenge) ──────────────────────────────────

class PaymentRequirement(BaseModel):
    """A payment requirement issued in response to an unauthenticated request
    for a protected resource. Wire-format for PAYMENT-REQUIRED HTTP header."""
    challenge_id: str = Field(default_factory=lambda: _new_id("chg"))
    tenant_id: str
    resource_id: str
    amount_usd: float
    asset_symbol: str = "USDC"
    chain: str
    recipient: str
    protocol_version: str = "v2"
    memo: Optional[str] = None
    expires_at: str
    payment_identifier: str = Field(default_factory=lambda: _new_id("pid"))
    requester_id: str  # agent or user
    requester_type: str = "agent"  # agent|user|service
    siwx_nonce: Optional[str] = None
    issued_at: str = Field(default_factory=_now_iso)


# ─── Policy ───────────────────────────────────────────────────────────

class PricePolicy(BaseModel):
    policy_id: str = Field(default_factory=lambda: _new_id("pp"))
    tenant_id: str
    resource_id: str
    base_price_usd: float
    tenant_multiplier: float = 1.0
    plan_discounts: dict[str, float] = Field(default_factory=dict)
    active: bool = True


class BudgetPolicy(BaseModel):
    policy_id: str = Field(default_factory=lambda: _new_id("bp"))
    tenant_id: str
    subject_id: str  # agent_id or user_id
    subject_type: str = "agent"
    daily_cap_usd: float = 100.0
    monthly_cap_usd: float = 1000.0
    per_transaction_cap_usd: float = 50.0
    allowed_resource_classes: list[ResourceClass] = Field(default_factory=list)
    active: bool = True


class PolicyDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: _new_id("pd"))
    tenant_id: str
    challenge_id: str
    outcome: PolicyOutcome
    active_rules: list[str] = Field(default_factory=list)
    denial_reason: Optional[str] = None
    requires_approval: bool = True  # Day-1 default
    rationale: str = ""
    decided_at: str = Field(default_factory=_now_iso)


# ─── Approval ─────────────────────────────────────────────────────────

class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: _new_id("apr"))
    tenant_id: str
    challenge_id: str
    resource_id: str
    requester_id: str
    requester_type: str = "agent"
    amount_usd: float
    asset_symbol: str
    chain: str
    facilitator_id: Optional[str] = None
    priority: ApprovalPriority = ApprovalPriority.NORMAL
    reason: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    policy_decision_id: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    assigned_to: Optional[str] = None
    escalation_chain: list[str] = Field(default_factory=list)
    evidence_bundle_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    expires_at: str = ""
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None
    is_override: bool = False


class ApprovalDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: _new_id("apd"))
    approval_id: str
    tenant_id: str
    action: str  # approve|reject|escalate|revoke
    decided_by: str
    reason: str
    is_override: bool = False
    decided_at: str = Field(default_factory=_now_iso)


# ─── Payment Authorization ────────────────────────────────────────────

class PaymentAuthorization(BaseModel):
    authorization_id: str = Field(default_factory=lambda: _new_id("auth"))
    tenant_id: str
    challenge_id: str
    approval_id: str
    payment_identifier: str
    amount_usd: float
    asset_symbol: str
    chain: str
    recipient: str
    payer: str  # wallet address
    facilitator_id: str
    authorized_at: str = Field(default_factory=_now_iso)


# ─── Verification / Payment Receipt ───────────────────────────────────

class PaymentReceipt(BaseModel):
    receipt_id: str = Field(default_factory=lambda: _new_id("rcpt"))
    tenant_id: str
    authorization_id: str
    challenge_id: str
    tx_hash: str
    chain: str
    asset_symbol: str
    amount_usd: float
    payer: str
    recipient: str
    verified: bool = False
    verified_by: str = ""  # facilitator_id or "local"
    verified_at: Optional[str] = None
    verification_error: Optional[str] = None


# ─── Settlement ───────────────────────────────────────────────────────

class Settlement(BaseModel):
    settlement_id: str = Field(default_factory=lambda: _new_id("set"))
    tenant_id: str
    receipt_id: str
    challenge_id: str
    state: SettlementState = SettlementState.PENDING
    tx_hash: str
    chain: str
    amount_usd: float
    facilitator_id: str
    attempts: int = 0
    max_attempts: int = 5
    next_retry_at: Optional[str] = None
    settled_at: Optional[str] = None
    failure_reason: Optional[str] = None
    retried_from: Optional[str] = None  # prior settlement_id
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


# ─── Entitlement / Access Grant ───────────────────────────────────────

class Entitlement(BaseModel):
    entitlement_id: str = Field(default_factory=lambda: _new_id("ent"))
    tenant_id: str
    holder_id: str  # agent_id or user_id
    holder_type: str = "agent"
    resource_id: str
    scope: str = "read"
    status: EntitlementStatus = EntitlementStatus.ACTIVE
    settlement_id: str
    issued_at: str = Field(default_factory=_now_iso)
    expires_at: str
    reuse_count: int = 0
    last_reused_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revoke_reason: Optional[str] = None
    siwx_binding: Optional[str] = None


class AccessGrant(BaseModel):
    grant_id: str = Field(default_factory=lambda: _new_id("grt"))
    tenant_id: str
    entitlement_id: str
    resource_id: str
    holder_id: str
    granted_at: str = Field(default_factory=_now_iso)
    request_url: str = ""
    request_method: str = "GET"


# ─── Fulfillment ──────────────────────────────────────────────────────

class Fulfillment(BaseModel):
    fulfillment_id: str = Field(default_factory=lambda: _new_id("ful"))
    tenant_id: str
    grant_id: str
    resource_id: str
    status: str = "completed"
    latency_ms: int = 0
    status_code: int = 200
    completed_at: str = Field(default_factory=_now_iso)


# ─── Treasury / Service Plan ──────────────────────────────────────────

class Treasury(BaseModel):
    treasury_id: str = Field(default_factory=lambda: _new_id("tsy"))
    tenant_id: str
    balance_usd: float = 0.0
    preferred_chains: list[str] = Field(default_factory=list)
    preferred_assets: list[str] = Field(default_factory=list)
    auto_reload: bool = False
    updated_at: str = Field(default_factory=_now_iso)


class ServicePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: _new_id("pln"))
    tenant_id: str
    name: str
    price_usd: float
    asset_symbol: str = "USDC"
    chain: str = "eip155:8453"
    included_resources: list[str] = Field(default_factory=list)
    billing_period: str = "monthly"
    active: bool = True


# ─── Explainability / Diagnostics ─────────────────────────────────────

class LifecycleTrace(BaseModel):
    """Full lifecycle trace for one challenge. Returned by explain endpoint."""
    challenge_id: str
    tenant_id: str
    requirement: Optional[PaymentRequirement] = None
    policy_decision: Optional[PolicyDecision] = None
    approval: Optional[ApprovalRequest] = None
    authorization: Optional[PaymentAuthorization] = None
    receipt: Optional[PaymentReceipt] = None
    settlement: Optional[Settlement] = None
    entitlement: Optional[Entitlement] = None
    grant: Optional[AccessGrant] = None
    fulfillment: Optional[Fulfillment] = None
    graph_writes: list[dict[str, Any]] = Field(default_factory=list)
    events_emitted: list[str] = Field(default_factory=list)


class PreflightResult(BaseModel):
    """SDK preflight check: can agent access resource?"""
    can_access: bool
    reason: str
    resource_id: str
    holder_id: str
    existing_entitlement_id: Optional[str] = None
    price_quote_usd: Optional[float] = None
    accepted_assets: list[str] = Field(default_factory=list)
    accepted_chains: list[str] = Field(default_factory=list)
    approval_required: bool = True
    challenge_url: Optional[str] = None
