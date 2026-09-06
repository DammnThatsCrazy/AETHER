"""Fraud360 domain contracts — the fraud-synthesis vocabulary (Phase 3).

Fraud360 is a **domain-synthesis** intelligence projection over canonical
Aether truth. These are the typed shapes the hypothesis layer uses to describe
suspected deceptive/abusive mechanisms and to record how strongly the evidence
supports them — NEVER a competing fraud graph, identity model, evidence model,
or decision system (ADR-010: ``ownsCanonicalTruth: false``, read_only).

Non-negotiable invariants:

* **No re-declared primitives.** ``EvidenceRef`` / ``GraphSnapshotRef`` are the
  canonical operational-intelligence types
  (``services/operational_intelligence/models.py``); ``MonetaryAmount`` is the
  canonical economic type
  (``services/economic/economic360_contracts.py``); ``EpistemicStatus`` is the
  consolidated epistemic vocabulary
  (``shared/contracts_models/epistemic.py``). This module declares no second
  copy of any of them (parity-tested by ``tests/unit/test_fraud360_contracts.py``).
* **No-silent-escalation.** A ``derived``/``inferred``/``predicted``/
  ``correlated`` suspicion is a *hypothesis*; it never renders as a factual
  declaration. ``confirmed`` is reachable only through the state machine with a
  factual ``claim_state`` (``observed``/``verified``/``causally_supported``);
  ``rejected`` requires an evidence-grounded basis.
* **Contradictions are first-class.** Contradictory evidence is surfaced on the
  hypothesis (``contradictory_evidence_refs``), never hidden.
* **Fails closed.** Every contract is a plain pydantic domain model with
  ``extra="forbid"`` (NOT ``ContractModel``, whose ``extra="allow"`` is for
  shared API mirrors): a misspelled field raises instead of silently passing.
"""

from __future__ import annotations

from enum import Enum
from typing import Final, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Reused canonical primitives (single-monolith reuse — never re-declared here).
from services.economic.economic360_contracts import MonetaryAmount
from services.operational_intelligence.models import EvidenceRef, GraphSnapshotRef
from shared.computation.runtime import new_run_id
from shared.contracts_models.epistemic import EpistemicStatus

# ── Epistemic banding (single authority for the no-silent-escalation rule) ───
#
# ``confirmed`` is a factual declaration of fraud. Only an evidence-grounded,
# factual claim state may grant it. ``observed`` / ``verified`` /
# ``causally_supported`` are the direct/factual members of the consolidated
# EpistemicStatus vocabulary that warrant confirmation; the suspicion band
# (``derived`` / ``inferred`` / ``predicted`` / ``correlated`` / ``attributed``)
# can never silently escalate to ``confirmed``.

CONFIRMED_FACTUAL_CLAIM_STATES: Final[frozenset[EpistemicStatus]] = frozenset(
    {
        EpistemicStatus.OBSERVED,
        EpistemicStatus.VERIFIED,
        EpistemicStatus.CAUSALLY_SUPPORTED,
    }
)

SUSPICION_CLAIM_STATES: Final[frozenset[EpistemicStatus]] = frozenset(
    {
        EpistemicStatus.DERIVED,
        EpistemicStatus.INFERRED,
        EpistemicStatus.PREDICTED,
        EpistemicStatus.CORRELATED,
        EpistemicStatus.ATTRIBUTED,
    }
)


def is_factual_claim(status: EpistemicStatus | str) -> bool:
    """True when ``status`` sits in the direct/factual epistemic band."""
    return EpistemicStatus(status) in CONFIRMED_FACTUAL_CLAIM_STATES


def is_suspicion_claim(status: EpistemicStatus | str) -> bool:
    """True when ``status`` sits in the suspicion/derivative band."""
    return EpistemicStatus(status) in SUSPICION_CLAIM_STATES


