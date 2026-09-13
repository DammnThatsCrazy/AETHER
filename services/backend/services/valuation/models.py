"""Valuation contracts — Pydantic v2 mirror of packages/shared/financial-assets.ts
and the additive packages/shared/value.ts CanonicalNativeValue contract.

Universal financial normalization (C1) valuation trunk: append-only market price
observations, tenant-scoped immutable valuation snapshots, tenant value policy
and canonical native values. All amounts are Decimal guarded by the
float-rejecting ``repositories.typed_repo.as_decimal`` — binary floats are never
legal carriers. ``reporting_amount`` is Optional[Decimal]; None means UNAVAILABLE
(never coerced to Decimal("0")).

Frozenset ownership (future parity validator compares each TS union against
exactly one Python frozenset of identical snake_case strings):
  OWNED HERE:  ECONOMIC_ROLES, PRICE_STATUSES, VALUATION_BASIS,
               VALUATION_METHOD_EXTENDED
  OWNED BY services/assets/models.py (NOT duplicated here):
               ASSET_KINDS, CHAIN_STATUSES, RESOLUTION_STATUSES,
               ALIAS_VERIFICATION_STATUSES, UNRESOLVED_REASONS
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from repositories.typed_repo import as_decimal

# ── Frozensets (parity surface with financial-assets.ts runtime arrays) ──────

ECONOMIC_ROLES = frozenset({
    "payment", "settlement", "charge", "fee", "cost", "revenue",
    "refund", "reversal", "dispute", "liability", "asset_holding",
    "exposure", "compensation", "unknown",
})
PRICE_STATUSES = frozenset({
    "normal", "provider_conflict", "stale_rate", "missing_rate", "outlier",
    "fallback", "manual", "unavailable",
})
VALUATION_BASIS = frozenset({
    "transaction_time", "event_time", "settlement_time", "observation_time",
})
# Existing value.ts ValuationMethod members PLUS the additive extended members.
VALUATION_METHOD_EXTENDED = frozenset({
    "fiat_identity", "fx_rate", "market_price", "provider_reported",
    "stablecoin_peg_verified", "manual", "unavailable",
    "oracle", "venue_exec", "primary_market", "stablecoin_peg",
})

# ── Literal unions (mirror financial-assets.ts unions) ───────────────────────

EconomicRole = Literal[
    "payment", "settlement", "charge", "fee", "cost", "revenue",
    "refund", "reversal", "dispute", "liability", "asset_holding",
    "exposure", "compensation", "unknown",
]
PriceStatus = Literal[
    "normal", "provider_conflict", "stale_rate", "missing_rate", "outlier",
    "fallback", "manual", "unavailable",
]
ValuationBasis = Literal[
    "transaction_time", "event_time", "settlement_time", "observation_time",
]
ValuationMethodExtended = Literal[
    "fiat_identity", "fx_rate", "market_price", "provider_reported",
    "stablecoin_peg_verified", "manual", "unavailable",
    "oracle", "venue_exec", "primary_market", "stablecoin_peg",
]

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


# ── Valuation models ─────────────────────────────────────────────────────────

class MarketPriceObservation(BaseModel):
    """Append-only market price observation (one immutable fact).

    Named MarketPriceObservation because the derivatives domain already owns
    ``PriceObservation`` in TS (both are barrel-exported from @aether/shared);
    this is the financial-normalization trunk observation.
    """

    model_config = ConfigDict(extra="forbid")

    observation_id: Optional[str] = None
    asset_id: str
    deployment_id: Optional[str] = None
    provider: str
    price: Decimal
    quote_asset_id: str
    observed_at: str
    source: str
    freshness_window_seconds: Optional[int] = Field(default=None, ge=1)
    source_record_id: Optional[str] = None
    received_at: Optional[str] = None

    _price = field_validator("price", mode="before")(_decimal_or_error)


class ValuationSnapshot(BaseModel):
    """Tenant-scoped, immutable valuation snapshot. reporting_amount None means
    UNAVAILABLE — never Decimal("0"). native_amount preserves the observed
    native value verbatim."""

    model_config = ConfigDict(extra="forbid")

    valuation_id: str
    tenant_id: str
    canonical_asset_id: Optional[str] = None
    deployment_id: Optional[str] = None
    economic_role: EconomicRole = "unknown"
    native_amount: Decimal
    native_currency: str
    reporting_asset_id: str
    reporting_amount: Optional[Decimal] = None
    valuation_basis: ValuationBasis
    price_status: PriceStatus
    valuation_method: ValuationMethodExtended
    provider: Optional[str] = None
    conversion_refs: list[str] = Field(default_factory=list)
    registry_version: Optional[str] = None
    policy_version: Optional[str] = None
    price_observation_ids: list[str] = Field(default_factory=list)
    supersedes_valuation_id: Optional[str] = None
    superseded_by_valuation_id: Optional[str] = None
    computed_at: str
    effective_at: str

    _amounts = field_validator("native_amount", "reporting_amount", mode="before")(
        _optional_decimal
    )


class TenantValuePolicy(BaseModel):
    """A tenant's valuation policy: which reporting assets are allowed, which
    named provider-chain policy governs sourcing, and whether fallback is
    permitted. provider_chain_policy is the id of a named policy resolved by the
    valuation service (mirror of the TS string field)."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    allowed_reporting_asset_ids: list[str]
    provider_chain_policy: str
    stale_threshold_seconds: Optional[int] = Field(default=None, ge=1)
    fallback_allowed: bool
    policy_version: Optional[str] = None


class CanonicalNativeValue(BaseModel):
    """Mirror of the additive packages/shared/value.ts CanonicalNativeValue
    (NativeValue with a REQUIRED namespaced canonical_asset_id). The observed
    native amount/currency are preserved verbatim — canonicalization never
    rewrites the observed amount."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    currency: str
    canonical_asset_id: str
    deployment_id: Optional[str] = None
    asset_id: Optional[str] = None
    asset_symbol: Optional[str] = None
    asset_name: Optional[str] = None
    chain: Optional[str] = None
    network: Optional[str] = None
    contract_or_mint: Optional[str] = None
    decimals: Optional[int] = Field(default=None, ge=0, le=36)
    economic_role: EconomicRole = "unknown"
    provider: Optional[str] = None
    account_id: Optional[str] = None
    wallet_id: Optional[str] = None
    rail: Optional[str] = None

    _amount = field_validator("amount", mode="before")(_decimal_or_error)
