"""Kyber operations — exceptions, incidents, and the governed command plane.

Three ideas, in dependency order.

**Exceptions** are the prioritised queue a single operator reads instead of
watching dashboards. An exception is not an alert: many alerts collapse into one
exception, and an exception carries what it would cost to ignore.

**Incidents** correlate signals that share a root cause. One bad deploy produces
failed events, connector warnings, graph drift and tenant reports; treating those
as four problems is how a small team drowns.

**Commands** are the only sanctioned way to change platform state from Kyber.
Every command is typed, capability-gated, blast-radius-assessed, idempotent, and
— critically — **unverified until its postconditions are checked**. An HTTP 200
is not success; ``executed_unverified`` is a real, visible state.

Nothing here replaces the existing operational services. A command wraps
``services/jobs``, the agent runtime, connector pause and so on; it does not
reimplement them. The value added is uniform authority, evidence and
verification over actions that today each carry their own ad-hoc handling — and
several of which write no audit record at all.
"""
from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now

# ── Vocabularies ─────────────────────────────────────────────────────────────

Severity = Literal["critical", "high", "medium", "low", "info"]

#: What the operator should do with it, not how bad it looks.
ExceptionBucket = Literal["critical_now", "needs_action", "watch", "informational"]

ExceptionStatus = Literal["open", "acknowledged", "in_progress", "resolved", "suppressed"]

IncidentStatus = Literal[
    "detected", "investigating", "identified", "mitigating", "monitoring",
    "resolved", "closed",
]

#: Reuses the capability plane's action classes verbatim (0 read … 5 fleet
#: destructive) so a command's risk and its capability cannot disagree.
CommandStatus = Literal[
    "requested", "awaiting_approval", "approved", "rejected", "dry_run_complete",
    "executing", "executed_unverified", "verified", "failed", "rolled_back",
    "cancelled", "expired",
]

VerificationOutcome = Literal["passed", "failed", "inconclusive", "not_run"]

ApprovalMode = Literal["solo", "small_team"]

ContainmentScope = Literal[
    "global", "environment", "region", "tenant", "feature", "connector",
    "worker", "model",
]


def now_iso() -> str:
    return utc_now().isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ── Exceptions ───────────────────────────────────────────────────────────────

class OperationalException(BaseModel):
    """One thing that needs a decision, with the cost of ignoring it.

    Priority is computed from the exposure fields rather than set by hand, and
    the inputs are stored alongside the result so a ranking can be explained
    after the fact. A potential cross-tenant leak must outrank a large volume of
    low-risk warnings, and that ordering has to be derivable, not asserted.
    """

    exception_id: str = Field(default_factory=lambda: _id("kex"))
    title: str
    severity: Severity = "medium"
    bucket: ExceptionBucket = "watch"
    status: ExceptionStatus = "open"
    confidence: float = 0.5
    #: Exposure inputs — these drive `priority_score`.
    affected_tenants: list[str] = Field(default_factory=list)
    affected_features: list[str] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    customer_visible: bool = False
    security_exposure: bool = False
    financial_exposure: bool = False
    data_integrity_exposure: bool = False
    reversible: bool = True
    time_to_breach_seconds: Optional[int] = None
    sla_impact: bool = False
    #: Computed, with its inputs retained for explainability.
    priority_score: float = 0.0
    priority_inputs: dict[str, Any] = Field(default_factory=dict)
    probable_cause: Optional[str] = None
    recommended_action: Optional[str] = None
    incident_id: Optional[str] = None
    dedupe_key: Optional[str] = None
    signal_count: int = 1
    first_seen_at: str = Field(default_factory=now_iso)
    last_seen_at: str = Field(default_factory=now_iso)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Incidents ────────────────────────────────────────────────────────────────

