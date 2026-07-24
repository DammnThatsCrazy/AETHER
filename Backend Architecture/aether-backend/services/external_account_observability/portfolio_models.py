"""External account observability — portfolio and position models.

NOTE: the canonical, route-wired portfolio/position models live in
``brokerage_models.py`` (decimal-safe). These records are retained for
compatibility and are NOT currently written by any route; their money fields are
kept decimal-safe here too so the duplicate ``PortfolioSnapshotObservedRecord``
name cannot reintroduce binary-float money if it is ever wired up.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from services.agentic_observability.models import decimal_str_from_provider


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class PositionSnapshotObservedRecord(BaseModel):
    position_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    symbol: str
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float.
    quantity: str
    avg_cost: Optional[str] = None
    current_value: Optional[str] = None
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)

    @field_validator("quantity", "avg_cost", "current_value", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class PortfolioSnapshotObservedRecord(BaseModel):
    portfolio_obs_id: str = Field(default_factory=_new_id)
    brokerage_obs_id: Optional[str] = None
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float.
    total_value: Optional[str] = None
    positions: list[dict[str, Any]] = Field(default_factory=list)
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)

    @field_validator("total_value", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class AgentPerformanceSnapshotObservedRecord(BaseModel):
    perf_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    period: Optional[str] = None
    # Decimal-safe money: accept str/int/Decimal, REJECT binary float.
    pnl: Optional[str] = None
    win_rate: Optional[float] = None  # a ratio (0..1), not an authoritative money value
    strategy_obs_id: Optional[str] = None
    tenant_id: str
    snapshot_at: str = Field(default_factory=_utc_now)

    @field_validator("pnl", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)
