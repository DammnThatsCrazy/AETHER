"""
Aether — Canonical lifecycle event registry for x402 and agent events.
"""
from __future__ import annotations

# ── x402 Lifecycle Events ─────────────────────────────────────────────────

X402_LIFECYCLE_EVENTS = {
    "x402_resource_requested",
    "x402_payment_required",
    "x402_quote_received",
    "x402_authorization_requested",
    "x402_authorization_resolved",
    "x402_payment_intent_created",
    "x402_payment_submitted",
    "x402_payment_settled",
    "x402_payment_failed",
    "x402_payment_timeout",
    "x402_receipt_verified",
    "x402_access_granted",
    "x402_access_denied",
    "x402_refund_or_reversal",
}

# Legacy shorthands that normalize into the canonical lifecycle
X402_LEGACY_EVENTS = {
    "x402_payment",  # normalizes to x402_payment_settled
}

ALL_X402_EVENTS = X402_LIFECYCLE_EVENTS | X402_LEGACY_EVENTS

# ── Agent Lifecycle Events ────────────────────────────────────────────────

AGENT_LIFECYCLE_EVENTS = {
    "agent_registered",
    "agent_updated",
    "agent_authorized",
    "agent_deauthorized",
    "agent_capability_granted",
    "agent_capability_revoked",
    "agent_task_created",
    "agent_task_decomposed",
    "agent_task_started",
    "agent_task_completed",
    "agent_task_failed",
    "agent_tool_called",
    "agent_resource_requested",
    "agent_delegated_task",
    "agent_subagent_spawned",
    "agent_policy_evaluated",
    "agent_handoff",
    "agent_escalated_to_human",
    "agent_outcome_recorded",
}

# Legacy shorthands
AGENT_LEGACY_EVENTS = {
    "agent_task",       # normalizes based on status field
    "agent_decision",   # normalizes to agent_policy_evaluated or agent_outcome_recorded
    "a2h_interaction",  # normalizes to agent_escalated_to_human or agent_handoff
}

ALL_AGENT_EVENTS = AGENT_LIFECYCLE_EVENTS | AGENT_LEGACY_EVENTS

ALL_LIFECYCLE_EVENTS = ALL_X402_EVENTS | ALL_AGENT_EVENTS

# ── Event Family Mapping ──────────────────────────────────────────────────

EVENT_FAMILY: dict[str, str] = {
    **{e: "x402" for e in ALL_X402_EVENTS},
    **{e: "agent" for e in ALL_AGENT_EVENTS},
}

# ── Consent Mapping ───────────────────────────────────────────────────────

EVENT_CONSENT_PURPOSE: dict[str, str] = {
    **{e: "commerce" for e in ALL_X402_EVENTS},
    **{e: "agent" for e in ALL_AGENT_EVENTS},
}

# ── Legacy Normalization ──────────────────────────────────────────────────

def normalize_legacy_x402_event(event_type: str, payload: dict) -> tuple[str, dict]:
    """Normalize a legacy x402 event to its canonical form."""
    if event_type == "x402_payment":
        return "x402_payment_settled", payload
    return event_type, payload


def normalize_legacy_agent_event(event_type: str, payload: dict) -> tuple[str, dict]:
    """Normalize a legacy agent event to its canonical form."""
    if event_type == "agent_task":
        status = payload.get("status", "")
        if status in ("completed", "success"):
            return "agent_task_completed", payload
        elif status in ("failed", "error"):
            return "agent_task_failed", payload
        else:
            return "agent_task_created", payload
    if event_type == "agent_decision":
        if payload.get("outcome_id") or payload.get("outcome"):
            return "agent_outcome_recorded", payload
        return "agent_policy_evaluated", payload
    if event_type == "a2h_interaction":
        direction = payload.get("direction", "")
        if direction == "human_to_agent":
            return "agent_handoff", payload
        return "agent_escalated_to_human", payload
    return event_type, payload


def normalize_event(event_type: str, payload: dict) -> tuple[str, dict]:
    """Normalize any lifecycle event (x402 or agent) to canonical form."""
    if event_type in X402_LEGACY_EVENTS:
        return normalize_legacy_x402_event(event_type, payload)
    if event_type in AGENT_LEGACY_EVENTS:
        return normalize_legacy_agent_event(event_type, payload)
    return event_type, payload
