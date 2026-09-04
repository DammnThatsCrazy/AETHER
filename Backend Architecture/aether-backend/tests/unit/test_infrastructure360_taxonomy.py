"""Infrastructure360 vertical slice — taxonomy state-machine + semantics tests.

The taxonomy (``services/infrastructure/taxonomy.py``) is pure and
deterministic: a legal state-transition table, relationship semantics, and the
canonical fact categories. The headline invariant under test: ``FAILED ->
ACTIVE`` is ILLEGAL without an intervening redeploy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.infrastructure.contracts import (  # noqa: E402
    InfrastructureEntityType,
    InfrastructureRelationshipType,
    InfrastructureState,
)
from services.infrastructure.taxonomy import (  # noqa: E402
    DEPLOYMENT_TARGET_KINDS,
    INFRASTRUCTURE_FACT_CATEGORIES,
    LEGAL_STATE_TRANSITIONS,
    RELATIONSHIP_SEMANTICS,
    SUPPORTED_ENTITY_KINDS,
    can_transition,
    is_valid_kind,
    is_valid_relationship,
    requires_redeploy,
)

ST = InfrastructureState


# ---------------------------------------------------------------------------
# Legal / illegal state transitions
# ---------------------------------------------------------------------------

def test_failed_to_active_is_illegal() -> None:
    # The taxonomy's headline invariant: a failed entity must be redeployed
    # before it can be active — a direct repair-to-active claim is a lie.
    assert not can_transition(ST.FAILED, ST.ACTIVE)


def test_failed_to_provisioned_is_legal() -> None:
    assert can_transition(ST.FAILED, ST.PROVISIONED)


def test_failed_to_deploying_is_legal() -> None:
    # The redeploy path: FAILED -> PROVISIONED -> DEPLOYING -> ACTIVE.
    assert can_transition(ST.FAILED, ST.DEPLOYING)


def test_active_to_degraded_and_back_is_legal() -> None:
    assert can_transition(ST.ACTIVE, ST.DEGRADED)
    assert can_transition(ST.DEGRADED, ST.ACTIVE)


def test_deploying_to_active_is_legal() -> None:
    assert can_transition(ST.DEPLOYING, ST.ACTIVE)


def test_every_state_self_transitions_legally() -> None:
    for state in ST:
        assert can_transition(state, state)


def test_transition_table_covers_every_state() -> None:
    assert set(LEGAL_STATE_TRANSITIONS) == set(ST)


def test_requires_redeploy_flags_failed_exit() -> None:
    assert requires_redeploy(ST.FAILED, ST.ACTIVE)
    assert requires_redeploy(ST.FAILED, ST.PROVISIONED)
    # Staying failed / deprovisioning / unknown is not a redeploy.
    assert not requires_redeploy(ST.FAILED, ST.FAILED)
    assert not requires_redeploy(ST.FAILED, ST.DEPROVISIONING)
    # Healthy states never require a redeploy.
    assert not requires_redeploy(ST.ACTIVE, ST.DEGRADED)
    assert not requires_redeploy(ST.DEGRADED, ST.ACTIVE)


# ---------------------------------------------------------------------------
# Entity kind validation
# ---------------------------------------------------------------------------

def test_supported_entity_kinds_is_closed_and_nonempty() -> None:
    assert len(SUPPORTED_ENTITY_KINDS) == 12
    assert InfrastructureEntityType.SERVICE in SUPPORTED_ENTITY_KINDS
    assert InfrastructureEntityType.ORCHESTRATOR in SUPPORTED_ENTITY_KINDS


def test_is_valid_kind() -> None:
    assert is_valid_kind(InfrastructureEntityType.DATABASE)
    # str-Enum: the enum's own value string is the kind too.
    assert is_valid_kind("database")
    assert not is_valid_kind("bogus")
    assert not is_valid_kind("database_replica")


def test_deployment_target_kinds_are_runtime_hosts() -> None:
    assert DEPLOYMENT_TARGET_KINDS == {
        InfrastructureEntityType.HOST,
        InfrastructureEntityType.CONTAINER,
        InfrastructureEntityType.ORCHESTRATOR,
    }


# ---------------------------------------------------------------------------
# Relationship semantics
# ---------------------------------------------------------------------------

def test_every_relationship_type_has_semantics() -> None:
    for rel in InfrastructureRelationshipType:
        assert is_valid_relationship(rel)
        assert RELATIONSHIP_SEMANTICS[rel]
    assert not is_valid_relationship("bogus")


def test_depends_on_semantics_are_directional_gating() -> None:
    assert "gated" in RELATIONSHIP_SEMANTICS[
        InfrastructureRelationshipType.DEPENDS_ON
    ]


def test_deployed_on_semantics_mention_runtime_target() -> None:
    assert "runtime" in RELATIONSHIP_SEMANTICS[
        InfrastructureRelationshipType.DEPLOYED_ON
    ]


# ---------------------------------------------------------------------------
# Canonical fact categories match the registry authorities
# ---------------------------------------------------------------------------

def test_fact_categories_match_registry_canonical_authorities() -> None:
    # The registry row's canonicalAuthorities includes exactly these three
    # infrastructure authorities (the orchestrator extends AUTHORITY_INDEX
    # with the same three).
    assert INFRASTRUCTURE_FACT_CATEGORIES == (
        "infrastructure_facts",
        "infrastructure_state",
        "deployments",
    )


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        (ST.FAILED, ST.ACTIVE, False),
        (ST.FAILED, ST.PROVISIONED, True),
        (ST.FAILED, ST.DEPLOYING, True),
        (ST.ACTIVE, ST.FAILED, True),
        (ST.DEPLOYING, ST.ACTIVE, True),
        (ST.ACTIVE, ST.MAINTENANCE, True),
        (ST.MAINTENANCE, ST.ACTIVE, True),
        (ST.DEPROVISIONING, ST.PROVISIONED, True),
        (ST.ACTIVE, ST.UNKNOWN, False),
    ],
)
def test_transition_table_is_exact(
    current: InfrastructureState,
    target: InfrastructureState,
    expected: bool,
) -> None:
    assert can_transition(current, target) is expected
