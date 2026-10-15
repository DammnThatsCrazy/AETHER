"""Derivatives canonical Pydantic models (API + persistence boundary).

Mirrors of the packages/shared/derivatives.ts contracts that the runtime
persists. Every monetary/quantity field is Decimal (floats raise), JSON
serialization is string, and execution_by_aether is the Literal False —
constructing an "executed by Aether" record is a type error.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from repositories.typed_repo import as_decimal

OrderStatus = Literal[
    "pending", "open", "partially_filled", "filled", "cancelled", "rejected", "expired", "unknown",
]
OrderSide = Literal["buy", "sell", "unknown"]
OrderType = Literal[
    "market", "limit", "stop_market", "stop_limit", "take_profit_market",
    "take_profit_limit", "twap", "unknown",
]
TimeInForce = Literal["gtc", "ioc", "fok", "post_only", "reduce_only", "unknown"]
PositionSide = Literal["long", "short", "flat", "unknown"]
PositionStatus = Literal[
    "absent", "opening", "open", "increasing", "reducing", "closing", "closed",
    "liquidating", "liquidated", "auto_deleveraged", "settlement_pending", "settled",
    "reconciliation_required", "source_stale", "unknown",
]
DecisionOrigin = Literal["human", "agent", "service", "venue", "import", "unknown"]
AccountingMethod = Literal[
    "average_entry", "venue_reported", "linear_contract", "inverse_contract",
    "manual_review", "unknown",
]
ConnectorState = Literal[
    "configured", "testing", "active", "paused", "backfilling", "stale", "error",
    "revoked", "unknown",
]


def _decimal_or_error(value: Any) -> Decimal:
    return as_decimal(value)


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return as_decimal(value)


class DerivativesTenantScoped(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    idempotency_key: str
    execution_by_aether: Literal[False] = False


class DerivativesOrder(DerivativesTenantScoped):
    order_id: str
    trading_account_id: str
    canonical_market_id: str
    order_type: OrderType = "unknown"
    order_side: OrderSide
    order_status: OrderStatus
    time_in_force: TimeInForce = "unknown"
    quantity: Decimal
    limit_price: Optional[Decimal] = None
    origin: DecisionOrigin = "unknown"
    source_refs: list[str] = Field(default_factory=list)
    recorded_at: str = ""

    _qty = field_validator("quantity", mode="before")(_decimal_or_error)
    _px = field_validator("limit_price", mode="before")(_optional_decimal)

    @field_serializer("quantity", "limit_price")
    def _ser(self, value: Optional[Decimal]) -> Optional[str]:
        return None if value is None else str(value)


class TradeFill(DerivativesTenantScoped):
    fill_id: str
    order_id: Optional[str] = None
    trading_account_id: str
    canonical_market_id: str
    side: OrderSide
    liquidity_role: Literal["maker", "taker", "auction", "unknown"] = "unknown"
    price: Decimal
    quantity: Decimal
    fee_amount: Optional[Decimal] = None
    fee_asset_id: Optional[str] = None
    executed_at: str
    source_refs: list[str] = Field(default_factory=list)

    _amounts = field_validator("price", "quantity", mode="before")(_decimal_or_error)
    _fee = field_validator("fee_amount", mode="before")(_optional_decimal)

    @field_serializer("price", "quantity", "fee_amount")
    def _ser(self, value: Optional[Decimal]) -> Optional[str]:
        return None if value is None else str(value)


class Position(DerivativesTenantScoped):
    position_id: str
    position_epoch_id: str
    trading_account_id: str
    canonical_market_id: str
    side: PositionSide
    status: PositionStatus
    size: Decimal
    entry_price: Optional[Decimal] = None
    realized_pnl: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    accounting_method: AccountingMethod = "average_entry"
    updated_at: str = ""

    _size = field_validator("size", mode="before")(_decimal_or_error)
    _optional = field_validator(
        "entry_price", "realized_pnl", "unrealized_pnl", mode="before",
    )(_optional_decimal)

    @field_serializer("size", "entry_price", "realized_pnl", "unrealized_pnl")
    def _ser(self, value: Optional[Decimal]) -> Optional[str]:
        return None if value is None else str(value)


class AccountLinkRequest(BaseModel):
    """POST /v1/derivatives/accounts/link — read-only account link intake."""

    model_config = ConfigDict(extra="forbid")

    venue_id: str
    external_account_ref: str
    venue_deployment_id: Optional[str] = None
    owner_entity_kind: Optional[str] = None
    owner_entity_id: Optional[str] = None
    credential_reference_id: Optional[str] = None
    authority_type: Literal["read_only"] = "read_only"
    tenant_id: Optional[str] = None
    execution_by_aether: Literal[False] = False


class DerivativesObservationIn(BaseModel):
    """POST /v1/derivatives/observations — canonical event intake."""

    model_config = ConfigDict(extra="forbid")

    event_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = None
    execution_by_aether: Literal[False] = False