class FraudPattern(BaseModel):
    """A registered pattern *condition* — NOT a taxonomy and NOT proof of fraud.

    A ``FraudPattern`` describes observable facts that, when they co-occur, are
    consistent with a deceptive/abusive *mechanism*. Matching a pattern only
    produces a ``FraudHypothesis`` in a suspicion state; it is never itself a
    finding that fraud occurred (pattern conditions are suspicion).

    ``network_type_refs`` / ``member_role_refs`` ALIGN to the shipped network
    taxonomy (``services/fraud_networks/models.py`` ``NetworkType`` /
    ``MemberRole``) — alignment is asserted by the registry test
    (``tests/unit/test_fraud360_patterns.py``), never re-declared here.
    Tenant-defined extensions register through the same declarative registry.
    """

    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    family: str
    display_name: str
    description: str
    network_type_refs: list[str] = Field(default_factory=list)
    member_role_refs: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    materiality_guidance: Optional[str] = None
    enabled: bool = True


class FraudHypothesisState(str, Enum):
    """Lifecycle state of a ``FraudHypothesis``.

    Backbone flow (canonical object model + blueprint):
    ``candidate → under_evaluation → supported → material → investigating →
    confirmed | rejected | inconclusive → closed``, plus the legal extras
    ``superseded`` / ``disputed`` / ``stale`` / ``corrected`` reachable from
    most states. Legal transitions are encoded in
    :attr:`FraudHypothesisStateMachine.ALLOWED_TRANSITIONS`.
    """

    CANDIDATE = "candidate"
    UNDER_EVALUATION = "under_evaluation"
    SUPPORTED = "supported"
    MATERIAL = "material"
    INVESTIGATING = "investigating"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    CLOSED = "closed"
    SUPERSEDED = "superseded"
    DISPUTED = "disputed"
    STALE = "stale"
    CORRECTED = "corrected"


class FraudHypothesisStateError(ValueError):
    """Base class for an illegal FraudHypothesis state transition."""


class IllegalTransitionError(FraudHypothesisStateError):
    """The requested transition is not in the allowed-transition graph."""


class ConfirmationRequiresFactualClaimError(FraudHypothesisStateError):
    """``confirmed`` was requested under a suspicion (non-factual) claim state."""


class RejectionRequiresEvidenceError(FraudHypothesisStateError):
    """``rejected`` was requested without an evidence-grounded basis."""


def _build_allowed_transitions() -> dict[FraudHypothesisState, frozenset[FraudHypothesisState]]:
    """Build the transition graph documented on the state machine below."""
    _ = FraudHypothesisState
    _FUNNEL = frozenset(
        {
            _.CANDIDATE,
            _.UNDER_EVALUATION,
            _.SUPPORTED,
            _.MATERIAL,
            _.INVESTIGATING,
        }
    )
    _OUTCOME = frozenset({_.CONFIRMED, _.REJECTED, _.INCONCLUSIVE})
    _META = frozenset({_.SUPERSEDED, _.DISPUTED, _.STALE, _.CORRECTED})

    graph: dict[FraudHypothesisState, set[FraudHypothesisState]] = {
        # Backbone funnel.
        _.CANDIDATE: {_.UNDER_EVALUATION},
        _.UNDER_EVALUATION: {_.SUPPORTED, _.REJECTED, _.INCONCLUSIVE},
        _.SUPPORTED: {_.MATERIAL, _.REJECTED, _.INCONCLUSIVE},
        _.MATERIAL: {_.INVESTIGATING, _.REJECTED, _.INCONCLUSIVE},
        _.INVESTIGATING: {_.CONFIRMED, _.REJECTED, _.INCONCLUSIVE},
        _.CONFIRMED: {_.CLOSED},
        _.REJECTED: {_.CLOSED},
        _.INCONCLUSIVE: {_.CLOSED, _.UNDER_EVALUATION},  # new evidence reopens the funnel
        _.CLOSED: set(),
    }

    # Legal extras (superseded/disputed/stale/corrected) reachable from the
    # open states — a record is closed out only once its conclusion holds.
    for state in _FUNNEL | _OUTCOME:
        graph[state] |= _META

    # Meta-state exits keep the lifecycle usable without a silent escalation.
    graph[_.SUPERSEDED] = {_.CLOSED, _.DISPUTED}
    graph[_.DISPUTED] = {_.UNDER_EVALUATION, _.SUPERSEDED, _.CLOSED}
    graph[_.STALE] = {_.UNDER_EVALUATION, _.SUPERSEDED, _.CLOSED}
    graph[_.CORRECTED] = {
        _.UNDER_EVALUATION,
        _.SUPPORTED,
        _.MATERIAL,
        _.INVESTIGATING,
        _.CONFIRMED,
        _.REJECTED,
        _.INCONCLUSIVE,
        _.CLOSED,
    }

    return {s: frozenset(targets) for s, targets in graph.items()}


