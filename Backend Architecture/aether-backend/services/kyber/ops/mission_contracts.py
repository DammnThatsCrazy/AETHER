"""Typed shapes for the Kyber Mission aggregate.

A **mission** is a thin persisted root over work the platform already does. It
does not run anything: the agent runtime executes the objective, the jobs
platform runs the jobs, the verification plane decides pass/fail, and the
containment plane holds the switches. The mission row records *which* of those
each mission is bound to — its objective, the incident it was raised from, the
commands it issued, the plan it follows — and the single decision the platform
must not get wrong: whether the mission may call itself complete.

That decision lives in :class:`VerificationGate`. A mission may only enter
``completed`` when the gate is not required, or when the latest verification
decision is ``passed`` (the vocabulary of
``Agent Layer/models/evidence.py``'s ``VerificationResult.decision`` —
``passed``/``failed``/``needs_review``/``inconclusive``). The backend never
imports the Agent Layer package (see ``services/agent/worker_bridge.py``), so
the decision travels as its string value rather than as the enum, exactly as
the rest of this plane reaches other planes by value rather than by import.

:class:`MissionView` is the read-time composition: the root plus everything a
mission touches, assembled from the existing planes and never dual-written.
Every composed field defaults empty so a view is answerable even when a plane
is unavailable — the same fail-soft discipline the verification plane uses when
it returns ``inconclusive`` rather than raising.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now


def now_iso() -> str:
    return utc_now().isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ── Vocabularies ─────────────────────────────────────────────────────────────


class MissionStatus(str, Enum):
    """The full lifecycle of a mission.

    A ``str`` enum so a value round-trips through JSONB as its own string and
    the migration's ``data->>'status'`` index sees exactly what is stored.
    """

    DETECTED = "detected"
    PROPOSED = "proposed"
    PLANNING = "planning"
    QUEUED = "queued"
    ACTIVE = "active"
    WAITING = "waiting"
    PAUSED = "paused"
    BLOCKED = "blocked"
    VERIFYING = "verifying"
    AWAITING_REVIEW = "awaiting_review"
    COMMITTING = "committing"
    MONITORING = "monitoring"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    CANCELLED = "cancelled"
    EXTERNALLY_BLOCKED = "externally_blocked"
    NOT_IN_RELEASE = "not_in_release"
    DISABLED_INTENTIONALLY = "disabled_intentionally"


#: The verification decisions a mission's gate reads. Mirrors, by value,
#: ``VerificationResult.decision`` in ``Agent Layer/models/evidence.py``. Kept
#: as strings because the backend never imports the Agent Layer package.
VERIFICATION_DECISIONS: frozenset[str] = frozenset(
    {"passed", "failed", "needs_review", "inconclusive"}
)

#: The one decision that opens the completion gate.
VERIFICATION_PASSED = "passed"

#: Lifecycle of a single monitoring condition.
MONITORING_STATUSES: frozenset[str] = frozenset(
    {"pending", "passing", "failing", "escalated", "resolved"}
)

#: Monitoring statuses a due sweep still evaluates. ``escalated`` and
#: ``resolved`` are terminal for a tick — an escalated condition has already
#: raised its signal and must not raise a second one on the next sweep.
MONITORING_ACTIVE_STATUSES: frozenset[str] = frozenset(
    {"pending", "passing", "failing"}
)


# ── Result and gate ──────────────────────────────────────────────────────────


class MissionResult(BaseModel):
    """What a mission produced, by reference — never a copy of the artifacts.

    ``evidence_ids`` and ``verification_id`` point at records the discovery and
    verification planes own. The mission stores the pointers so a view can be
    composed; it does not restate the evidence, because a second copy is a
    second source of truth that can disagree with the first.
    """

    summary: str = ""
    outcome_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    verification_id: Optional[str] = None
    produced_at: str = Field(default_factory=now_iso)


class VerificationGate(BaseModel):
    """Whether completion is gated, and the latest verification decision.

    ``required`` defaults True: a mission that changes durable state must prove
    it worked before it may say so, which is the same reason a command stays
    ``executed_unverified`` until its postconditions are checked. ``decision``
    is ``None`` until a verification runs, and ``None`` reads as "not verified",
    never as "fine".
    """

    required: bool = True
    decision: Optional[str] = None

    @property
    def is_satisfied(self) -> bool:
        """True when the gate permits completion.

        Either completion is not gated, or the latest decision is ``passed``.
        Any other decision — ``failed``, ``needs_review``, ``inconclusive`` or
        ``None`` — leaves the gate closed.
        """
        return (not self.required) or self.decision == VERIFICATION_PASSED


# ── Root ─────────────────────────────────────────────────────────────────────


class Mission(BaseModel):
    """The thin persisted root. One row per objective (unique on objective_id).

    It names the planes the mission is bound to and carries the completion gate;
    it does not carry the objective's plan, the jobs' state or the evidence
    itself — those are composed at read time in :class:`MissionView`.
    """

    mission_id: str = Field(default_factory=lambda: _id("kms"))
    tenant_id: str
    title: str
    status: MissionStatus = MissionStatus.DETECTED
    objective_id: str
    incident_id: Optional[str] = None
    command_ids: list[str] = Field(default_factory=list)
    plan_id: str = ""
    result: Optional[MissionResult] = None
    verification_gate: VerificationGate = Field(default_factory=VerificationGate)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MonitoringCondition(BaseModel):
    """A recurring check a live mission schedules against the world.

    ``expected_state`` is what the mission asserts should hold; the monitoring
    sweep re-reads live state and compares. ``failure_count`` and
    ``escalation_policy`` together decide when a persistent divergence stops
    being a transient blip and becomes an operator signal.
    """

    condition_id: str = Field(default_factory=lambda: _id("kmc"))
    mission_id: str
    tenant_id: str
    condition_type: str
    expected_state: Any = None
    window: Any = None
    status: str = "pending"
    last_checked_at: Optional[str] = None
    failure_count: int = 0
    next_check_at: Optional[str] = None
    escalation_policy: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Read-time composition ────────────────────────────────────────────────────


class MissionView(BaseModel):
    """The mission root plus everything it touches, composed at read time.

    Never persisted and never dual-written: each field is read from the plane
    that owns it when the view is built. Every composed field defaults empty so
    a partial platform still answers — an absent plane contributes nothing
    rather than failing the whole read.
    """

    mission: Mission
    objective: Optional[dict[str, Any]] = None
    plan: Optional[dict[str, Any]] = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    worker_runs: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[Any] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    monitoring_conditions: list[MonitoringCondition] = Field(default_factory=list)
    timeline: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "MONITORING_ACTIVE_STATUSES",
    "MONITORING_STATUSES",
    "VERIFICATION_DECISIONS",
    "VERIFICATION_PASSED",
    "Mission",
    "MissionResult",
    "MissionStatus",
    "MissionView",
    "MonitoringCondition",
    "VerificationGate",
    "now_iso",
]
