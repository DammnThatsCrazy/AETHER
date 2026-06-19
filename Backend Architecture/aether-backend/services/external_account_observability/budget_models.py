"""External account observability — budget and permission models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class AgentBudgetObservedRecord(BaseModel):
    budget_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    total_budget: Optional[float] = None
    used_budget: Optional[float] = None
    available_budget: Optional[float] = None
    currency: str = "USD"
    as_of: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class AgentPermissionObservedRecord(BaseModel):
    permission_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    scopes_observed: list[str] = Field(default_factory=list)
    granted_at: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
