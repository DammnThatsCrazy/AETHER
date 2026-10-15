"""Canonical Stablecoin Intelligence contracts.

The module is intentionally dependency-light so repositories, routes, SDK
parity tests, and migrations can share one source of truth for PR1 foundation.
Aether remains observation-first: these models describe externally observed
facts and evidence, never Aether-executed payments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Optional

SCHEMA_VERSION = "stablecoin.intelligence.v1"


class FinalityState(str, Enum):
    OBSERVED = "observed"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FINALIZED = "finalized"
    REVERTED = "reverted"
    DROPPED = "dropped"
    FAILED = "failed"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class StablecoinEventType(str, Enum):
    TRANSFER = "transfer"
    PAYMENT = "payment"
    SETTLEMENT_OBSERVATION = "settlement_observation"
    REFUND = "refund"
    REVERSAL = "reversal"
    MINT = "mint"
    BURN = "burn"
    REDEMPTION = "redemption"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    SWAP = "swap"
    BRIDGE_DEPOSIT = "bridge_deposit"
    BRIDGE_MINT = "bridge_mint"
    BRIDGE_BURN = "bridge_burn"
    BRIDGE_RELEASE = "bridge_release"
    LIQUIDITY_ADDITION = "liquidity_addition"
    LIQUIDITY_REMOVAL = "liquidity_removal"
    COLLATERAL_DEPOSIT = "collateral_deposit"
    COLLATERAL_WITHDRAWAL = "collateral_withdrawal"
    TREASURY_TRANSFER = "treasury_transfer"
    REWARD = "reward"
    FEE = "fee"
    AGENT_REQUESTED_PAYMENT = "agent_requested_payment"
    X402_CHALLENGE_OBSERVED = "x402_challenge_observed"
    X402_PAYMENT_OBSERVED = "x402_payment_observed"
    UNKNOWN_STABLECOIN_MOVEMENT = "unknown_stablecoin_movement"


class StablecoinCapability(str, Enum):
    SEND = "send"
    RECEIVE = "receive"
    HOLD = "hold"
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"
    ACCEPT_PAYMENT = "accept_payment"
    SETTLE = "settle"
    REFUND = "refund"
    SWAP = "swap"
    BRIDGE = "bridge"
    MINT = "mint"
    REDEEM = "redeem"
    COLLATERAL = "collateral"
    REWARDS = "rewards"
    X402 = "x402"
    AGENT_EXPENSES = "agent_expenses"
    TREASURY = "treasury"
    BALANCE_REPORTING = "balance_reporting"


class SupportState(str, Enum):
    ANNOUNCED = "announced"
    REGISTERED = "registered"
    CONFIGURED = "configured"
    SANDBOX_TESTED = "sandbox_tested"
    PRODUCTION_TESTED = "production_tested"
    OBSERVED = "observed"
    PRODUCTION_ACTIVE = "production_active"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


FINALIZED_VOLUME_STATES = frozenset({FinalityState.FINALIZED})
ACTIVE_VOLUME_STATES = frozenset({FinalityState.CONFIRMED, FinalityState.FINALIZED})


@dataclass(frozen=True)
class StablecoinMoney:
    """Decimal-safe token amount paired with canonical deployment identity."""

    amount_atomic: int
    decimals: int
    canonical_asset_id: str
    deployment_id: str
    chain_id: str
    network: str

    def __post_init__(self) -> None:
        if not self.canonical_asset_id or not self.deployment_id or not self.chain_id or not self.network:
            raise ValueError("stablecoin money requires asset, deployment, chain, and network")
        if not isinstance(self.amount_atomic, int):
            raise TypeError("amount_atomic must be an integer")
        if self.decimals < 0 or self.decimals > 38:
            raise ValueError("decimals must be between 0 and 38")

    @property
    def amount_decimal(self) -> Decimal:
        return Decimal(self.amount_atomic).scaleb(-self.decimals)

    def assert_same_unit(self, other: "StablecoinMoney") -> None:
        if (self.canonical_asset_id, self.deployment_id, self.chain_id, self.network) != (
            other.canonical_asset_id,
            other.deployment_id,
            other.chain_id,
            other.network,
        ):
            raise ValueError("cannot combine unlike stablecoin units")

    def add(self, other: "StablecoinMoney") -> "StablecoinMoney":
        self.assert_same_unit(other)
        return StablecoinMoney(
            self.amount_atomic + other.amount_atomic,
            self.decimals,
            self.canonical_asset_id,
            self.deployment_id,
            self.chain_id,
            self.network,
        )


@dataclass(frozen=True)
class StablecoinDeployment:
    deployment_id: str
    canonical_asset_id: str
    chain_id: str
    network: str
    token_standard: str
    contract_or_mint: str
    decimals: int
    deployment_type: str = "canonical"
    canonical_or_wrapped: str = "canonical"
    issuer_verified: bool = False
    active: bool = True
    testnet: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StablecoinObservation:
    observation_id: str
    tenant_id: str
    source: str
    source_record_id: str
    source_execution_id: str
    observed_at: str
    chain_id: str
    network: str
    transaction_hash: str
    finality_status: FinalityState
    event_type: StablecoinEventType
    deployment_id: str
    canonical_asset_id: str
    amount_atomic: int
    schema_version: str = SCHEMA_VERSION
    source_manifest_id: str = ""
    evidence_id: str = ""
    log_or_instruction_index: Optional[int] = None
    from_address: str = ""
    to_address: str = ""
    classification_confidence: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id is required for tenant-owned stablecoin observations")
        if not self.source_execution_id:
            raise ValueError("source_execution_id is required to distinguish repeated provider executions")
        if not self.deployment_id or not self.canonical_asset_id or not self.chain_id:
            raise ValueError("deployment, asset, and chain identity are required")
        if not isinstance(self.amount_atomic, int):
            raise TypeError("amount_atomic must be an integer")


def parse_decimal(value: str | int | Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
