"""
Aether Economic Event Topics — Agentic Commerce Control Plane (L3b+).

All topics follow the `aether.<domain>.<entity>.<action>` convention.
These are re-exported from the main EventTopic enum for backwards compatibility.
"""

from __future__ import annotations

from shared.events.events import EventTopic

# ── Challenge & Requirement ────────────────────────────────────────────────────

CHALLENGE_ISSUED = EventTopic.COMMERCE_CHALLENGE_ISSUED
REQUIREMENT_GENERATED = EventTopic.COMMERCE_REQUIREMENT_GENERATED

# ── Approval Lifecycle ─────────────────────────────────────────────────────────

APPROVAL_REQUESTED = EventTopic.COMMERCE_APPROVAL_REQUESTED
APPROVAL_ASSIGNED = EventTopic.COMMERCE_APPROVAL_ASSIGNED
APPROVAL_APPROVED = EventTopic.COMMERCE_APPROVAL_APPROVED
APPROVAL_REJECTED = EventTopic.COMMERCE_APPROVAL_REJECTED
APPROVAL_ESCALATED = EventTopic.COMMERCE_APPROVAL_ESCALATED
APPROVAL_EXPIRED = EventTopic.COMMERCE_APPROVAL_EXPIRED
APPROVAL_REVOKED = EventTopic.COMMERCE_APPROVAL_REVOKED

# ── Payment & Verification ─────────────────────────────────────────────────────

PAYMENT_SUBMITTED = EventTopic.COMMERCE_PAYMENT_SUBMITTED
VERIFICATION_STARTED = EventTopic.COMMERCE_VERIFICATION_STARTED
VERIFICATION_SUCCEEDED = EventTopic.COMMERCE_VERIFICATION_SUCCEEDED
VERIFICATION_FAILED = EventTopic.COMMERCE_VERIFICATION_FAILED

# ── Settlement ─────────────────────────────────────────────────────────────────

SETTLEMENT_STARTED = EventTopic.COMMERCE_SETTLEMENT_STARTED
SETTLEMENT_PENDING = EventTopic.COMMERCE_SETTLEMENT_PENDING
SETTLEMENT_COMPLETED = EventTopic.COMMERCE_SETTLEMENT_COMPLETED
SETTLEMENT_FAILED = EventTopic.COMMERCE_SETTLEMENT_FAILED

# ── Entitlement ────────────────────────────────────────────────────────────────

ENTITLEMENT_GRANTED = EventTopic.COMMERCE_ENTITLEMENT_GRANTED
ENTITLEMENT_REUSED = EventTopic.COMMERCE_ENTITLEMENT_REUSED
ENTITLEMENT_REVOKED = EventTopic.COMMERCE_ENTITLEMENT_REVOKED
ENTITLEMENT_EXPIRED = EventTopic.COMMERCE_ENTITLEMENT_EXPIRED

# ── Access ─────────────────────────────────────────────────────────────────────

ACCESS_GRANTED = EventTopic.COMMERCE_ACCESS_GRANTED
ACCESS_DENIED = EventTopic.COMMERCE_ACCESS_DENIED

# ── Policy ─────────────────────────────────────────────────────────────────────

POLICY_DENIED = EventTopic.COMMERCE_POLICY_DENIED

# ── Facilitator ────────────────────────────────────────────────────────────────

FACILITATOR_ROUTE_SELECTED = EventTopic.COMMERCE_FACILITATOR_ROUTE_SELECTED

# ── Audit & Operator ──────────────────────────────────────────────────────────

KYBER_ACTION_LOGGED = EventTopic.COMMERCE_KYBER_ACTION_LOGGED
OPERATOR_ACTION_LOGGED = EventTopic.COMMERCE_OPERATOR_ACTION_LOGGED
REPLAY_EXECUTED = EventTopic.COMMERCE_REPLAY_EXECUTED

# ── Reconciliation ─────────────────────────────────────────────────────────────

RECONCILIATION_TASK_CREATED = EventTopic.COMMERCE_RECONCILIATION_TASK_CREATED
RECONCILIATION_TASK_RESOLVED = EventTopic.COMMERCE_RECONCILIATION_TASK_RESOLVED

# ── All commerce topics (for consumer routing tables) ─────────────────────────

ALL_COMMERCE_TOPICS: frozenset[EventTopic] = frozenset({
    CHALLENGE_ISSUED,
    REQUIREMENT_GENERATED,
    APPROVAL_REQUESTED,
    APPROVAL_ASSIGNED,
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
    APPROVAL_ESCALATED,
    APPROVAL_EXPIRED,
    APPROVAL_REVOKED,
    PAYMENT_SUBMITTED,
    VERIFICATION_STARTED,
    VERIFICATION_SUCCEEDED,
    VERIFICATION_FAILED,
    SETTLEMENT_STARTED,
    SETTLEMENT_PENDING,
    SETTLEMENT_COMPLETED,
    SETTLEMENT_FAILED,
    ENTITLEMENT_GRANTED,
    ENTITLEMENT_REUSED,
    ENTITLEMENT_REVOKED,
    ENTITLEMENT_EXPIRED,
    ACCESS_GRANTED,
    ACCESS_DENIED,
    POLICY_DENIED,
    FACILITATOR_ROUTE_SELECTED,
    KYBER_ACTION_LOGGED,
    OPERATOR_ACTION_LOGGED,
    REPLAY_EXECUTED,
    RECONCILIATION_TASK_CREATED,
    RECONCILIATION_TASK_RESOLVED,
})
