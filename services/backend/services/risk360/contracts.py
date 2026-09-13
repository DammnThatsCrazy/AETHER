"""Risk360 canonical domain contracts (Phase 3).

Hand-authored domain vocabulary for the Risk360 intelligence projection. All
models inherit :class:`RiskContract` (``extra="forbid"``) so a misspelled field
raises instead of silently passing — mirroring the projection-plane and
economic-domain contract discipline (``ProjectionContract``,
``EconomicContract``), NOT ``ContractModel`` which is ``extra="allow"``.

Reuse, never redefine: every canonical primitive below is imported from its
canonical home and declared **no second copy** of any of them here:

* ``EntityRef`` / ``EvidenceRef`` / ``GraphSnapshotRef`` ←
  ``services/operational_intelligence/models.py``
* ``EpistemicStatus`` ← ``shared/contracts_models/epistemic.py``
* ``ValueState`` ← ``shared/measurement/value_states.py``
* ``MonetaryAmount`` ← ``services/economic/economic360_contracts.py``
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

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Reused canonical primitives — never re-declared (identity-parity tested).
from services.operational_intelligence.models import (  # noqa: F401  (re-exported)
    EntityRef,
    EvidenceRef,
    GraphSnapshotRef,
)

# Canonical epistemic vocabulary (Phase 2 consolidation).
from shared.contracts_models.epistemic import EpistemicStatus

# Canonical value-state authority for the measurement integrity plane.
from shared.measurement.value_states import ValueState, requires_value

# Canonical economic amount for exposure "economic value".
from services.economic.economic360_contracts import MonetaryAmount

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
    #: Canonical risk dimension key (see services.risk360.dimensions).
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
