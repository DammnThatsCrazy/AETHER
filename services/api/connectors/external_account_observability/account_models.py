"""External account observability — agentic account models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class ExternalAgenticAccountObservedRecord(BaseModel):
    account_obs_id: str = Field(default_factory=_new_id)
    agent_id: Optional[str] = None
    provider: str
    external_account_id: str
    account_type: Optional[str] = None
    permissions_observed: list[str] = Field(default_factory=list)
    connected_at: Optional[str] = None
    disconnected_at: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    execution_by_aether: Literal[False] = False


class AgentDisconnectObservedRecord(BaseModel):
    disconnect_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    reason: Optional[str] = None
    disconnected_at: Optional[str] = None
    initiated_by_external: bool = True
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class AgentNotificationObservedRecord(BaseModel):
    notification_obs_id: str = Field(default_factory=_new_id)
    account_obs_id: Optional[str] = None
    notification_type: Optional[str] = None
    summary_ref: Optional[str] = None
    received_at: str = Field(default_factory=_utc_now)
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
