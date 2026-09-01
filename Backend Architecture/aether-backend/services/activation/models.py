"""Self-serve activation lifecycle contracts.

Additive alongside :mod:`services.onboarding` (the operator-driven
implementation lifecycle). This package models the *tenant-driven* self-serve
path: verify account -> select plan -> confirm billing -> select SDKs ->
create keys -> send a first event -> prove first value -> complete.

State is derived from real evidence only. The ``manual_pending``, ``blocked``
and ``externally_blocked`` states exist so the service can record honestly that
a precondition could not be met, rather than faking a forward state.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ActivationState(str, Enum):
    not_started = "not_started"
    account_verified = "account_verified"
    plan_selected = "plan_selected"
    billing_pending = "billing_pending"
    billing_active = "billing_active"
    sdk_selected = "sdk_selected"
    keys_created = "keys_created"
    waiting_for_event = "waiting_for_event"
    event_received = "event_received"
    first_value_ready = "first_value_ready"
    complete = "complete"
    manual_pending = "manual_pending"
    blocked = "blocked"
    externally_blocked = "externally_blocked"


class ActivationRecord(BaseModel):
    """Persisted self-serve activation state for one tenant.

    ``selected_plan_tier`` is a plan tier (P1..P4) and NEVER a Stripe price id.
    ``created_key_ids`` holds HASHED key identifiers only — raw API keys are
    returned to the caller exactly once at creation time and are never stored.
    """

    activation_id: str
    tenant_id: str
    state: ActivationState = ActivationState.not_started
    selected_plan_tier: Optional[str] = Field(default=None, pattern="^(P1|P2|P3|P4)$")
    sdk_selection: list[str] = Field(default_factory=list)
    created_key_ids: list[str] = Field(default_factory=list)
    first_event_id: Optional[str] = None
    first_event_batch_id: Optional[str] = None
    first_value_evidence: dict[str, Any] = Field(default_factory=dict)
    waiting_reason: Optional[str] = None
    rights_policy_set_ref: Optional[str] = None
    rights_activation_state: Optional[str] = None
    rights_blocked_reason: Optional[str] = None
    manual_reason: Optional[str] = None
    blocked_reason: Optional[str] = None
    created_at: str
    updated_at: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class SelectPlanRequest(BaseModel):
    plan_tier: str = Field(..., pattern="^(P1|P2|P3|P4)$")


class SdkSelectionRequest(BaseModel):
    platforms: list[str] = Field(default_factory=list, max_length=50)


class CreateSdkKeysRequest(BaseModel):
    count: int = Field(default=1, ge=1, le=5)
    label: str = Field(default="onboarding key", max_length=200)


class TestEventRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=128)
    properties: Optional[dict[str, Any]] = Field(default_factory=dict)
    anonymous_id: Optional[str] = Field(default=None, max_length=256)
    session_id: Optional[str] = Field(default=None, max_length=256)
