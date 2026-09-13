"""Stablecoin Intelligence — Pydantic v2 mirrors of packages/shared/stablecoin.ts.

Canonical bounded-domain contracts for read-only stablecoin economic
observation. Field names are snake_case exactly as in the TypeScript
contract; enums are Literal unions matching the runtime arrays in
stablecoin.ts; every canonical amount is a Decimal guarded by a
float-rejecting validator (repositories.typed_repo.as_decimal).

Aether observes and verifies — it never executes, custodies, mints,
redeems, or routes funds: ``execution_by_aether`` is Literal[False].
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from repositories.typed_repo import as_decimal

# ── Enum literals (mirror stablecoin.ts runtime arrays) ─────────────────────

StablecoinEvidenceClass = Literal["fact", "computation", "inference", "insufficient_evidence"]

StablecoinObservationType = Literal[
    "transfer", "payment", "mint", "burn", "bridge_outbound", "bridge_inbound", "swap",
    "x402_settlement", "treasury_movement", "payout", "venue_deposit", "venue_withdrawal",
    "unknown",
]

# Ingestable types: 'unknown' is a storage classification, never a legal
# ingest observation_type — routes reject it with 422 via this Literal.
IngestObservationType = Literal[
    "transfer", "payment", "mint", "burn", "bridge_outbound", "bridge_inbound", "swap",
    "x402_settlement", "treasury_movement", "payout", "venue_deposit", "venue_withdrawal",
]

PegStatus = Literal["on_peg", "minor_deviation", "depegged", "recovering", "unknown"]

StablecoinFinalityStatus = Literal[
    "provisional", "confirmed", "finalized", "reorged", "corrected", "unknown",
]

SupportAssertionStatus = Literal[
    "announced", "configured", "observed", "production_active",
    "degraded", "suspended", "retired", "unknown",
]

StablecoinCapability = Literal[
    "send", "receive", "hold", "deposit", "withdraw", "accept_payment", "settle", "refund",
    "swap", "bridge", "mint", "redeem", "collateral", "rewards", "x402", "treasury", "unknown",
]

StablecoinBackingModel = Literal[
    "fiat_reserve", "crypto_collateralized", "algorithmic", "commodity_backed", "hybrid",
    "unknown",
]

StablecoinDeploymentType = Literal[
    "canonical", "bridged", "wrapped", "synthetic", "deprecated", "counterfeit_suspected",
    "unknown",
]

StablecoinReconciliationStatus = Literal[
    "matched", "partial", "mismatched", "duplicate", "missing_onchain",
    "missing_tenant_event", "pending_finality", "reverted", "unresolved", "unknown",
]

StablecoinAssetStatus = Literal["active", "deprecated", "suspended", "unknown"]
StablecoinEnvironment = Literal["production", "sandbox", "testnet", "unknown"]
StablecoinFlowDirection = Literal["inflow", "outflow", "net", "internal"]


# ── Validator helpers ────────────────────────────────────────────────────────

def _decimal_or_error(value: Any) -> Decimal:
    """Coerce to Decimal via as_decimal; floats are rejected outright."""
    try:
        return as_decimal(value)
    except TypeError as exc:
        raise ValueError(str(exc)) from exc


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return _decimal_or_error(value)


def _block_int(value: Any) -> Optional[int]:
    """Block numbers are exact integers — floats and bools are rejected."""
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("block numbers must be integers or integer strings, never float/bool")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError("block number must be integral")
        return int(value)
    if isinstance(value, str) and value.strip():
        return int(value.strip())
    raise ValueError(f"cannot coerce {type(value).__name__} to a block number")


# ── Shared envelopes ─────────────────────────────────────────────────────────

class StablecoinEvidenceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_class: StablecoinEvidenceClass = "fact"
    source_refs: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    confidence: str = "0"
    valid_time: str = ""
    recorded_time: str = ""
    explanation: str = ""


class EntityRef(BaseModel):
    """Mirror of packages/shared/entities.ts EntityRef (extra keys such as
    tenant_id are tolerated so graph builders can validate tenancy)."""

    model_config = ConfigDict(extra="allow")

    kind: str
    id: str
    label: Optional[str] = None


class StablecoinTenantScoped(BaseModel):
    """Tenant-scoped envelope — observation-only, never execution."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    idempotency_key: str
    evidence: Optional[StablecoinEvidenceEnvelope] = None
    execution_by_aether: Literal[False] = False