class IncidentSignal(BaseModel):
    """One observation attributed to an incident.

    ``correlation_basis`` and ``correlation_confidence`` record *why* the signal
    was attached. Deterministic bases (same deployment, same idempotency key) are
    distinguished from heuristic ones (time proximity, error-signature
    similarity) so a wrong correlation is auditable rather than mysterious.
    """

    signal_id: str = Field(default_factory=lambda: _id("kis"))
    incident_id: Optional[str] = None
    tenant_id: Optional[str] = None
    source: str
    signal_type: str
    error_signature: Optional[str] = None
    service: Optional[str] = None
    feature: Optional[str] = None
    release_id: Optional[str] = None
    correlation_basis: Optional[str] = None
    correlation_confidence: float = 0.0
    observed_at: str = Field(default_factory=now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    """A correlated failure with an owner-visible next action."""

    incident_id: str = Field(default_factory=lambda: _id("kin"))
    title: str
    status: IncidentStatus = "detected"
    severity: Severity = "medium"
    priority_score: float = 0.0
    root_cause: Optional[str] = None
    affected_tenants: list[str] = Field(default_factory=list)
    affected_features: list[str] = Field(default_factory=list)
    affected_services: list[str] = Field(default_factory=list)
    release_id: Optional[str] = None
    customer_visible: bool = False
    revenue_exposure: bool = False
    security_exposure: bool = False
    data_integrity_exposure: bool = False
    #: Interruption recovery: what a returning operator needs to resume.
    last_action: Optional[str] = None
    next_action: Optional[str] = None
    blocked_by: Optional[str] = None
    pending_verification: list[str] = Field(default_factory=list)
    operator_notes: list[dict[str, Any]] = Field(default_factory=list)
    signal_count: int = 0
    opened_at: str = Field(default_factory=now_iso)
    resolved_at: Optional[str] = None
    closed_at: Optional[str] = None
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Commands ─────────────────────────────────────────────────────────────────

class CommandSpec(BaseModel):
    """A registered command type. Declaration, not an instance.

    ``handler`` names an existing operational service call. A command is a
    governed wrapper — capability, approval, blast radius, verification — over
    work the platform already knows how to do.
    """

    command_type: str
    title: str
    capability_id: str
    action_class: int
    handler: str
    #: Postconditions the verifier checks. A command with none cannot be
    #: registered: unverifiable state change is what this plane exists to stop.
    verification_checks: tuple[str, ...] = ()
    requires_dry_run: bool = False
    requires_rollback_plan: bool = False
    tenant_scoped: bool = True
    containment_scope: Optional[ContainmentScope] = None
    description: str = ""


class CommandRequest(BaseModel):
    """One intent to change state, with everything needed to judge it."""

    command_id: str = Field(default_factory=lambda: _id("kcm"))
    command_type: str
    status: CommandStatus = "requested"
    requested_by: str
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    environment: str = "local"
    tenant_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    reason: str
    action_class: int = 0
    dry_run: bool = False
    #: Same key + same command type must never execute twice.
    idempotency_key: str
    blast_radius: Optional[dict[str, Any]] = None
    rollback_plan: Optional[str] = None
    verification_plan: list[str] = Field(default_factory=list)
    required_approvals: int = 0
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    approval_mode: ApprovalMode = "solo"
    step_up_verified: bool = False
    policy_decision_id: Optional[str] = None
    incident_id: Optional[str] = None
    scheduled_for: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommandExecution(BaseModel):
    """What actually happened. Distinct from whether it worked."""

    execution_id: str = Field(default_factory=lambda: _id("kce"))
    command_id: str
    attempt: int = 1
    started_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    side_effects: list[str] = Field(default_factory=list)
    rollback_status: Optional[str] = None


class CommandVerification(BaseModel):
    """Whether the intended state was actually reached.

    A command stays ``executed_unverified`` until this passes. That state is not
    bookkeeping — it is the honest answer between "the call returned" and "the
    system is in the state we wanted", and those are different questions.
    """

    verification_id: str = Field(default_factory=lambda: _id("kcv"))
    command_id: str
    outcome: VerificationOutcome = "not_run"
    checks: list[dict[str, Any]] = Field(default_factory=list)
    customer_visible_parity: Optional[bool] = None
    #: Present when a Tenant Mirror digest was compared before and after.
    mirror_digest_before: Optional[str] = None
    mirror_digest_after: Optional[str] = None
    failure_reason: Optional[str] = None
    started_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None


class ContainmentSwitch(BaseModel):
    """A scoped pause. Safe mode is the platform-wide case of this."""

    switch_id: str = Field(default_factory=lambda: _id("ksw"))
    scope: ContainmentScope
    target: Optional[str] = None
    control: str
    active: bool = False
    reason: Optional[str] = None
    activated_by: Optional[str] = None
    activated_at: Optional[str] = None
    deactivated_by: Optional[str] = None
    deactivated_at: Optional[str] = None
    blast_radius: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "ApprovalMode",
    "CommandExecution",
    "CommandRequest",
    "CommandSpec",
    "CommandStatus",
    "CommandVerification",
    "ContainmentScope",
    "ContainmentSwitch",
    "ExceptionBucket",
    "ExceptionStatus",
    "Incident",
    "IncidentSignal",
    "IncidentStatus",
    "OperationalException",
    "Severity",
    "VerificationOutcome",
    "now_iso",
]
