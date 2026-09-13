"""Agent communication observability — inbox and thread models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class AgentInboxObservedRecord(BaseModel):
    inbox_obs_id: str = Field(default_factory=_new_id)
    agent_id: Optional[str] = None
    provider: str = "unknown"
    email_address: Optional[str] = None
    custom_domain: Optional[str] = None
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    received_at: str = Field(default_factory=_utc_now)


class AgentEmailAddressObservedRecord(BaseModel):
    address_obs_id: str = Field(default_factory=_new_id)
    inbox_obs_id: Optional[str] = None
    address: str
    is_primary: bool = False
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)


class AgentThreadObservedRecord(BaseModel):
    thread_obs_id: str = Field(default_factory=_new_id)
    inbox_obs_id: Optional[str] = None
    subject: Optional[str] = None
    participants: list[str] = Field(default_factory=list)
    message_count: int = 0
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