# ── Global reference models ──────────────────────────────────────────────────

class StablecoinAssetCanonical(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_asset_id: str
    symbol: str
    name: str
    issuer_entity_id: Optional[str] = None
    issuer_name: Optional[str] = None
    backing_model: StablecoinBackingModel = "unknown"
    pegged_to: str = "USD"
    asset_status: StablecoinAssetStatus = "active"
    risk_classification: Optional[str] = None
    first_seen_at: str = ""
    global_reference: Literal[True] = True


class StablecoinDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: str
    canonical_asset_id: str
    chain_id: str
    network: str
    token_standard: str
    contract_or_mint: str
    decimals: int = Field(ge=0, le=36)
    deployment_type: StablecoinDeploymentType = "unknown"
    bridge_origin_deployment_id: Optional[str] = None
    issuer_verified: bool = False
    active: bool = True
    testnet: bool = False
    first_seen_at: str = ""
    last_seen_at: Optional[str] = None
    deprecated_at: Optional[str] = None
    global_reference: Literal[True] = True


# ── Tenant-scoped canonical records ─────────────────────────────────────────

class StablecoinObservation(StablecoinTenantScoped):
    observation_id: str
    observation_type: StablecoinObservationType
    deployment_id: str
    canonical_asset_id: str
    chain_id: str
    network: Optional[str] = None
    block_number: Optional[int] = None
    block_hash: Optional[str] = None
    transaction_hash: str
    log_or_instruction_index: Optional[int] = None
    amount_atomic: Decimal
    amount_decimal: Decimal
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    from_wallet_id: Optional[str] = None
    to_wallet_id: Optional[str] = None
    from_entity_ref: Optional[EntityRef] = None
    to_entity_ref: Optional[EntityRef] = None
    counterparty_class: Optional[str] = None
    protocol_id: Optional[str] = None
    merchant_id: Optional[str] = None
    facilitator_id: Optional[str] = None
    agent_id: Optional[str] = None
    campaign_id: Optional[str] = None
    journey_id: Optional[str] = None
    session_id: Optional[str] = None
    finality_status: StablecoinFinalityStatus = "provisional"
    finalized_at: Optional[str] = None
    classification_confidence: str = "0"
    observed_at: str
    ingested_at: str

    _amounts = field_validator("amount_atomic", "amount_decimal", mode="before")(
        _decimal_or_error
    )
    _block = field_validator("block_number", mode="before")(_block_int)


class StablecoinValuationSnapshot(StablecoinTenantScoped):
    valuation_id: str
    deployment_id: str
    price_usd: Decimal
    peg_deviation_bps: Decimal
    peg_status: PegStatus
    source: str
    source_record_id: Optional[str] = None
    observed_at: str
    stale_after: Optional[str] = None

    _amounts = field_validator("price_usd", "peg_deviation_bps", mode="before")(
        _decimal_or_error
    )


class StablecoinSupportAssertion(StablecoinTenantScoped):
    assertion_id: str
    subject_entity_ref: EntityRef
    deployment_id: str
    capability: StablecoinCapability
    support_status: SupportAssertionStatus
    environment: StablecoinEnvironment = "production"
    evidence_type: str
    evidence_reference: Optional[str] = None
    first_observed_at: Optional[str] = None
    last_observed_at: Optional[str] = None
    successful_observation_count: int = Field(default=0, ge=0)
    failed_observation_count: int = Field(default=0, ge=0)
    confidence: str = "0"
    expires_at: Optional[str] = None


class StablecoinFlowAggregate(StablecoinTenantScoped):
    flow_aggregate_id: str
    canonical_asset_id: str
    deployment_id: Optional[str] = None
    chain_id: Optional[str] = None
    window_start: str
    window_end: str
    direction: StablecoinFlowDirection
    gross_transfer_volume_decimal: Decimal
    finalized_payment_volume_decimal: Decimal
    transfer_count: int = Field(default=0, ge=0)
    unique_senders: int = Field(default=0, ge=0)
    unique_recipients: int = Field(default=0, ge=0)
    metric_version: str
    materialized_at: str

    _amounts = field_validator(
        "gross_transfer_volume_decimal", "finalized_payment_volume_decimal", mode="before"
    )(_decimal_or_error)


class StablecoinReconciliationRecord(StablecoinTenantScoped):
    reconciliation_id: str
    observation_id: Optional[str] = None
    transaction_hash: Optional[str] = None
    status: StablecoinReconciliationStatus
    expected_amount_decimal: Optional[Decimal] = None
    observed_amount_decimal: Optional[Decimal] = None
    difference_decimal: Optional[Decimal] = None
    sources_compared: list[str] = Field(default_factory=list)
    resolved_at: Optional[str] = None
    resolution_note: Optional[str] = None

    _amounts = field_validator(
        "expected_amount_decimal", "observed_amount_decimal", "difference_decimal",
        mode="before",
    )(_optional_decimal)


class StablecoinFinalityCheckpoint(StablecoinTenantScoped):
    checkpoint_id: str
    chain_id: str
    confirmed_block_number: int
    confirmed_block_hash: Optional[str] = None
    confirmation_horizon: int = Field(ge=0)
    advanced_at: str

    _block = field_validator("confirmed_block_number", mode="before")(_block_int)


# ── Ingest / request payloads (API boundary) ─────────────────────────────────

class StablecoinObservationIngest(BaseModel):
    """Ingest payload for POST /v1/stablecoins/observations.

    observation_id / idempotency_key are derived deterministically by the
    pipeline — callers never supply them. 'unknown' observation_type is not
    ingestable (422 at the route boundary).
    """

    model_config = ConfigDict(extra="forbid")

    observation_type: IngestObservationType
    chain_id: str
    network: Optional[str] = None
    block_number: Optional[int] = None
    block_hash: Optional[str] = None
    transaction_hash: str
    log_or_instruction_index: Optional[int] = None
    contract_or_mint: Optional[str] = None
    deployment_id: Optional[str] = None
    canonical_asset_id: Optional[str] = None
    decimals: Optional[int] = Field(default=None, ge=0, le=36)
    amount_atomic: Decimal
    amount_decimal: Optional[Decimal] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None
    from_wallet_id: Optional[str] = None
    to_wallet_id: Optional[str] = None
    from_entity_ref: Optional[EntityRef] = None
    to_entity_ref: Optional[EntityRef] = None
    counterparty_class: Optional[str] = None
    protocol_id: Optional[str] = None
    merchant_id: Optional[str] = None
    facilitator_id: Optional[str] = None
    agent_id: Optional[str] = None
    campaign_id: Optional[str] = None
    journey_id: Optional[str] = None
    session_id: Optional[str] = None
    finality_status: StablecoinFinalityStatus = "provisional"
    classification_confidence: Optional[str] = None
    observed_at: str
    evidence: Optional[StablecoinEvidenceEnvelope] = None
    tenant_id: Optional[str] = None  # must match the authenticated tenant when present
    execution_by_aether: Literal[False] = False

    _amounts = field_validator("amount_atomic", "amount_decimal", mode="before")(
        _optional_decimal
    )
    _block = field_validator("block_number", mode="before")(_block_int)

    @field_validator("amount_atomic")
    @classmethod
    def _atomic_is_integral(cls, v: Decimal) -> Decimal:
        if v != v.to_integral_value():
            raise ValueError("amount_atomic must be an integral atomic amount")
        return v


class StablecoinValuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: str
    price_usd: Decimal
    source: str
    observed_at: str
    source_record_id: Optional[str] = None
    stale_after: Optional[str] = None
    evidence: Optional[StablecoinEvidenceEnvelope] = None
    tenant_id: Optional[str] = None
    execution_by_aether: Literal[False] = False

    _amounts = field_validator("price_usd", mode="before")(_decimal_or_error)


class StablecoinSupportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_entity_ref: EntityRef
    deployment_id: str
    capability: StablecoinCapability
    support_status: SupportAssertionStatus
    environment: StablecoinEnvironment = "production"
    evidence_type: str
    evidence_reference: Optional[str] = None
    first_observed_at: Optional[str] = None
    last_observed_at: Optional[str] = None
    successful_observation_count: int = Field(default=0, ge=0)
    failed_observation_count: int = Field(default=0, ge=0)
    confidence: str = "0"
    expires_at: Optional[str] = None
    evidence: Optional[StablecoinEvidenceEnvelope] = None
    tenant_id: Optional[str] = None
    execution_by_aether: Literal[False] = False


class StablecoinFlowComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_asset_id: str
    window_start: str
    window_end: str
    deployment_id: Optional[str] = None
    chain_id: Optional[str] = None
    tenant_id: Optional[str] = None
    execution_by_aether: Literal[False] = False
