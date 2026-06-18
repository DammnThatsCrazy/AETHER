"""External account observability — brokerage and trading models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


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
    quantity: float
    price_type: str = "market"
    submitted_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class TradeOrderObservedRecord(BaseModel):
    order_obs_id: str = Field(default_factory=_new_id)
    intent_obs_id: Optional[str] = None
    external_order_id: Optional[str] = None
    status: str = "pending"
    symbol: str
    side: str = "buy"
    quantity: float
    filled_qty: Optional[float] = None
    avg_price: Optional[float] = None
    executed_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class TradeFillObservedRecord(BaseModel):
    fill_obs_id: str = Field(default_factory=_new_id)
    order_obs_id: Optional[str] = None
    symbol: str
    quantity: float
    price: float
    executed_externally: Literal[True] = True
    execution_by_aether: Literal[False] = False
    tenant_id: str
    filled_at: str = Field(default_factory=_utc_now)


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
    total_value: Optional[float] = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)
