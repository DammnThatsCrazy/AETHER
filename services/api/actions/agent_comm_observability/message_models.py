"""Agent communication observability — message and attachment models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class AgentMessageObservedRecord(BaseModel):
    message_obs_id: str = Field(default_factory=_new_id)
    thread_obs_id: Optional[str] = None
    inbox_obs_id: Optional[str] = None
    direction: str = "inbound"
    from_address: Optional[str] = None
    to_addresses: list[str] = Field(default_factory=list)
    subject: Optional[str] = None
    has_attachments: bool = False
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
    received_at: str = Field(default_factory=_utc_now)


class AgentAttachmentObservedRecord(BaseModel):
    attachment_obs_id: str = Field(default_factory=_new_id)
    message_obs_id: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    parsed: bool = False
    extracted_entities_count: int = 0
    tenant_id: str
    observed_at: str = Field(default_factory=_utc_now)
