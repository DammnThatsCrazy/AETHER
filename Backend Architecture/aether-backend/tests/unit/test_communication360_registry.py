"""Unit tests for the Phase-3 Communication360 dimension-seed registry.

Each seed in ``services/communication360/registry.py`` derives its values from
the contracts enums (``services/communication360/contracts.py``) by import —
never re-declared. These tests pin the registry to the canonical enums, the
sorting/non-empty contract, the helpers, and the no-redefinition rule.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.communication360.contracts import (  # noqa: E402
    AgentConsumptionState,
    AuthorityState,
    CapabilityState,
    CommunicationActType,
    CommunicationParticipantRole,
    ConversationState,
)
from services.communication360.registry import (  # noqa: E402
    COMMUNICATION360_DIMENSIONS,
    dimension,
    is_dimension_value,
)
import services.communication360.registry as registry_mod  # noqa: E402

# Dimension name -> the source contracts enum the seed must derive from.
DIMENSION_ENUMS = {
    "communication_participant_role": CommunicationParticipantRole,
    "communication_act_type": CommunicationActType,
    "conversation_state": ConversationState,
    "agent_consumption_state": AgentConsumptionState,
    "authority_state": AuthorityState,
    "capability_state": CapabilityState,
}


def test_dimension_keys_match_the_six_contracts_enums() -> None:
    assert set(COMMUNICATION360_DIMENSIONS) == set(DIMENSION_ENUMS)


@pytest.mark.parametrize("name", sorted(DIMENSION_ENUMS))
def test_dimension_is_nonempty_and_sorted(name: str) -> None:
    values = COMMUNICATION360_DIMENSIONS[name]
    assert isinstance(values, tuple)
    assert len(values) > 0
    assert all(isinstance(v, str) and v for v in values)
    assert values == tuple(sorted(values))


@pytest.mark.parametrize("name", sorted(DIMENSION_ENUMS))
def test_every_value_round_trips_to_the_source_enum_member(name: str) -> None:
    enum_cls = DIMENSION_ENUMS[name]
    expected = tuple(sorted(member.value for member in enum_cls))
    assert COMMUNICATION360_DIMENSIONS[name] == expected
    # Every seeded string round-trips to a real member of the contracts enum.
    for value in expected:
        assert enum_cls(value) is not None
        assert enum_cls(value).value == value


@pytest.mark.parametrize("name", sorted(DIMENSION_ENUMS))
def test_is_dimension_value(name: str) -> None:
    enum_cls = DIMENSION_ENUMS[name]
    for member in enum_cls:
        assert is_dimension_value(name, member.value) is True
    assert is_dimension_value(name, "definitely-not-a-member") is False
    assert is_dimension_value("not_a_dimension", "whatever") is False


def test_dimension_helper_returns_seed_and_fails_closed() -> None:
    for name, values in COMMUNICATION360_DIMENSIONS.items():
        assert dimension(name) == values
    with pytest.raises(KeyError):
        dimension("not_a_dimension")


def test_registry_derives_from_contracts_without_redeclaring() -> None:
    """Seeds must import the contracts enums — never re-declare vocab/primitives."""
    source = inspect.getsource(registry_mod)
    assert "from services.communication360.contracts import" in source
    # The registry must not define any enum or primitive class of its own.
    for banned in ("CommunicationParticipantRole", "CommunicationActType",
                   "ConversationState", "AgentConsumptionState", "AuthorityState",
                   "CapabilityState", "EvidenceRef", "EntityRef", "ContractModel"):
        assert f"class {banned}" not in source, f"registry re-declares {banned}"
