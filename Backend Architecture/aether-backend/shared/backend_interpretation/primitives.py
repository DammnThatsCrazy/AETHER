"""WS-D typed primitives — the backend-interpretation carriers.

Every carrier REUSES a canonical Aether primitive rather than redefining one
(blueprint reuse-never-redefine rule): :class:`EntityRef` and
:class:`EvidenceRef` come from ``services/operational_intelligence/models.py``
(single-monolith home) and :class:`CorrelationBlock` from
``shared/observation/envelope.py`` (Invariant #12 canonical correlation). This
module declares no second copy of any of them.

Three carriers:

* :class:`RelationshipFact` — a *typed* canonical relationship/edge fact with a
  ``resolution_method`` + a :class:`ValidityWindow`, carrying ``evidence_refs``
  end to end (blueprint Invariant #14 / gap row 26). Zero prior art existed for
  this primitive before WS-D; this module is its canonical home.
* :class:`EpisodeRecord` — the canonical episode primitive (gap row 31): a
  time-bounded, subject-scoped grouping of observations/outcomes with evidence
  lineage. ``episode360`` and sibling projections project over it.
* :class:`OutcomeTruthRecord` — the durable outcome-truth row that carries
  evidence lineage AND model/policy derivation lineage (gap row 26 / outcome
  store returns ``None`` today). It can be projected FROM a measurement
  :class:`~services.measurement.outcome.contracts.Outcome` (same state ladder)
  but adds the subject + derivation + exact-money columns the canonical outcome
  read currently drops.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.operational_intelligence.models import (
    EntityRef,
    EvidenceRef,
)

# ── Curated vocabularies (this package is their canonical home) ─────────────

# Resolution methods (Invariant #14 / relationship + identity resolution).
# ``observed`` = carried on an ingress observation verbatim; ``source_asserted``
# = asserted by the source without independent confirmation; ``resolved`` =
# reconciled to a canonical subject by identity resolution; ``inferred`` /
# ``predicted`` / ``attributed`` / ``causally_supported`` = derived by an
# intelligence mechanism; ``unresolved`` = explicit failure to resolve.
RESOLUTION_METHODS: tuple[str, ...] = (
    "observed",
    "source_asserted",
    "resolved",
    "inferred",
    "predicted",
    "attributed",
    "causally_supported",
    "unresolved",
)

CLAIM_TYPES: tuple[str, ...] = ("observed", "derived")

# Validity-window states: a fact is active from valid_from (or creation) to
# valid_to (or until superseded/expired). Finality mirrors the Outcome ladder's
# terminal-sink rule: SUPERSEDED facts never silently return to active.
VALIDITY_STATES: tuple[str, ...] = ("active", "expired", "pending", "superseded")

# Reuse the OutcomeState ladder values verbatim (same vocabulary, no second
# enum): provisional/reversible/conditionally_final/final/superseded/unknown.
OUTCOME_STATES: tuple[str, ...] = (
    "provisional",
    "reversible",
    "conditionally_final",
    "final",
    "superseded",
    "unknown",
)

# Money-presence states for outcome truth rows (money-exactness rule: None is
# never silently 0.0 — it is a typed absence).
VALUE_STATES: tuple[str, ...] = (
    "present",
    "missing",
    "empty",
    "zero",
    "degraded",
    "unknown",
)

EPISODE_STATUSES: tuple[str, ...] = ("open", "closed", "superseded", "unknown")

RelationshipResolutionMethod = Literal[
    "observed",
    "source_asserted",
    "resolved",
    "inferred",
    "predicted",
    "attributed",
    "causally_supported",
    "unresolved",
]
ClaimType = Literal["observed", "derived"]
ValidityState = Literal["active", "expired", "pending", "superseded"]
EpisodeStatus = Literal["open", "closed", "superseded", "unknown"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContractSpineModel(BaseModel):
    """Base for WS-D carriers (additive-tolerant like the monolith ContractModel)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ValidityWindow(ContractSpineModel):
    """When a relationship fact is (and stays) true.

    ``valid_from`` / ``valid_to`` are ISO-8601 instants or ``None`` (open
    window). ``state`` reflects the same terminal-sink discipline as outcome
    finality: ``superseded`` is a one-way exit.
    """

    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    state: ValidityState = "active"


