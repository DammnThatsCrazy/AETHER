"""External account observability — budget and permission models."""
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


class AgentBudgetObservedRecord(BaseModel):
    budget_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    # Decimal-safe money (str/int/Decimal in → decimal string; float rejected).
    total_budget: Optional[str] = None
    used_budget: Optional[str] = None
    available_budget: Optional[str] = None
    currency: str = "USD"
    as_of: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)

    @field_validator("total_budget", "used_budget", "available_budget", mode="before")
    @classmethod
    def _decimal_money(cls, v: Any, info: ValidationInfo) -> Any:
        return decimal_str_from_provider(v, info.field_name)


class AgentPermissionObservedRecord(BaseModel):
    permission_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    scopes_observed: list[str] = Field(default_factory=list)
    granted_at: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
