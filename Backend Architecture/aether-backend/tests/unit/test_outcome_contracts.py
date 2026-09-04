"""Unit tests for the Outcome360 canonical outcome-domain contracts.

Covers the OutcomeState finality ladder + legality table (FINAL / CONDITIONALLY_FINAL
may only leave via an explicit superseding transition; FINAL -> PROVISIONAL and
FINAL -> REVERSIBLE are ILLEGAL), the transition-application API, the
OutcomeChain model, and the no-redefinition doctrine (the slice reuses the
canonical EvidenceRef / PageRequest / TimeRangeFilter — it never declares a
second EntityRef or time-range primitive).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

import services.measurement.outcome.contracts as outcome_contracts  # noqa: E402
from services.measurement.outcome.contracts import (  # noqa: E402
    OUTCOME_STATE_TRANSITIONS,
    Outcome,
    OutcomeChain,
    OutcomeChainLink,
    OutcomeState,
    OutcomeTransition,
    apply_transition,
    is_legal_transition,
)
from services.operational_intelligence.models import (  # noqa: E402
    EvidenceRef,
    PageRequest,
    TimeRangeFilter,
)


def _outcome(state: OutcomeState = OutcomeState.PROVISIONAL) -> Outcome:
    return Outcome(
        id="oc_1",
        tenant_id="tenant-a",
        domain="commercial",
        state=state,
        definition_ref="journey_completion",
        updated_at="2026-08-23T12:00:00Z",
    )


def _transition(
    from_state: OutcomeState,
    to_state: OutcomeState,
    *,
    superseding: bool = False,
) -> OutcomeTransition:
    return OutcomeTransition(
        from_state=from_state,
        to_state=to_state,
        reason="attested",
        occurred_at="2026-08-23T12:00:00Z",
        actor="measurement",
        superseding=superseding,
    )


# ---------------------------------------------------------------------------
# Finality legality table
# ---------------------------------------------------------------------------

def test_final_to_provisional_is_illegal() -> None:
    with pytest.raises(ValidationError):
        _transition(OutcomeState.FINAL, OutcomeState.PROVISIONAL)


def test_final_to_reversible_is_illegal() -> None:
    with pytest.raises(ValidationError):
        _transition(OutcomeState.FINAL, OutcomeState.REVERSIBLE)


def test_final_to_conditionally_final_is_illegal() -> None:
    with pytest.raises(ValidationError):
        _transition(OutcomeState.FINAL, OutcomeState.CONDITIONALLY_FINAL)


def test_final_to_superseded_requires_explicit_superseding() -> None:
    # FINAL -> SUPERSEDED is legal ONLY via an explicit superseding transition.
    with pytest.raises(ValidationError):
        _transition(OutcomeState.FINAL, OutcomeState.SUPERSEDED, superseding=False)

    transition = _transition(
        OutcomeState.FINAL, OutcomeState.SUPERSEDED, superseding=True
    )
    assert transition.to_state is OutcomeState.SUPERSEDED
    assert transition.superseding is True


def test_conditionally_final_to_final_is_legal() -> None:
    transition = _transition(OutcomeState.CONDITIONALLY_FINAL, OutcomeState.FINAL)
    assert transition.to_state is OutcomeState.FINAL


def test_conditionally_final_to_superseded_is_legal_when_superseding() -> None:
    with pytest.raises(ValidationError):
        _transition(
            OutcomeState.CONDITIONALLY_FINAL,
            OutcomeState.SUPERSEDED,
            superseding=False,
        )
    transition = _transition(
        OutcomeState.CONDITIONALLY_FINAL,
        OutcomeState.SUPERSEDED,
        superseding=True,
    )
    assert transition.to_state is OutcomeState.SUPERSEDED


def test_lower_ladder_transitions_are_legal() -> None:
    for from_state, to_state in (
        (OutcomeState.PROVISIONAL, OutcomeState.REVERSIBLE),
        (OutcomeState.PROVISIONAL, OutcomeState.CONDITIONALLY_FINAL),
        (OutcomeState.PROVISIONAL, OutcomeState.FINAL),
        (OutcomeState.REVERSIBLE, OutcomeState.PROVISIONAL),
        (OutcomeState.REVERSIBLE, OutcomeState.CONDITIONALLY_FINAL),
        (OutcomeState.REVERSIBLE, OutcomeState.FINAL),
    ):
        transition = _transition(from_state, to_state)
        assert transition.to_state is to_state


def test_superseded_is_terminal() -> None:
    for to_state in (
        OutcomeState.PROVISIONAL,
        OutcomeState.REVERSIBLE,
        OutcomeState.CONDITIONALLY_FINAL,
        OutcomeState.FINAL,
        OutcomeState.SUPERSEDED,
    ):
        with pytest.raises(ValidationError):
            _transition(OutcomeState.SUPERSEDED, to_state)


def test_state_transition_table_matches_ladder() -> None:
    # FINAL may only move to SUPERSEDED; CONDITIONALLY_FINAL only to FINAL/SUPERSEDED.
    assert set(OUTCOME_STATE_TRANSITIONS[OutcomeState.FINAL]) == {
        OutcomeState.SUPERSEDED
    }
    assert set(OUTCOME_STATE_TRANSITIONS[OutcomeState.CONDITIONALLY_FINAL]) == {
        OutcomeState.FINAL,
        OutcomeState.SUPERSEDED,
    }
    assert OUTCOME_STATE_TRANSITIONS[OutcomeState.SUPERSEDED] == ()


def test_is_legal_transition_predicate() -> None:
    assert is_legal_transition(OutcomeState.FINAL, OutcomeState.SUPERSEDED, superseding=True)
    assert not is_legal_transition(OutcomeState.FINAL, OutcomeState.SUPERSEDED)
    assert not is_legal_transition(OutcomeState.FINAL, OutcomeState.PROVISIONAL)
    assert not is_legal_transition(OutcomeState.FINAL, OutcomeState.REVERSIBLE)
    assert is_legal_transition(OutcomeState.CONDITIONALLY_FINAL, OutcomeState.FINAL)
    assert is_legal_transition(
        OutcomeState.CONDITIONALLY_FINAL, OutcomeState.SUPERSEDED, superseding=True
    )


def test_unknown_state_is_reclassifiable() -> None:
    transition = _transition(OutcomeState.UNKNOWN, OutcomeState.PROVISIONAL)
    assert transition.to_state is OutcomeState.PROVISIONAL


# ---------------------------------------------------------------------------
# Transition application
# ---------------------------------------------------------------------------

def test_apply_transition_returns_new_outcome() -> None:
    outcome = _outcome(OutcomeState.PROVISIONAL)
    transition = _transition(
        OutcomeState.PROVISIONAL, OutcomeState.CONDITIONALLY_FINAL
    )
    updated = apply_transition(outcome, transition)

    assert updated.state is OutcomeState.CONDITIONALLY_FINAL
    assert updated.updated_at == "2026-08-23T12:00:00Z"
    # Pure function — the source row is never mutated (read-only projection).
    assert outcome.state is OutcomeState.PROVISIONAL


def test_apply_transition_rejects_state_mismatch() -> None:
    outcome = _outcome(OutcomeState.PROVISIONAL)
    transition = _transition(
        OutcomeState.REVERSIBLE, OutcomeState.CONDITIONALLY_FINAL
    )
    with pytest.raises(ValueError, match="cannot apply"):
        apply_transition(outcome, transition)


def test_apply_transition_enforces_superseding() -> None:
    outcome = _outcome(OutcomeState.FINAL)
    with pytest.raises(ValueError):
        apply_transition(
            outcome,
            _transition(OutcomeState.FINAL, OutcomeState.SUPERSEDED),
        )
    updated = apply_transition(
        outcome,
        _transition(
            OutcomeState.FINAL, OutcomeState.SUPERSEDED, superseding=True
        ),
    )
    assert updated.state is OutcomeState.SUPERSEDED


# ---------------------------------------------------------------------------
# Outcome / OutcomeChain models
# ---------------------------------------------------------------------------

def test_outcome_round_trips_with_evidence() -> None:
    evidence = EvidenceRef(id="ev_1", type="event", source="measurement")
    outcome = Outcome(
        id="oc_1",
        tenant_id="tenant-a",
        domain="commercial",
        state=OutcomeState.FINAL,
        definition_ref="journey_completion",
        achieved_at="2026-08-01T00:00:00Z",
        target_at="2026-08-31T00:00:00Z",
        value=1.0,
        evidence_refs=[evidence],
        updated_at="2026-08-23T12:00:00Z",
    )
    dumped = outcome.model_dump()
    assert dumped["state"] == "final"
    assert dumped["evidence_refs"][0]["id"] == "ev_1"
    reloaded = Outcome(**dumped)
    assert reloaded.state is OutcomeState.FINAL
    assert reloaded.evidence_refs[0].type == "event"


def test_outcome_chain_links_carry_attested_transitions() -> None:
    chain = OutcomeChain(
        id="chain_1",
        tenant_id="tenant-a",
        outcomes=[
            _outcome(OutcomeState.CONDITIONALLY_FINAL),
            Outcome(
                id="oc_2",
                tenant_id="tenant-a",
                domain="commercial",
                state=OutcomeState.FINAL,
                definition_ref="journey_completion",
                updated_at="2026-08-23T12:00:00Z",
            ),
        ],
        links=[
            OutcomeChainLink(
                from_outcome_id="oc_1",
                to_outcome_id="oc_2",
                transition=_transition(
                    OutcomeState.CONDITIONALLY_FINAL, OutcomeState.FINAL
                ),
            ),
        ],
    )
    assert chain.links[0].transition.to_state is OutcomeState.FINAL


def test_outcome_chain_rejects_illegal_link_transition() -> None:
    with pytest.raises(ValidationError):
        OutcomeChainLink(
            from_outcome_id="oc_1",
            to_outcome_id="oc_2",
            transition=_transition(OutcomeState.FINAL, OutcomeState.PROVISIONAL),
        )


# ---------------------------------------------------------------------------
# No-redefinition doctrine (canonical primitives reused, never re-declared)
# ---------------------------------------------------------------------------

def test_outcome_package_reuses_canonical_primitives() -> None:
    # The slice reuses the SAME class objects as the canonical operational
    # intelligence models — not second copies.
    assert outcome_contracts.EvidenceRef is EvidenceRef
    assert outcome_contracts.PageRequest is PageRequest
    assert outcome_contracts.TimeRangeFilter is TimeRangeFilter


def test_outcome_package_declares_no_second_entity_ref() -> None:
    # No second EntityRef primitive anywhere in the outcome package namespace.
    assert "EntityRef" not in vars(outcome_contracts)
    # The provider's only *Ref name is the canonical EvidenceRef it re-uses
    # (identity, never a re-declaration).
    import services.measurement.outcome.provider as provider_mod  # noqa: E402

    ref_names = {name for name in vars(provider_mod) if name.endswith("Ref")}
    assert ref_names <= {"EvidenceRef"}
    if "EvidenceRef" in ref_names:
        assert provider_mod.EvidenceRef is EvidenceRef


def test_outcome_uses_canonical_evidence_ref_class() -> None:
    evidence = outcome_contracts.EvidenceRef(id="ev_1", type="event", source="s")
    assert isinstance(evidence, EvidenceRef)