class RelationshipFact(ContractSpineModel):
    """A typed relationship fact between two entities (gap row 26 / Inv. #14).

    Adds what the legacy edge record lacked: a canonical ``predicate`` +
    ``direction``, an explicit ``resolution_method`` and :class:`ValidityWindow`
    (not just an opaque properties blob), and first-class ``evidence_refs`` that
    survive promotion into the graph (the identity audit today drops per-signal
    evidence). ``relationship_key`` is the normalized ``subject|predicate|object``
    natural key used to group duplicate edges; ``fact_id`` is unique per write.
    """

    tenant_id: str
    fact_id: str
    relationship_key: str
    subject: EntityRef
    object: EntityRef
    predicate: str
    direction: Literal["outgoing", "incoming", "undirected"] = "undirected"
    resolution_method: RelationshipResolutionMethod = "observed"
    resolution_reason: Optional[str] = None
    validity: ValidityWindow = Field(default_factory=ValidityWindow)
    claim_type: ClaimType = "observed"
    model_version: Optional[str] = None
    policy_version: Optional[str] = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    source_event_id: Optional[str] = None
    observed_at: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    supersedes: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.validity.state == "active"

    def resolved_evidence_ids(self) -> list[str]:
        return [ref.id for ref in self.evidence_refs]


class EpisodeRecord(ContractSpineModel):
    """The canonical episode primitive (gap row 31 / item 2).

    An episode is a time-bounded, subject-scoped, kind-tagged span that groups
    the observations and outcomes which tell one story (a support ticket, a
    user journey, an execution run). Carries its own evidence lineage and the
    ids of the outcome/observation rows it spans; ``episode360`` and sibling
    projections project over these records. Never a competing system of record:
    the underlying observations/outcomes stay canonical.
    """

    episode_id: str
    tenant_id: str
    subject: EntityRef
    kind: str
    status: EpisodeStatus = "open"
    title: Optional[str] = None
    occurred_from: Optional[str] = None
    occurred_to: Optional[str] = None
    outcome_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    model_version: Optional[str] = None
    source_event_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    closed_at: Optional[str] = None


class OutcomeTruthRecord(ContractSpineModel):
    """Durable outcome-truth row WITH lineage (gap row 26 / item 3).

    The canonical outcome read today returns ``None`` (outcome store returns
    ``None``); the durable row this record models keeps the derivation lineage
    that identity-style audits otherwise drop: ``claim_type``,
    ``model_version`` / ``policy_version``, ``source_event_ids`` and every
    ``evidence_refs`` entry. ``state`` uses the Outcome finality-ladder values
    (no second enum); exact money is carried as ``value_amount`` /
    ``value_currency`` DECIMAL strings (``None`` amount is a typed
    ``value_state`` absence, never a silent ``0.0``).
    """

    outcome_id: str
    tenant_id: str
    definition_ref: str
    subject: Optional[EntityRef] = None
    state: str = "unknown"  # OutcomeState ladder values (validated below)
    achieved_at: Optional[str] = None
    value_amount: Optional[str] = None
    value_currency: Optional[str] = None
    value_state: str = "missing"  # VALUE_STATES member
    claim_type: ClaimType = "observed"
    model_version: Optional[str] = None
    policy_version: Optional[str] = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    observed_at: Optional[str] = None
    updated_at: str = Field(default_factory=utc_now_iso)
    superseded_by: Optional[str] = None

    @classmethod
    def validate_vocab(cls, value: str) -> None:
        if value not in OUTCOME_STATES:
            raise ValueError(
                f"state {value!r} is not an Outcome ladder member "
                f"(allowed: {OUTCOME_STATES})"
            )


_CANONICAL_EVIDENCE_TYPES = frozenset(
    {
        "event",
        "entity",
        "relationship",
        "document",
        "transaction",
        "model_output",
        "annotation",
    }
)


def evidence_ref(
    *,
    evidence_id: str,
    evidence_type: str,
    source: str,
    observed_at: Optional[str] = None,
    confidence: Optional[float] = None,
    uri: Optional[str] = None,
) -> EvidenceRef:
    """Build a canonical :class:`EvidenceRef` from a (possibly raw) signal.

    ``evidence_type`` is a member of the canonical EvidenceType vocabulary
    (validated by ``EvidenceRef``); a raw source-native type label that is not
    on the canonical vocabulary is mapped to ``event`` (the fallback member) so
    an off-vocabulary source string can never crash a wiring seam. WS-D callers
    that only hold a raw ``source_event_id`` string pass
    ``evidence_id=source_event_id``, ``evidence_type="event"`` and ``source=``
    the origin system.
    """
    return EvidenceRef(
        id=evidence_id,
        type=evidence_type if evidence_type in _CANONICAL_EVIDENCE_TYPES else "event",
        source=source,
        observedAt=observed_at,
        confidence=confidence,
        uri=uri,
    )


__all__ = [
    "CLAIM_TYPES",
    "EPISODE_STATUSES",
    "OUTCOME_STATES",
    "RESOLUTION_METHODS",
    "VALIDITY_STATES",
    "VALUE_STATES",
    "ClaimType",
    "ContractSpineModel",
    "EpisodeRecord",
    "EpisodeStatus",
    "OutcomeTruthRecord",
    "RelationshipFact",
    "RelationshipResolutionMethod",
    "ValidityState",
    "ValidityWindow",
    "evidence_ref",
    "utc_now_iso",
]
