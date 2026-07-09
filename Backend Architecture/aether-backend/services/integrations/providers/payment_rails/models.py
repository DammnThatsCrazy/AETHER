"""Payment Rail Observability — Pydantic mirrors of the canonical TS contracts.

Snake_case mirrors of ``packages/shared/payment-rails.ts``. Aether observes,
normalizes, reconciles, and displays how money enters, exits, settles, or
fails across providers. Aether does not execute or settle payments, custody
funds, or sign transactions.

Named providers only (no generic webhook fallback): Privy, Stripe crypto
onramp, Coinbase onramp/offramp, MoonPay buy/sell, Bridge virtual accounts.
Records never carry raw KYC documents, card numbers, bank/routing numbers,
or provider secrets; metadata is sanitized and explicitly PII-safe.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

PAYMENT_RAILS_SCHEMA_VERSION = "payment.rails.v1"

PaymentRailProvider = Literal["privy", "stripe", "coinbase", "moonpay", "bridge"]

PAYMENT_RAIL_PROVIDERS: tuple[str, ...] = ("privy", "stripe", "coinbase", "moonpay", "bridge")

FundingFlowType = Literal[
    "fiat_onramp",
    "crypto_onramp",
    "bank_deposit",
    "crypto_deposit",
    "offramp",
    "settlement",
    "refund",
]

FUNDING_FLOW_TYPES: tuple[str, ...] = (
    "fiat_onramp", "crypto_onramp", "bank_deposit", "crypto_deposit",
    "offramp", "settlement", "refund",
)

PaymentRail = Literal[
    "fiat", "stripe", "coinbase", "moonpay", "bridge", "bank_transfer",
    "card", "ach", "wire", "sepa", "onchain", "x402",
]

FundingSessionStatus = Literal[
    "initiated", "submitted", "pending", "completed",
    "failed", "refunded", "cancelled", "unresolved",
]

FUNDING_SESSION_STATUSES: tuple[str, ...] = (
    "initiated", "submitted", "pending", "completed",
    "failed", "refunded", "cancelled", "unresolved",
)

ReconciliationState = Literal[
    "sdk_only", "provider_only", "matched", "stale", "conflict", "ignored_duplicate",
]

RECONCILIATION_STATES: tuple[str, ...] = (
    "sdk_only", "provider_only", "matched", "stale", "conflict", "ignored_duplicate",
)

FundingActorKind = Literal["human", "agent", "org", "wallet", "service", "system"]

# Canonical status ordering rank. Non-final states ascend
# initiated < submitted < pending < unresolved; final states hold the highest
# ranks and NEVER regress on duplicate or out-of-order provider events.
# ``refunded`` outranks the other finals so a completed session can still
# advance to refunded (money returned after settlement).
CANONICAL_STATUS_ORDERING: dict[str, int] = {
    "initiated": 10,
    "submitted": 20,
    "pending": 30,
    "unresolved": 40,
    "completed": 100,
    "failed": 100,
    "cancelled": 100,
    "refunded": 110,
}

FINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "refunded", "cancelled"})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class FundingSession(BaseModel):
    """Canonical internal funding session — one normalized record per observed
    onramp/offramp/deposit/settlement/refund flow, tenant-scoped and idempotent
    on (tenant_id, idempotency_key)."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    provider: PaymentRailProvider
    # Underlying processor when the provider routes through another rail
    # (e.g. Privy → Stripe/MoonPay/Coinbase/Meld).
    provider_detail: Optional[str] = None
    flow_type: FundingFlowType
    rail: PaymentRail
    status: FundingSessionStatus = "initiated"
    # Provider-native status string the canonical status was mapped from.
    provider_status: Optional[str] = None
    # Failure/rejection reason metadata (e.g. AML, fraud, min-amount), sanitized.
    status_reason: Optional[str] = None
    reconciliation_state: ReconciliationState = "provider_only"

    actor_kind: FundingActorKind = "human"
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    org_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    journey_id: Optional[str] = None
    campaign_id: Optional[str] = None

    source_asset: Optional[str] = None
    source_chain: Optional[str] = None
    source_amount: Optional[str] = None
    fiat_currency: Optional[str] = None
    destination_asset: Optional[str] = None
    destination_chain: Optional[str] = None
    destination_amount: Optional[str] = None
    destination_address: Optional[str] = None

    # Fee total where safely reported by the provider.
    fee_amount: Optional[str] = None
    fee_currency: Optional[str] = None

    provider_session_id: Optional[str] = None
    provider_transaction_id: Optional[str] = None
    # Safe opaque customer reference only — never a PAN, account number, or
    # KYC identifier.
    provider_customer_ref: Optional[str] = None
    deposit_address_id: Optional[str] = None
    virtual_account_id: Optional[str] = None
    tx_hash: Optional[str] = None

    idempotency_key: str
    occurred_at: str = Field(default_factory=utc_now_iso)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    # Sanitized, explicitly PII-safe metadata.
    metadata: dict[str, Any] = Field(default_factory=dict)


