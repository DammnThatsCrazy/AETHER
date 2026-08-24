"""Canonical outcome-domain contracts for the Outcome360 intelligence projection.

ADR-010: a 360 is an intelligence projection over canonical Aether truth — never
a competing system of record. This module owns the outcome DOMAIN vocabulary the
projection projects: the :class:`OutcomeState` finality ladder, the
:class:`Outcome` row, the :class:`OutcomeTransition` legality model and the
:class:`OutcomeChain` that links outcomes across time. It never re-implements
measurement facts — achievement truth stays with the measurement engine
(journey compiler / gold materializer / ``services/measurement/contracts.py``).

Reuse, never redefine: the canonical primitives (:class:`EvidenceRef`,
:class:`PageRequest`, :class:`TimeRangeFilter`) are imported from
``services/operational_intelligence/models.py`` (single-monolith reuse). This
module deliberately declares NO second ``EntityRef`` / ``EvidenceRef`` /
``PageRequest`` / time-range primitive — the parity test asserts it.

The finality ladder and its legality table are the contract's spine:

* ``PROVISIONAL`` — observed but not yet ratified.
* ``REVERSIBLE`` — confirmed but still correctable by new evidence.
* ``CONDITIONALLY_FINAL`` — final under stated conditions.
* ``FINAL`` — terminal (except supersession).
* ``SUPERSEDED`` — terminal sink reachable by an explicit superseding transition.
* ``UNKNOWN`` — unclassified fallback (never a silent claim).

A transition to ``SUPERSEDED`` from ``CONDITIONALLY_FINAL`` / ``FINAL`` MUST
carry ``superseding=True`` — finality is never undone silently; ``FINAL ->
PROVISIONAL`` and ``FINAL -> REVERSIBLE`` are ILLEGAL by the table.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, model_validator

from services.operational_intelligence.models import (
    ContractModel,
    EvidenceRef,  # noqa: F401 - re-exported canonical primitive
    PageRequest,  # noqa: F401 - re-exported canonical primitive
    TimeRangeFilter,  # noqa: F401 - re-exported canonical primitive
)


class OutcomeState(str, Enum):
    """The finality ladder of a canonical outcome row.

    Member VALUES are lower-snake (repo registry convention); member NAMES are
    the uppercase ladder positions referenced by the legality table.
    """

    PROVISIONAL = "provisional"
    REVERSIBLE = "reversible"
    CONDITIONALLY_FINAL = "conditionally_final"
    FINAL = "final"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


# ── Finality legality table ─────────────────────────────────────────────────
# ``from_state -> (to_state, ...)``. Terminal states (FINAL / SUPERSEDED) have
# no upward transitions; SUPERSEDED is a one-way sink. UNKNOWN is the
# unclassified fallback and may be reclassified onto any ladder position.

OUTCOME_STATE_TRANSITIONS: dict[OutcomeState, tuple[OutcomeState, ...]] = {
    OutcomeState.UNKNOWN: (
        OutcomeState.PROVISIONAL,
        OutcomeState.REVERSIBLE,
        OutcomeState.CONDITIONALLY_FINAL,
        OutcomeState.FINAL,
        OutcomeState.SUPERSEDED,
    ),
    OutcomeState.PROVISIONAL: (
        OutcomeState.REVERSIBLE,
        OutcomeState.CONDITIONALLY_FINAL,
        OutcomeState.FINAL,
        OutcomeState.SUPERSEDED,
    ),
    OutcomeState.REVERSIBLE: (
        OutcomeState.PROVISIONAL,
        OutcomeState.CONDITIONALLY_FINAL,
        OutcomeState.FINAL,
        OutcomeState.SUPERSEDED,
    ),
    OutcomeState.CONDITIONALLY_FINAL: (
        OutcomeState.FINAL,
        OutcomeState.SUPERSEDED,
    ),
    OutcomeState.FINAL: (
        OutcomeState.SUPERSEDED,
    ),
    OutcomeState.SUPERSEDED: (),
}

# Finality positions that may be released ONLY through an explicit superseding
# transition — never reopened and never silently re-derived.
_FINALITY_STATES_REQUIRING_SUPERSEDING = frozenset(
    {
        OutcomeState.CONDITIONALLY_FINAL,
        OutcomeState.FINAL,
    }
)


def is_legal_transition(
    from_state: OutcomeState,
    to_state: OutcomeState,
    *,
    superseding: bool = False,
) -> bool:
    """True when ``from_state -> to_state`` is a legal ladder transition.

    ``superseding`` marks an explicit supersession record (required to leave a
    finality position for SUPERSEDED). Pure predicate — never raises.
    """
    if to_state not in OUTCOME_STATE_TRANSITIONS.get(from_state, ()):
        return False
    if (
        to_state is OutcomeState.SUPERSEDED
        and from_state in _FINALITY_STATES_REQUIRING_SUPERSEDING
        and not superseding
    ):
        return False
    return True


def _require_legal_transition(
    from_state: OutcomeState,
    to_state: OutcomeState,
    *,
    superseding: bool,
) -> None:
    if not is_legal_transition(
        from_state, to_state, superseding=superseding
    ):
        raise ValueError(
            f"illegal outcome-state transition {from_state.value!r} -> "
            f"{to_state.value!r}"
            + (
                "; leaving a finality state for superseded requires an "
                "explicit superseding transition"
                if to_state is OutcomeState.SUPERSEDED
                and from_state in _FINALITY_STATES_REQUIRING_SUPERSEDING
                else ""
            )
        )


class OutcomeTransition(ContractModel):
    """One attested state transition of an outcome row.

    ``superseding`` marks an EXPLICIT supersession record. It is required when
    a finality state (``FINAL`` / ``CONDITIONALLY_FINAL``) moves to
    ``SUPERSEDED``; the legality table rejects every other path out of a
    finality state.
    """

    from_state: OutcomeState
    to_state: OutcomeState
    reason: str
    occurred_at: str
    actor: str
    superseding: bool = False

    @model_validator(mode="after")
    def _validate_legality(self) -> "OutcomeTransition":
        _require_legal_transition(
            self.from_state,
            self.to_state,
            superseding=self.superseding,
        )
        return self


class Outcome(ContractModel):
    """One canonical outcome row (a projection of outcome_facts).

    ``definition_ref`` names an outcome type from the canonical
    ``outcome-type-registry.json`` (e.g. ``journey_completion``). ``value`` is
    the optional attested scalar (rate, amount, count). Every row that the
    projection asserts carries at least one :class:`EvidenceRef`.
    """

    id: str
    tenant_id: str
    domain: str
    state: OutcomeState
    definition_ref: str
    achieved_at: Optional[str] = None
    target_at: Optional[str] = None
    value: Optional[float] = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    updated_at: str


class OutcomeChainLink(ContractModel):
    """One attested link between two outcomes in a chain.

    The link carries the transition that produced ``to_outcome_id`` from
    ``from_outcome_id`` — the finality legality table is enforced on the link
    itself (via :class:`OutcomeTransition`).
    """

    from_outcome_id: str
    to_outcome_id: str
    transition: OutcomeTransition


class OutcomeChain(ContractModel):
    """A tenant-scoped, time-ordered chain of outcome rows and their links."""

    id: str
    tenant_id: str
    outcomes: list[Outcome]
    links: list[OutcomeChainLink]


def apply_transition(outcome: Outcome, transition: OutcomeTransition) -> Outcome:
    """Apply ``transition`` to ``outcome``, returning a NEW outcome row.

    Pure function (the projection plane is read-only): the source row is never
    mutated. Enforces that ``transition.from_state`` matches the row's current
    state (a transition cannot be applied off a mismatched base) on top of the
    transition model's own legality validation.
    """
    if transition.from_state is not outcome.state:
        raise ValueError(
            f"transition from {transition.from_state.value!r} cannot apply to "
            f"outcome {outcome.id!r} in state {outcome.state.value!r}"
        )
    return outcome.model_copy(
        update={
            "state": transition.to_state,
            "updated_at": transition.occurred_at,
        }
    )


__all__ = [
    "EvidenceRef",  # canonical primitive re-export (never redefined)
    "Outcome",
    "OutcomeChain",
    "OutcomeChainLink",
    "OutcomeState",
    "OutcomeTransition",
    "OUTCOME_STATE_TRANSITIONS",
    "PageRequest",  # canonical primitive re-export (never redefined)
    "TimeRangeFilter",  # canonical primitive re-export (never redefined)
    "apply_transition",
    "is_legal_transition",
]
