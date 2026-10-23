"""Risk360 canonical domain contracts (Phase 3).

Hand-authored domain vocabulary for the Risk360 intelligence projection. All
models inherit :class:`RiskContract` (``extra="forbid"``) so a misspelled field
raises instead of silently passing — mirroring the projection-plane and
economic-domain contract discipline (``ProjectionContract``,
``EconomicContract``), NOT ``ContractModel`` which is ``extra="allow"``.

Reuse, never redefine: every canonical primitive below is imported from its
canonical home and declared **no second copy** of any of them here:

* ``EntityRef`` / ``EvidenceRef`` / ``GraphSnapshotRef`` ←
  ``services/api/graph/operational_intelligence/models.py``
* ``EpistemicStatus`` ← ``shared/contracts_models/epistemic.py``
* ``ValueState`` ← ``shared/measurement/value_states.py``
* ``MonetaryAmount`` ← ``services/api/value/economic/economic360_contracts.py``
* ``new_run_id`` / ``ComputationContext`` ← ``shared/computation/runtime.py`` /
  ``shared/computation/context.py`` (for :class:`RiskAssessmentRun`)

Epistemic honesty (no-silent-escalation): every contract carries a
``claim_state: EpistemicStatus`` and reused ``EvidenceRef``s. A ``derived`` /
``inferred`` / ``correlated`` risk condition can never render as a factual
declaration without an evidence-grounded upgrade. A :class:`RiskVector`
represents an absent dimension as an honest non-value-bearing state — never a
fabricated zero (see :class:`RiskComponent` / :class:`RiskVector`).

Naming convention: Python models use snake_case field names on the wire (the
operational-intelligence TS twins use camelCase; comparison-workbench models
use snake_case — these domain contracts follow the snake_case convention used
by the sibling comparison domain set and the canonical
``operational_intelligence.models`` snake_case fields such as
``graph_snapshot_id``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Reused canonical primitives — never re-declared (identity-parity tested).
from graph.operational_intelligence.models import (  # noqa: F401  (re-exported)
    EntityRef,
    EvidenceRef,
    GraphSnapshotRef,
)

# Canonical epistemic vocabulary (Phase 2 consolidation).
from shared.contracts_models.epistemic import EpistemicStatus

# Canonical value-state authority for the measurement integrity plane.
from shared.measurement.value_states import ValueState, requires_value

# Canonical economic amount for exposure "economic value".
from value.economic.economic360_contracts import MonetaryAmount

# Runs substrate: reproducibility over ``computation_runs``.
from shared.computation.context import ComputationContext
from shared.computation.runtime import new_run_id

from .dimensions import RISK_DIMENSION_KEYS


class RiskContract(BaseModel):
    """Risk360-domain contract base — fails closed on unknown fields."""

    model_config = ConfigDict(extra="forbid")


class RiskSignal(RiskContract):
    """An atomic risk-relevant observation or derived condition about a subject.

    A ``RiskSignal`` is **not itself a finding and not a fraud assertion**: it is
    atomic input to an assessment. Materiality and aggregation happen later; a
    signal becomes a finding candidate only through the Risk360 pipeline. It
    always names the subject it concerns (``subject_kind`` / ``subject_id``),
    the risk ``risk_dimension`` it feeds (a member of ``RISK_DIMENSION_KEYS``),
    its epistemic ``claim_state`` (so a detector's ``derived``/``inferred``
    condition can never silently render as fact), a confidence, reused
    ``evidence_refs``, and the detector/source that produced it.
    """

    signal_id: str
    tenant_id: str
    subject_kind: str
    subject_id: str
    #: Canonical risk dimension key (see intelligence.risk360.dimensions).
    risk_dimension: str
    claim_state: EpistemicStatus = EpistemicStatus.UNKNOWN
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    #: Detector/service that produced the signal (e.g. ``fraud.signals``).
    source: str
    detector_version: Optional[str] = None
    observed_at: Optional[datetime] = None
    #: Optional 0–1 likelihood/severity score the detector attached.
    score: Optional[float] = Field(default=None, ge=0, le=1)
    #: Optional raw magnitude carried by the signal (never a fabricated figure).
    value: Optional[float] = None

    @model_validator(mode="after")
    def _dimension_is_registered(self) -> "RiskSignal":
        if self.risk_dimension not in RISK_DIMENSION_KEYS:
            raise ValueError(
                f"risk_dimension {self.risk_dimension!r} is not a registered Risk360 dimension"
            )
        return self


PoisoningType = Literal[
    "schema_drift",
    "volume_spike",
    "identity_collision",
    "attribution_manipulation",
    "campaign_spoofing",
    "agent_trace_tampering",
    "communication_injection",
    "value_distortion",
    "relationship_graph_manipulation",
]
PoisoningEvidenceStatus = Literal[
    "open", "acknowledged", "resolved", "dismissed", "superseded"
]


class RiskPoisoningLifecycleEvent(RiskContract):
    """Auditable status or restatement transition for poisoning evidence."""

    event_id: str
    from_status: PoisoningEvidenceStatus
    to_status: PoisoningEvidenceStatus
    occurred_at: datetime
    actor_id: str
    reason: Optional[str] = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _lifecycle_event_is_scoped(self) -> "RiskPoisoningLifecycleEvent":
        if not self.event_id.strip() or not self.actor_id.strip():
            raise ValueError("poisoning lifecycle event id and actor must not be empty")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("poisoning lifecycle timestamps must include a timezone")
        return self


class RiskPoisoningEvidence(RiskContract):
    """Canonical detector evidence for source poisoning or manipulation.

    This is a risk-domain record, not a Risk360 projection snapshot. A detector
    must persist both the exact tenant source and exact subject it evaluated;
    readers never infer either binding from a graph neighbor or a payload.
    Evidence and lifecycle revisions remain attributable through the canonical
    ``EvidenceRef`` primitive and explicit supersession links.
    """

    evidence_id: str
    tenant_id: str
    source_id: str
    subject_kind: str
    subject_id: str
    poisoning_type: PoisoningType
    signal_strength: float = Field(ge=0, le=1)
    confidence: Literal["low", "medium", "high", "verified"]
    claim_state: EpistemicStatus = EpistemicStatus.INFERRED
    detector_id: str
    detector_version: str
    source_record_id: str
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    first_seen_at: datetime
    last_seen_at: datetime
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: PoisoningEvidenceStatus = "open"
    version: int = Field(default=1, ge=1)
    supersedes_evidence_id: Optional[str] = None
    superseded_by_evidence_id: Optional[str] = None
    restatement_reason: Optional[str] = None
    lifecycle_events: list[RiskPoisoningLifecycleEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _evidence_is_exact_and_temporally_valid(self) -> "RiskPoisoningEvidence":
        for label, value in (
            ("evidence_id", self.evidence_id),
            ("tenant_id", self.tenant_id),
            ("source_id", self.source_id),
            ("subject_kind", self.subject_kind),
            ("subject_id", self.subject_id),
            ("detector_id", self.detector_id),
            ("detector_version", self.detector_version),
            ("source_record_id", self.source_record_id),
        ):
            if not value.strip():
                raise ValueError(f"poisoning evidence {label} must not be empty")
        if any(
            instant.tzinfo is None or instant.utcoffset() is None
            for instant in (self.first_seen_at, self.last_seen_at, self.recorded_at)
        ):
            raise ValueError("poisoning evidence timestamps must include a timezone")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen_at must not precede first_seen_at")
        if self.version == 1:
            if self.supersedes_evidence_id is not None or self.restatement_reason is not None:
                raise ValueError("initial poisoning evidence cannot declare a restatement")
        elif (
            not self.supersedes_evidence_id
            or not self.restatement_reason
            or not self.restatement_reason.strip()
        ):
            raise ValueError("restated evidence requires a predecessor and reason")
        if self.status == "superseded" and not self.superseded_by_evidence_id:
            raise ValueError("superseded evidence requires a successor id")
        if self.status != "superseded" and self.superseded_by_evidence_id is not None:
            raise ValueError("only superseded evidence may name a successor")
        event_ids = [event.event_id for event in self.lifecycle_events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("poisoning lifecycle event ids must be unique")
        current_status: PoisoningEvidenceStatus = "open"
        allowed_transitions: dict[str, frozenset[str]] = {
            "open": frozenset({"acknowledged", "resolved", "dismissed", "superseded"}),
            "acknowledged": frozenset({"open", "resolved", "dismissed", "superseded"}),
            "resolved": frozenset({"superseded"}),
            "dismissed": frozenset({"superseded"}),
            "superseded": frozenset(),
        }
        previous_event_at: Optional[datetime] = None
        for event in self.lifecycle_events:
            if previous_event_at is not None and event.occurred_at < previous_event_at:
                raise ValueError("poisoning lifecycle events must be chronological")
            if event.from_status != current_status:
                raise ValueError("poisoning lifecycle events must form a status chain")
            if event.to_status not in allowed_transitions[current_status]:
                raise ValueError("poisoning lifecycle event has an illegal status transition")
            current_status = event.to_status
            previous_event_at = event.occurred_at
        if self.lifecycle_events and current_status != self.status:
            raise ValueError("poisoning evidence status must match its lifecycle history")
        if self.status == "superseded" and (
            not self.lifecycle_events or self.lifecycle_events[-1].to_status != "superseded"
        ):
            raise ValueError("superseded poisoning evidence requires a lifecycle event")
        if self.confidence == "verified" and self.claim_state not in {
            EpistemicStatus.VERIFIED,
            EpistemicStatus.CAUSALLY_SUPPORTED,
        }:
            raise ValueError("verified poisoning confidence requires factual claim state")
        evidence_ids = [ref.id for ref in self.evidence_refs]
        if any(not ref_id.strip() for ref_id in evidence_ids):
            raise ValueError("poisoning evidence references must have ids")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("poisoning evidence references must be unique")
        if any(not ref.source.strip() for ref in self.evidence_refs):
            raise ValueError("poisoning evidence references must name their source")
        for event in self.lifecycle_events:
            if event.occurred_at < self.recorded_at:
                raise ValueError("poisoning lifecycle event cannot predate the evidence record")
        return self


class RiskComponent(RiskContract):
    """One scored (or honestly absent) risk dimension within a RiskVector.

    ``state`` is the canonical measurement-plane :class:`ValueState`. The
    value-state invariant is enforced here: only ``observed`` / ``estimated``
    may carry a real ``score``; every other state (``missing_inputs``,
    ``insufficient_data``, ``not_applicable``, ``degraded``) requires
    ``score=None``. A missing dimension is therefore **never coerced to a
    fabricated zero** — the honest absence vocabulary (missing / unknown /
    unavailable / not_applicable / suppressed, per the SoT §4) renders as a
    non-value-bearing state. An *observed* zero (``state=observed, score=0.0``)
    is allowed because data genuinely supports it.
    """

    dimension: str
    state: ValueState = ValueState.MISSING_INPUTS
    score: Optional[float] = Field(default=None, ge=0, le=1)
    claim_state: EpistemicStatus = EpistemicStatus.UNKNOWN
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def _value_state_invariant(self) -> "RiskComponent":
        if requires_value(self.state) and self.score is None:
            raise ValueError(
                f"dimension {self.dimension!r}: state {self.state.value!r} is "
                "value-bearing, so a score is required"
            )
        if not requires_value(self.state) and self.score is not None:
            raise ValueError(
                f"dimension {self.dimension!r}: state {self.state.value!r} is "
                "not value-bearing, so score must be None (a real score "
                "requires observed/estimated data; a missing dimension is "
                "never a fabricated number)"
            )
        return self


class RiskVector(RiskContract):
    """A multidimensional risk result for one subject/context.

    ``components`` is intentionally **sparse**: it holds only the dimensions a
    producer actually scored or explicitly recorded. Every dimension the vector
    does NOT contain is still represented — never as a fabricated ``0``.
    :meth:`component_for` returns the recorded component when present, otherwise
    an honest-absence component (``ValueState.MISSING_INPUTS``, ``score=None``),
    so a consumer asking about any dimension gets a value-state-bearing answer
    rather than inventing a number. ``claim_state`` on an absent component stays
    ``EpistemicStatus.UNKNOWN``.
    """

    components: list[RiskComponent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dimensions_are_unique(self) -> "RiskVector":
        seen: dict[str, int] = {}
        for component in self.components:
            seen[component.dimension] = seen.get(component.dimension, 0) + 1
        duplicates = {d for d, n in seen.items() if n > 1}
        if duplicates:
            raise ValueError(
                f"RiskVector components must be unique per dimension; "
                f"duplicates: {sorted(duplicates)}"
            )
        return self

    def has_component(self, dimension: str) -> bool:
        """Return True when ``dimension`` has a recorded component."""
        return any(c.dimension == dimension for c in self.components)

    def component_for(self, dimension: str) -> RiskComponent:
        """Return the recorded component, or an honest-absence component.

        When ``dimension`` has no recorded component this synthesizes one with
        ``ValueState.MISSING_INPUTS`` (non-value-bearing) and ``score=None`` —
        it **never fabricates a zero** for an unobserved dimension.
        """
        for component in self.components:
            if component.dimension == dimension:
                return component
        return RiskComponent(
            dimension=dimension,
            state=ValueState.MISSING_INPUTS,
            claim_state=EpistemicStatus.UNKNOWN,
        )


class ExposureAssessment(RiskContract):
    """ "Risk of what" — the exposed assets/outcomes/populations and their value.

    Labels are free-text names of what is at stake (exposed assets, outcomes,
    populations); ``economic_value`` is typed with the canonical
    :class:`MonetaryAmount` (which keeps an unpriced amount ``None`` rather
    than a coerced ``0``). ``subject_kind``/``subject_id`` name the subject the
    exposure belongs to; ``subject_ref`` reuses the canonical
    :class:`EntityRef` when the subject is an entity-kind subject.
    """

    tenant_id: str
    subject_kind: str
    subject_id: str
    subject_ref: Optional[EntityRef] = None
    exposed_asset_labels: list[str] = Field(default_factory=list)
    exposed_outcome_labels: list[str] = Field(default_factory=list)
    exposed_population_labels: list[str] = Field(default_factory=list)
    economic_value: Optional[MonetaryAmount] = None
    claim_state: EpistemicStatus = EpistemicStatus.UNKNOWN
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class RiskAssessment(RiskContract):
    """An aggregation of risk signals in a context — the Risk360 record.

    Context = subject + policy + the dimensions evaluated + the resulting
    :class:`RiskVector` + optional :class:`ExposureAssessment` + an epistemic
    claim state over the whole read.

    ``policy_id`` / ``policy_version`` reference the canonical
    :class:`DecisionPolicy` (``shared/computation/policies.py``) by its id
    fields ONLY — there is no universal meaning for an overall risk score, so
    thresholds/weights live in the referenced policy, never embedded here or as
    service constants. This contract intentionally does not import the decision
    graph.

    ``subject_kind``/``subject_id`` name the assessed subject and may carry a
    reused :class:`EntityRef` in ``subject_ref`` when it is an entity-kind
    subject; relationship/cluster/population subjects are named by kind + id.
    ``snapshot`` optionally pins the point-in-time graph snapshot read
    (:class:`GraphSnapshotRef`). ``run_id`` ties the assessment to a
    reproducibility run (:class:`RiskAssessmentRun`) over ``computation_runs``.
    """

    assessment_id: str
    tenant_id: str
    subject_kind: str
    subject_id: str
    subject_ref: Optional[EntityRef] = None
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    #: Canonical risk dimension keys this assessment evaluated (may be a subset
    #: of RISK_DIMENSION_KEYS; unlisted ones stay missing in the vector).
    dimensions: list[str] = Field(default_factory=list)
    vector: RiskVector
    exposure: Optional[ExposureAssessment] = None
    claim_state: EpistemicStatus = EpistemicStatus.UNKNOWN
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    snapshot: Optional[GraphSnapshotRef] = None
    run_id: Optional[str] = None
    assessed_at: Optional[datetime] = None


class RiskAssessmentRun(RiskContract):
    """Reproducibility reference over the computation substrate.

    A Risk360 assessment run is a **reference onto ``computation_runs``** (the
    substrate table), described by ``new_run_id()`` + a deterministic
    ``context_hash`` from :class:`ComputationContext`. There is **no parallel
    run table** for Risk360: the assessment itself is persisted in
    ``risk_assessments`` and ``run_id`` links it to the substrate run. Two runs
    over equal computation contexts produce an equal ``context_hash``; a later
    restatement (late data) chains via ``supersedes_run_id`` so V1 and V2 both
    remain — "what Aether knew at decision time".
    """

    run_id: str
    tenant_id: str
    assessment_id: str
    #: Deterministic 32-hex hash of the computation context that produced this
    #: run (see ComputationContext.context_hash()).
    context_hash: str
    created_at: Optional[datetime] = None
    supersedes_run_id: Optional[str] = None

    @staticmethod
    def make_run_id() -> str:
        """Factory-style helper mirroring ``shared.computation.runtime.new_run_id``."""
        return new_run_id()

    @classmethod
    def from_context(
        cls,
        *,
        tenant_id: str,
        assessment_id: str,
        context: ComputationContext,
        created_at: Optional[datetime] = None,
        supersedes_run_id: Optional[str] = None,
    ) -> "RiskAssessmentRun":
        """Build a run over the computation substrate for an assessment.

        ``run_id`` is minted via ``new_run_id()`` and ``context_hash`` is the
        deterministic :meth:`ComputationContext.context_hash` of ``context`` —
        the dedupe/supersession key that keeps late-data restatements on the
        same computation from forking.
        """
        return cls(
            run_id=new_run_id(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            context_hash=context.context_hash(),
            created_at=created_at,
            supersedes_run_id=supersedes_run_id,
        )


__all__ = [
    # Domain contracts
    "RiskSignal",
    "RiskPoisoningEvidence",
    "RiskPoisoningLifecycleEvent",
    "PoisoningType",
    "PoisoningEvidenceStatus",
    "RiskComponent",
    "RiskVector",
    "ExposureAssessment",
    "RiskAssessment",
    "RiskAssessmentRun",
    # Re-exported canonical primitives (imported above — never re-declared).
    "EntityRef",
    "EvidenceRef",
    "GraphSnapshotRef",
    "EpistemicStatus",
    "ValueState",
    "requires_value",
    "MonetaryAmount",
    "ComputationContext",
]
