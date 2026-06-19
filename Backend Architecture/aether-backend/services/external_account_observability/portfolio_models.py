"""External account observability — portfolio and position models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class PositionSnapshotObservedRecord(BaseModel):
    position_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    symbol: str
    quantity: float
    avg_cost: Optional[float] = None
    current_value: Optional[float] = None
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)


class PortfolioSnapshotObservedRecord(BaseModel):
    portfolio_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    total_value: Optional[float] = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)


class AgentPerformanceSnapshotObservedRecord(BaseModel):
    perf_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    period: Optional[str] = None
    pnl: Optional[float] = None
    win_rate: Optional[float] = None
    strategy_obs_id: Optional[str] = None
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)
