"""Unit tests for Communication360 Phase-5 delegation authority (services.communication360.authority).

Pure-logic coverage of decision-log #6 / SoT §24: mapping a ``services/delegation``
``allowed`` outcome onto the frozen ``AuthorityEvaluation`` decision vocabulary,
the reserved PARTIAL/DEGRADED states for scope-limited grants, the minimal
participant-binding role guard, and the observed epistemic status on evaluations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # Backend Architecture/aether-backend
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.communication360.authority import (  # noqa: E402
    EVALUATION_CLAIM_STATE,
    acting_within_scope,
    authority_state_for,
    evaluate_authority,
)
from services.communication360.contracts import (  # noqa: E402
    AuthorityState,
    CommunicationParticipantRole,
    ParticipantBinding,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402


def _binding(**overrides: object) -> ParticipantBinding:
    values: dict[str, object] = {
        "binding_id": "pb_1",
        "tenant_id": "tenant-a",
        "communication_scope": "conv_1",
        "communication_scope_kind": "conversation",
        "entity_id": "agent-1",
        "role": CommunicationParticipantRole.AUTHOR,
        "delegation_grant_id": "grant-1",
    }
    values.update(overrides)
    return ParticipantBinding(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# evaluate_authority mapping
# ---------------------------------------------------------------------------

def test_allowed_true_maps_to_granted() -> None:
    evaluation = evaluate_authority(
        agent_entity_id="agent-1",
        communication_scope="conv_1",
        communication_scope_kind="conversation",
        delegation_allowed=True,
        delegation_grant_id="grant-1",
        reason="active delegation",
        tenant_id="tenant-a",
    )
    assert evaluation.decision is AuthorityState.GRANTED
    assert evaluation.confidence == 1.0
    assert evaluation.claim_state is EVALUATION_CLAIM_STATE
    assert evaluation.claim_state is EpistemicStatus.OBSERVED
    assert evaluation.agent_entity_id == "agent-1"
    assert evaluation.communication_scope == "conv_1"
    assert evaluation.delegation_grant_id == "grant-1"
    assert evaluation.reason == "active delegation"


def test_allowed_false_maps_to_denied() -> None:
    evaluation = evaluate_authority(
        agent_entity_id="agent-1",
        communication_scope="conv_1",
        communication_scope_kind="conversation",
        delegation_allowed=False,
        reason="no active delegation",
        tenant_id="tenant-a",
    )
    assert evaluation.decision is AuthorityState.DENIED
    assert evaluation.confidence == 1.0
    assert evaluation.claim_state is EpistemicStatus.OBSERVED


def test_unknown_delegation_outcome_maps_to_unknown() -> None:
    evaluation = evaluate_authority(
        agent_entity_id="agent-1",
        communication_scope="conv_1",
        communication_scope_kind="conversation",
        delegation_allowed=None,
        tenant_id="tenant-a",
    )
    assert evaluation.decision is AuthorityState.UNKNOWN
    assert evaluation.confidence == 0.0
    assert evaluation.claim_state is EpistemicStatus.OBSERVED


def test_evaluate_authority_never_emits_scope_limited_states() -> None:
    # PARTIAL / DEGRADED are reserved for scope-/amount-limited grants and are
    # not reachable from a bare delegation boolean.
    for allowed in (True, False, None):
        evaluation = evaluate_authority(
            agent_entity_id="agent-1",
            communication_scope="conv_1",
            communication_scope_kind="conversation",
            delegation_allowed=allowed,
            tenant_id="tenant-a",
        )
        assert evaluation.decision not in {AuthorityState.PARTIAL, AuthorityState.DEGRADED}


def test_evaluate_authority_requires_tenant_id() -> None:
    with pytest.raises(ValueError):
        evaluate_authority(
            agent_entity_id="agent-1",
            communication_scope="conv_1",
            communication_scope_kind="conversation",
            delegation_allowed=True,
        )


def test_evaluation_claim_state_is_never_factual() -> None:
    evaluation = evaluate_authority(
        agent_entity_id="agent-1",
        communication_scope="conv_1",
        communication_scope_kind="conversation",
        delegation_allowed=True,
        tenant_id="tenant-a",
    )
    assert evaluation.claim_state is not None
    assert evaluation.claim_state.value not in {
        "verified",
        "resolved",
        "causally_supported",
    }


def test_evaluate_authority_is_deterministic() -> None:
    kwargs = dict(
        agent_entity_id="agent-1",
        communication_scope="m1",
        communication_scope_kind="message",
        delegation_allowed=True,
        tenant_id="tenant-a",
        evaluation_id="ev_1",
        evaluated_at="2026-09-03T12:00:00Z",
    )
    first = evaluate_authority(**kwargs)
    second = evaluate_authority(**kwargs)
    assert first.decision is AuthorityState.GRANTED
    assert first.model_dump() == second.model_dump()


# ---------------------------------------------------------------------------
# PARTIAL / DEGRADED — reserved for scope-/amount-limited grants
# ---------------------------------------------------------------------------

def test_scope_limited_grant_maps_to_partial() -> None:
    # A grant limited by scope/amount (e.g. services/delegation max_amount) is an
    # explicit PARTIAL — never produced from a bare allowed boolean.
    assert (
        authority_state_for(allowed=True, partial=True)
        is AuthorityState.PARTIAL
    )


def test_degraded_grant_maps_to_degraded() -> None:
    assert (
        authority_state_for(allowed=True, degraded=True)
        is AuthorityState.DEGRADED
    )


def test_partial_requires_explicit_flag() -> None:
    # Without the scope-limitation flag a bare allowed outcome stays GRANTED.
    assert authority_state_for(allowed=True) is AuthorityState.GRANTED
    assert authority_state_for(allowed=False) is AuthorityState.DENIED
    assert authority_state_for(allowed=None) is AuthorityState.UNKNOWN


# ---------------------------------------------------------------------------
# acting_within_scope role guard
# ---------------------------------------------------------------------------

def test_acting_within_scope_grants_when_role_matches() -> None:
    binding = _binding(role=CommunicationParticipantRole.AUTHOR)
    assert acting_within_scope(binding, True, role="author") is True


def test_acting_within_scope_denies_on_role_mismatch() -> None:
    binding = _binding(role=CommunicationParticipantRole.AUTHOR)
    assert acting_within_scope(binding, True, role="principal") is False


def test_acting_within_scope_never_widens_a_denial() -> None:
    binding = _binding(role=CommunicationParticipantRole.AUTHOR)
    assert acting_within_scope(binding, False, role="author") is False
    assert acting_within_scope(binding, None, role="author") is False


def test_acting_within_scope_accepts_binding_dicts() -> None:
    binding = _binding(role=CommunicationParticipantRole.SENDER).model_dump()
    assert acting_within_scope(binding, True, role="sender") is True