class FraudHypothesisStateMachine:
    """Encodes the legal ``FraudHypothesis`` transitions (no-silent-escalation).

    Two rules are enforced at the machine boundary so no caller — provider,
    service, UI, or Noesis — can silently strengthen a claim:

    * **Confirmation requires fact.** Reaching ``confirmed`` requires an
      explicit ``claim_state`` in the factual band
      (:data:`CONFIRMED_FACTUAL_CLAIM_STATES` —
      ``observed``/``verified``/``causally_supported``). A ``derived`` /
      ``inferred`` / ``predicted`` / ``correlated`` / ``attributed`` suspicion
      is rejected for ``confirmed`` even when evidence refs are supplied.
    * **Rejection requires evidence.** ``rejected`` is a grounded negative — it
      needs ``evidence_refs``. ``superseded``/``disputed``/``stale``/
      ``corrected`` are reachable from most states.
    """

    ALLOWED_TRANSITIONS: Final[
        dict[FraudHypothesisState, frozenset[FraudHypothesisState]]
    ] = _build_allowed_transitions()

    @classmethod
    def is_allowed(
        cls, current: FraudHypothesisState | str, target: FraudHypothesisState | str
    ) -> bool:
        """Structural check: is the edge present in the transition graph?"""
        return FraudHypothesisState(target) in cls.ALLOWED_TRANSITIONS[
            FraudHypothesisState(current)
        ]

    @classmethod
    def transition(
        cls,
        current: FraudHypothesisState | str,
        target: FraudHypothesisState | str,
        *,
        evidence_refs: Optional[list] = None,
        claim_state: Optional[EpistemicStatus | str] = None,
    ) -> FraudHypothesisState:
        """Return ``target`` when the transition is legal, else raise.

        Validates the structural edge AND the no-silent-escalation rules:
        ``confirmed`` requires a factual ``claim_state``; ``rejected`` requires
        an evidence-grounded basis (``evidence_refs``).
        """
        current_s = FraudHypothesisState(current)
        target_s = FraudHypothesisState(target)

        if target_s not in cls.ALLOWED_TRANSITIONS[current_s]:
            raise IllegalTransitionError(
                f"Illegal FraudHypothesis transition: {current_s.value} → {target_s.value}"
            )

        if target_s is FraudHypothesisState.CONFIRMED:
            cs = EpistemicStatus(claim_state) if claim_state is not None else None
            if cs is None or cs not in CONFIRMED_FACTUAL_CLAIM_STATES:
                band = ", ".join(sorted(s.value for s in CONFIRMED_FACTUAL_CLAIM_STATES))
                raise ConfirmationRequiresFactualClaimError(
                    "FraudHypothesis cannot reach 'confirmed' under "
                    f"claim_state={cs.value if cs else None!r}; a factual claim state "
                    f"({band}) is required (no-silent-escalation)."
                )

        if target_s is FraudHypothesisState.REJECTED and not evidence_refs:
            raise RejectionRequiresEvidenceError(
                "FraudHypothesis cannot reach 'rejected' without an "
                "evidence-grounded basis (evidence_refs)."
            )

        return target_s


