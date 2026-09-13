"""External account observability — brokerage and trading models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, ValidationInfo, field_validator

from services.agentic_observability.models import decimal_str_from_provider


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class ExternalBrokerageAccountObservedRecord(BaseModel):
    brokerage_obs_id: str = Field(default_factory=_new_id)
    agent_id: Optional[str] = None
    provider: str
    external_account_id: str
    account_type: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    execution_by_aether: Literal[False] = False


class TradingStrategyObservedRecord(BaseModel):
    strategy_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    name: Optional[str] = None
    risk_tolerance: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class TradeIntentObservedRecord(BaseModel):
    intent_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    strategy_obs_id: Optional[str] = None
    symbol: str
    side: str
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float, store as
    # a canonical decimal string (never a lossy binary float on the wire).
    quantity: str
    price_type: str = "market"
    submitted_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)

    @field_validator("quantity", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class TradeOrderObservedRecord(BaseModel):
    order_obs_id: str = Field(default_factory=_new_id)
    intent_obs_id: Optional[str] = None
    external_order_id: Optional[str] = None
    status: str = "pending"
    symbol: str
    side: str = "buy"
    # Decimal-safe money (str/int/Decimal in → decimal string; float rejected).
    quantity: str
    filled_qty: Optional[str] = None
    avg_price: Optional[str] = None
    executed_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)

    @field_validator("quantity", "filled_qty", "avg_price", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class TradeFillObservedRecord(BaseModel):
    fill_obs_id: str = Field(default_factory=_new_id)
    order_obs_id: Optional[str] = None
    symbol: str
    # Decimal-safe money (str/int/Decimal in → decimal string; float rejected).
    quantity: str
    price: str
    executed_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    tenant_id: str
    filled_at: str = Field(default_factory=_utc_now)

    @field_validator("quantity", "price", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class TradeRejectionObservedRecord(BaseModel):
    rejection_obs_id: str = Field(default_factory=_new_id)
    order_obs_id: Optional[str] = None
    reason: Optional[str] = None
    rejected_by_external: bool = True
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class PortfolioSnapshotObservedRecord(BaseModel):
    portfolio_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    # Decimal-safe money (str/int/Decimal in → decimal string; float rejected).
    total_value: Optional[str] = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)

    @field_validator("total_value", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)