class PaymentProviderAccount(BaseModel):
    """Tenant-scoped provider connection metadata. Secrets live in the key
    vault, never here."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    provider: PaymentRailProvider
    display_name: Optional[str] = None
    # Safe provider-side account/business identifier.
    provider_account_ref: Optional[str] = None
    environment: Literal["production", "sandbox"] = "production"
    status: Literal["configured", "not_configured", "error", "disabled"] = "not_configured"
    # Whether a webhook verification secret is configured (never the secret).
    webhook_configured: bool = False
    # Whether API polling credentials are configured (never the credentials).
    polling_configured: bool = False
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class DepositAddress(BaseModel):
    """Provider-issued crypto deposit address reference (Privy et al.)."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    provider: PaymentRailProvider
    provider_address_id: Optional[str] = None
    address: str
    chain: str
    asset: Optional[str] = None
    user_id: Optional[str] = None
    wallet_id: Optional[str] = None
    status: Literal["active", "inactive", "unknown"] = "active"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class VirtualAccount(BaseModel):
    """Provider-issued virtual bank account reference (Bridge et al.)."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    provider: PaymentRailProvider
    provider_virtual_account_id: str
    provider_customer_ref: Optional[str] = None
    # Masked/partial account reference safe for display (never full
    # account/routing numbers).
    masked_account_ref: Optional[str] = None
    currency: Optional[str] = None
    destination_address: Optional[str] = None
    destination_chain: Optional[str] = None
    status: Literal["active", "deactivated", "unknown"] = "active"
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class PaymentRailStatusMap(BaseModel):
    """Per-provider mapping from provider-native statuses to canonical
    FundingSessionStatus values, with ordering rank for non-regression."""

    provider: PaymentRailProvider
    # provider-native status → canonical status
    statuses: dict[str, FundingSessionStatus]
    # Canonical status → monotonic rank; final states hold the highest ranks.
    ordering: dict[str, int] = Field(default_factory=lambda: dict(CANONICAL_STATUS_ORDERING))
    version: str = PAYMENT_RAILS_SCHEMA_VERSION


class ReconciliationDiscrepancy(BaseModel):
    """Field-level mismatch between the SDK view and provider truth, sanitized."""

    field: str
    sdk_value: Optional[str] = None
    provider_value: Optional[str] = None


class ReconciliationRecord(BaseModel):
    """Result of reconciling a funding session against provider/SDK truth."""

    id: str = Field(default_factory=new_id)
    tenant_id: str
    funding_session_id: str
    provider: PaymentRailProvider
    state: ReconciliationState
    # Source that most recently advanced this record:
    # 'sdk' | 'webhook' | 'polling' | 'manual'.
    last_source: str = "webhook"
    sdk_event_id: Optional[str] = None
    provider_event_id: Optional[str] = None
    discrepancies: list[ReconciliationDiscrepancy] = Field(default_factory=list)
    first_observed_at: str = Field(default_factory=utc_now_iso)
    last_checked_at: str = Field(default_factory=utc_now_iso)
    resolved_at: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class PaymentRailHealth(BaseModel):
    """Aggregate per-provider health for Aether/Kyber surfaces."""

    tenant_id: Optional[str] = None
    provider: PaymentRailProvider
    configured: bool = False
    enabled: bool = False
    webhook_verified_24h: int = 0
    webhook_rejected_24h: int = 0
    sessions_observed_24h: int = 0
    sessions_completed_24h: int = 0
    sessions_failed_24h: int = 0
    sessions_unresolved: int = 0
    reconciliation_matched_rate: Optional[float] = None
    reconciliation_conflicts: int = 0
    last_event_at: Optional[str] = None
    last_poll_at: Optional[str] = None
    status: Literal["healthy", "degraded", "not_configured", "error"] = "not_configured"
    computed_at: str = Field(default_factory=utc_now_iso)
