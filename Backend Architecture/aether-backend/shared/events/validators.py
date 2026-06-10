"""
Payload validators for x402 and agent lifecycle events.
"""
from __future__ import annotations
from typing import Any

from .lifecycle_events import (
    X402_LIFECYCLE_EVENTS, AGENT_LIFECYCLE_EVENTS,
    X402_LEGACY_EVENTS, AGENT_LEGACY_EVENTS,
    ALL_LIFECYCLE_EVENTS,
)

# Fields required per event type
_X402_REQUIRED: dict[str, list[str]] = {
    "x402_resource_requested": ["agent_id", "tenant_id", "resource_id", "service_id"],
    "x402_payment_required": ["agent_id", "tenant_id", "amount", "currency"],
    "x402_quote_received": ["agent_id", "tenant_id", "payment_intent_id"],
    "x402_authorization_requested": ["agent_id", "tenant_id", "authorization_id"],
    "x402_authorization_resolved": ["agent_id", "tenant_id", "authorization_id", "status"],
    "x402_payment_intent_created": ["agent_id", "tenant_id", "payment_intent_id", "amount", "currency"],
    "x402_payment_submitted": ["agent_id", "tenant_id", "payment_intent_id"],
    "x402_payment_settled": ["agent_id", "tenant_id", "payment_intent_id", "amount", "currency"],
    "x402_payment_failed": ["agent_id", "tenant_id", "failure_reason"],
    "x402_payment_timeout": ["agent_id", "tenant_id"],
    "x402_receipt_verified": ["agent_id", "tenant_id", "receipt_id", "settlement_event_id"],
    "x402_access_granted": ["agent_id", "tenant_id", "resource_id"],
    "x402_access_denied": ["agent_id", "tenant_id", "resource_id", "failure_reason"],
    "x402_refund_or_reversal": ["agent_id", "tenant_id", "settlement_event_id"],
    "x402_payment": ["agent_id", "tenant_id"],
}

_AGENT_REQUIRED: dict[str, list[str]] = {
    "agent_registered": ["agent_id", "tenant_id", "owner_user_id"],
    "agent_updated": ["agent_id", "tenant_id"],
    "agent_authorized": ["agent_id", "tenant_id", "authorization_id"],
    "agent_deauthorized": ["agent_id", "tenant_id", "authorization_id"],
    "agent_capability_granted": ["agent_id", "tenant_id", "capability"],
    "agent_capability_revoked": ["agent_id", "tenant_id", "capability"],
    "agent_task_created": ["agent_id", "tenant_id", "task_id"],
    "agent_task_decomposed": ["agent_id", "tenant_id", "task_id", "parent_task_id", "subtask_ids"],
    "agent_task_started": ["agent_id", "tenant_id", "task_id"],
    "agent_task_completed": ["agent_id", "tenant_id", "task_id"],
    "agent_task_failed": ["agent_id", "tenant_id", "task_id", "failure_reason"],
    "agent_tool_called": ["agent_id", "tenant_id", "tool_id"],
    "agent_resource_requested": ["agent_id", "tenant_id", "resource_id"],
    "agent_delegated_task": ["agent_id", "tenant_id", "delegation_id", "task_id"],
    "agent_subagent_spawned": ["agent_id", "tenant_id", "parent_agent_id"],
    "agent_policy_evaluated": ["agent_id", "tenant_id", "policy_id", "decision"],
    "agent_handoff": ["agent_id", "tenant_id"],
    "agent_escalated_to_human": ["agent_id", "tenant_id"],
    "agent_outcome_recorded": ["agent_id", "tenant_id", "outcome_id"],
    "agent_task": ["agent_id", "tenant_id"],
    "agent_decision": ["agent_id", "tenant_id"],
    "a2h_interaction": ["agent_id", "tenant_id"],
}

ALL_REQUIRED = {**_X402_REQUIRED, **_AGENT_REQUIRED}


class ValidationError(Exception):
    def __init__(self, event_type: str, missing_fields: list[str]) -> None:
        self.event_type = event_type
        self.missing_fields = missing_fields
        super().__init__(f"Event '{event_type}' missing required fields: {missing_fields}")


def validate_lifecycle_event(event_type: str, payload: dict[str, Any]) -> None:
    """Validate required fields for a lifecycle event. Raises ValidationError if invalid."""
    if event_type not in ALL_LIFECYCLE_EVENTS:
        raise ValidationError(event_type, [f"unknown event type '{event_type}'"])
    required = ALL_REQUIRED.get(event_type, ["agent_id", "tenant_id"])
    missing = [f for f in required if not payload.get(f)]
    if missing:
        raise ValidationError(event_type, missing)