class FraudHypothesis(BaseModel):
    """A suspected deceptive/abusive mechanism, tracked from suspicion to fact.

    Fraud is represented as a hypothesis until the required evidence state
    supports it. ``state`` names where the record stands in the lifecycle;
    ``claim_state`` carries the consolidated ``EpistemicStatus`` so a UI can
    never render a ``derived``/``inferred`` suspicion as ``confirmed``.
    Reaching ``confirmed`` requires a factual claim state and an explicit
    evidence-grounded upgrade through :class:`FraudHypothesisStateMachine`.

    Contradictions and missing evidence are first-class
    (``contradictory_evidence_refs``), never hidden. The hypothesis is pinned
    to the graph snapshot it was synthesized against (``snapshot``) and may
    carry a ``run_id`` on the canonical ``computation_runs`` substrate.
    """

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str
    tenant_id: str
    subject_kind: Literal["entity", "relationship", "agent"]
    subject_id: str
    state: FraudHypothesisState = FraudHypothesisState.CANDIDATE
    claim_state: EpistemicStatus = EpistemicStatus.DERIVED
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    matched_pattern_ids: list[str] = Field(default_factory=list)
    materiality: Optional[float] = Field(default=None, ge=0, le=1)
    # Economic exposure via the canonical monetary contract — never re-declared.
    exposure: Optional[MonetaryAmount] = None
    # Canonical evidence refs — supporting AND contradictory (both first-class).
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    contradictory_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    # Backing authorities this hypothesis was synthesized from (by id).
    risk_assessment_ids: list[str] = Field(default_factory=list)
    network_ids: list[str] = Field(default_factory=list)
    flow_trace_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    snapshot: Optional[GraphSnapshotRef] = None
    run_id: Optional[str] = None
    supersedes_hypothesis_id: Optional[str] = None
    superseded_by_hypothesis_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @model_validator(mode="after")
    def _no_confirmed_under_suspicion_claim(self) -> "FraudHypothesis":
        # Belt-and-suspenders: even a hand-constructed record may never present
        # a confirmed hypothesis under a suspicion claim state. The state
        # machine enforces the same rule at transition time.
        if (
            self.state is FraudHypothesisState.CONFIRMED
            and self.claim_state not in CONFIRMED_FACTUAL_CLAIM_STATES
        ):
            raise ValueError(
                "A confirmed FraudHypothesis requires a factual claim_state "
                f"({sorted(s.value for s in CONFIRMED_FACTUAL_CLAIM_STATES)}); "
                f"got {self.claim_state.value!r} — no-silent-escalation."
            )
        return self


class FraudHypothesisRun(BaseModel):
    """Reproducibility ref over the canonical ``computation_runs`` substrate.

    A synthesis run is recorded on the computation plane — identified by
    ``new_run_id()`` with a ``context_hash`` from
    ``ComputationContext.context_hash()`` — NOT on a parallel fraud run table.
    This contract carries the identity a caller stores there; a
    ``FraudHypothesis`` may pin the ``run_id`` it was produced by.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=new_run_id)
    tenant_id: str
    context_hash: Optional[str] = None
    definition_id: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    hypothesis_count: Optional[int] = None


__all__ = [
    "CONFIRMED_FACTUAL_CLAIM_STATES",
    "SUSPICION_CLAIM_STATES",
    "ConfirmationRequiresFactualClaimError",
    "FraudHypothesis",
    "FraudHypothesisRun",
    "FraudHypothesisState",
    "FraudHypothesisStateError",
    "FraudHypothesisStateMachine",
    "FraudPattern",
    "IllegalTransitionError",
    "RejectionRequiresEvidenceError",
    "is_factual_claim",
    "is_suspicion_claim",
]
