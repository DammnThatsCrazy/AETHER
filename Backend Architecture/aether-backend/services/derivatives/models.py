"""Canonical derivatives ingestion models.

These models are intentionally independent from venue SDKs. They carry only
read-only observations and normalized facts; any attempt to model Aether as the
executor remains fail-closed with ``execution_by_aether = False``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping


class DerivativesValidationError(ValueError):
    """Raised when provider data cannot be safely normalized."""


class ReadOnlyCredentialError(DerivativesValidationError):
    """Raised when a credential grants trading, transfer, withdrawal, or mutation scope."""


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class PositionSide(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class LiquidityRole(StrEnum):
    MAKER = "maker"
    TAKER = "taker"
    UNKNOWN = "unknown"


class PositionStatus(StrEnum):
    ABSENT = "absent"
    OPEN = "open"
    CLOSED = "closed"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True)
class SourceRef:
    provider: str
    source_record_id: str
    observed_at: str
    finality: str = "authoritative"

    @property
    def idempotency_component(self) -> str:
        return f"{self.provider}:{self.source_record_id}"


@dataclass(frozen=True)
class BronzeObservation:
    tenant_id: str
    provider: str
    deployment: str
    record_type: str
    source_record_id: str
    raw_payload: Mapping[str, Any]
    observed_at: str
    idempotency_key: str
    execution_by_aether: bool = False


@dataclass(frozen=True)
class NormalizedFillFact:
    tenant_id: str
    provider: str
    deployment: str
    trading_account_id: str
    canonical_market_id: str
    fill_id: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    executed_at: str
    liquidity_role: LiquidityRole = LiquidityRole.UNKNOWN
    fee_amount: Decimal = Decimal("0")
    fee_asset_id: str | None = None
    source_ref: SourceRef | None = None
    execution_by_aether: bool = False

    def __post_init__(self) -> None:
        _reject_float(self.price, "price")
        _reject_float(self.quantity, "quantity")
        _reject_float(self.fee_amount, "fee_amount")
        if self.quantity <= 0:
            raise DerivativesValidationError("fill quantity must be positive")
        if self.price <= 0:
            raise DerivativesValidationError("fill price must be positive")
        if self.execution_by_aether:
            raise DerivativesValidationError("Aether must not be marked as execution venue")

    @property
    def idempotency_key(self) -> str:
        source = self.source_ref.idempotency_component if self.source_ref else self.fill_id
        return ":".join([self.tenant_id, self.provider, self.deployment, self.trading_account_id, source])


@dataclass
class PositionEpochState:
    tenant_id: str
    trading_account_id: str
    canonical_market_id: str
    epoch_id: str
    side: PositionSide = PositionSide.FLAT
    status: PositionStatus = PositionStatus.ABSENT
    size: Decimal = Decimal("0")
    entry_notional: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    opened_at: str | None = None
    closed_at: str | None = None
    source_fill_ids: list[str] = field(default_factory=list)

    @property
    def entry_price(self) -> Decimal | None:
        if self.size == 0:
            return None
        return abs(self.entry_notional / self.size)

    @property
    def net_realized_pnl(self) -> Decimal:
        return self.realized_pnl - self.fees


def decimal_from_provider(value: Any, field_name: str) -> Decimal:
    """Parse provider numerics without accepting binary floating point."""
    if isinstance(value, float):
        raise DerivativesValidationError(f"{field_name} must not be a binary float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise DerivativesValidationError(f"{field_name} is empty")
        return Decimal(stripped)
    raise DerivativesValidationError(f"{field_name} has unsupported type {type(value).__name__}")


def _reject_float(value: Any, field_name: str) -> None:
    if isinstance(value, float):
        raise DerivativesValidationError(f"{field_name} must not be a binary float")


_MUTATING_SCOPE_TOKENS = {
    "trade", "trading", "order", "orders:write", "withdraw", "withdrawal", "transfer",
    "transfers", "key", "key_management", "account:write", "wallet:write", "admin", "write",
}


def validate_read_only_scopes(scopes: list[str] | tuple[str, ...] | set[str]) -> None:
    normalized = {scope.strip().lower().replace("-", "_") for scope in scopes}
    mutating = sorted(scope for scope in normalized if scope in _MUTATING_SCOPE_TOKENS or scope.endswith(":write"))
    if mutating:
        raise ReadOnlyCredentialError(f"credential grants mutating scopes: {', '.join(mutating)}")
