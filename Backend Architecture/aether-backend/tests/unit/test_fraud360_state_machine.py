"""Fraud360 hypothesis state-machine tests (Phase 3).

Exercises the full lifecycle: the backbone funnel
(``candidate → under_evaluation → supported → material → investigating →
confirmed | rejected | inconclusive → closed``), the legal extras
(``superseded``/``disputed``/``stale``/``corrected``), and the
no-silent-escalation rule — a ``derived``/``inferred``/``predicted``/
``correlated``/``attributed`` suspicion can NEVER reach ``confirmed``, while a
factual claim state (``observed``/``verified``/``causally_supported``) can.
``rejected`` requires an evidence-grounded basis.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.fraud360.contracts import (  # noqa: E402
    CONFIRMED_FACTUAL_CLAIM_STATES,
    SUSPICION_CLAIM_STATES,
    ConfirmationRequiresFactualClaimError,
    EpistemicStatus,
    FraudHypothesisState,
    FraudHypothesisStateMachine,
    IllegalTransitionError,
    RejectionRequiresEvidenceError,
)

S = FraudHypothesisState


def _walk(states, **kwargs):
    """Walk a forward path, asserting each hop is legal and returns the target."""
    current = states[0]
    for target in states[1:]:
        current = FraudHypothesisStateMachine.transition(current, target, **kwargs)
    return current


def test_full_confirmed_lifecycle():
    end = _walk(
        [
            S.CANDIDATE,
            S.UNDER_EVALUATION,
            S.SUPPORTED,
            S.MATERIAL,
            S.INVESTIGATING,
            S.CONFIRMED,
            S.CLOSED,
        ],
        claim_state=EpistemicStatus.VERIFIED,
        evidence_refs=["ev1"],
    )
    assert end is S.CLOSED


def test_full_rejected_lifecycle_requires_evidence():
    with pytest.raises(RejectionRequiresEvidenceError):
        _walk(
            [S.CANDIDATE, S.UNDER_EVALUATION, S.REJECTED],
            evidence_refs=None,
        )
    end = _walk(
        [S.CANDIDATE, S.UNDER_EVALUATION, S.REJECTED, S.CLOSED],
        evidence_refs=["ev_reject"],
    )
    assert end is S.CLOSED


def test_inconclusive_can_reopen_the_funnel():
    end = _walk(
        [S.INVESTIGATING, S.INCONCLUSIVE, S.UNDER_EVALUATION, S.SUPPORTED],
    )
    assert end is S.SUPPORTED


def test_suspicion_claim_never_reaches_confirmed():
    """No-silent-escalation: every suspicion claim state is denied at confirmed."""
    for suspicion in SUSPICION_CLAIM_STATES:
        with pytest.raises(ConfirmationRequiresFactualClaimError):
            FraudHypothesisStateMachine.transition(
                S.INVESTIGATING,
                S.CONFIRMED,
                claim_state=suspicion,
                evidence_refs=["ev1"],
            )


def test_confirm_without_claim_state_is_denied():
    with pytest.raises(ConfirmationRequiresFactualClaimError):
        FraudHypothesisStateMachine.transition(
            S.INVESTIGATING, S.CONFIRMED, evidence_refs=["ev1"], claim_state=None
        )


def test_factual_claim_state_reaches_confirmed():
    for factual in CONFIRMED_FACTUAL_CLAIM_STATES:
        result = FraudHypothesisStateMachine.transition(
            S.INVESTIGATING,
            S.CONFIRMED,
            claim_state=factual,
            evidence_refs=["ev1"],
        )
        assert result is S.CONFIRMED


def test_illegal_edge_raises():
    with pytest.raises(IllegalTransitionError):
        FraudHypothesisStateMachine.transition(S.CANDIDATE, S.CONFIRMED)
    with pytest.raises(IllegalTransitionError):
        FraudHypothesisStateMachine.transition(S.SUPPORTED, S.CANDIDATE)
    with pytest.raises(IllegalTransitionError):
        FraudHypothesisStateMachine.transition(S.CLOSED, S.DISPUTED)


def test_legal_extras_reachable_from_active_states():
    # superseded / disputed / stale / corrected are legal extras from active
    # states — representative hops all return their target.
    assert FraudHypothesisStateMachine.transition(S.CANDIDATE, S.SUPERSEDED) is S.SUPERSEDED
    assert FraudHypothesisStateMachine.transition(S.SUPPORTED, S.DISPUTED) is S.DISPUTED
    assert FraudHypothesisStateMachine.transition(S.INVESTIGATING, S.STALE) is S.STALE
    assert FraudHypothesisStateMachine.transition(S.MATERIAL, S.CORRECTED) is S.CORRECTED
    # A confirmed record may still be disputed / superseded (never silently).
    assert FraudHypothesisStateMachine.transition(
        S.CONFIRMED, S.DISPUTED, claim_state=EpistemicStatus.VERIFIED
    ) is S.DISPUTED


def test_meta_state_exits_keep_lifecycle_usable():
    assert _walk([S.DISPUTED, S.UNDER_EVALUATION, S.SUPPORTED]) is S.SUPPORTED
    assert _walk([S.STALE, S.UNDER_EVALUATION]) is S.UNDER_EVALUATION
    assert _walk([S.SUPERSEDED, S.DISPUTED]) is S.DISPUTED
    end = FraudHypothesisStateMachine.transition(
        S.CORRECTED, S.CONFIRMED, claim_state=EpistemicStatus.VERIFIED
    )
    assert end is S.CONFIRMED


def test_allowed_transition_table_is_total_and_closed_is_sink():
    all_states = set(S)
    assert set(FraudHypothesisStateMachine.ALLOWED_TRANSITIONS) == all_states
    assert FraudHypothesisStateMachine.ALLOWED_TRANSITIONS[S.CLOSED] == frozenset()


def test_is_allowed_is_structural_only():
    assert FraudHypothesisStateMachine.is_allowed(S.INVESTIGATING, S.CONFIRMED)
    assert not FraudHypothesisStateMachine.is_allowed(S.CANDIDATE, S.CONFIRMED)
    # structural edge exists but the no-silent-escalation rule still blocks it.
    with pytest.raises(ConfirmationRequiresFactualClaimError):
        FraudHypothesisStateMachine.transition(
            S.INVESTIGATING, S.CONFIRMED, claim_state=EpistemicStatus.DERIVED
        )


def test_string_inputs_are_coerced():
    assert FraudHypothesisStateMachine.transition(
        "investigating", "confirmed",
        claim_state="verified", evidence_refs=["ev"],
    ) is S.CONFIRMED
