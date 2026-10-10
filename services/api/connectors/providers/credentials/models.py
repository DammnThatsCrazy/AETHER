"""Request models for the slot-aware credential/connection API.

Secret fields are **write-only**: they are accepted on mutation requests and are
never present in any response model. No GET returns a credential value.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SlotValueWrite(BaseModel):
    """Create or replace a credential slot value (write-only)."""

    value: str = Field(..., min_length=1, description="Secret value — write-only, never returned")
    endpoint: Optional[str] = Field(
        None, description="Optional endpoint; only a safe hostname is persisted"
    )
    idempotency_key: Optional[str] = Field(
        None, description="Idempotency key so a retried create is not duplicated"
    )


class SlotRotateRequest(BaseModel):
    """Rotate a slot to a new value with optimistic-concurrency protection."""

    value: str = Field(..., min_length=1, description="New secret value — write-only")
    expected_active_version: Optional[int] = Field(
        None, description="Expected current active version; mismatch → 409 Conflict"
    )
    idempotency_key: Optional[str] = None


class SlotActivateRequest(BaseModel):
    """Activate a specific (already-created) credential version."""

    credential_version: int = Field(..., ge=1)
    expected_active_version: Optional[int] = Field(
        None, description="Expected current active version; mismatch → 409 Conflict"
    )


__all__ = ["SlotValueWrite", "SlotRotateRequest", "SlotActivateRequest"]
