"""Client-sync Pydantic contract — twin of packages/shared/sync-event.ts.

Drift-guarded by tests/contracts/test_sync_event_contract_parity.py. Wire fields
are snake_case (decision-log D6). Change rows carry ids + revisions only, never a
resource body — the client re-fetches through its normal scoped endpoints.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

# The exactly-ten change types the feed emits (snake_case, no digits — the parity
# scraper matches only [a-z_]+). Pinned by the parity test.
SYNC_CHANGE_TYPES: tuple[str, ...] = (
    "notification_changed",
    "continuation_changed",
    "saved_view_changed",
    "conversation_changed",
    "watchlist_changed",
    "incident_changed",
    "command_receipt_changed",
    "preference_changed",
    "session_revoked",
    "installation_revoked",
)


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncEvent(_Base):
    id: str
    scope_key: str
    seq: int
    change_type: str
    resource_kind: Optional[str] = None
    resource_id: Optional[str] = None
    revision: Optional[str] = None
    created_at: str

    @field_validator("change_type")
    @classmethod
    def _change_type(cls, v: str) -> str:
        if v not in SYNC_CHANGE_TYPES:
            raise ValueError(f"change_type must be one of {SYNC_CHANGE_TYPES}")
        return v


class ClientSyncResponse(_Base):
    events: list[SyncEvent] = []
    cursor: str
    has_more: bool = False
    reset: bool = False
