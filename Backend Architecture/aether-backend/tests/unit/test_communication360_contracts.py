"""Unit tests for the Phase-3 canonical Communication360 contract surface.

The authoritative surface is ``services/communication360/contracts.py`` and its
``__all__`` (27 names: 21 pydantic model families + the 6 Phase-2 vocab enums).
These tests enforce the parity/alignment obligations:

* every model family constructs with its required fields and round-trips
  ``model_dump()`` / ``model_validate()``;
* the surface fails closed — an unknown field on any model raises
  :class:`pydantic.ValidationError` (``extra="forbid"``);
* ``CommunicationParticipantRole`` has exactly the 11 Phase-2 ratified roles;
* the module never re-defines canonical primitives it must import instead
  (``EvidenceRef``, ``EntityRef``, ``CommunicationState``, ``EpistemicStatus``,
  ``ContractModel``).
"""

from __future__ import annotations

import inspect
import os
import sys
from enum import Enum
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parents[4]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

import services.communication360.contracts as contracts_mod  # noqa: E402

BASE = contracts_mod.CommunicationContract

# Minimal required-field kwargs for each model family (nested objects are
# passed as plain dicts — pydantic v2 coerces them).
_MODEL_SAMPLES: dict[str, dict] = {
    "CommunicationContract": {},
    "InformationRef": {
        "information_id": "info-1",
        "kind": "message_content",
        "tenant_id": "tenant-a",
    },
    "Information": {
        "information_id": "info-1",
        "tenant_id": "tenant-a",
        "kind": "message_content",
    },
    "MessageClaimBinding": {
        "binding_id": "binding-1",
        "tenant_id": "tenant-a",
        "message_id": "msg-1",
        "information_ref": {
            "information_id": "info-1",
            "kind": "message_content",
            "tenant_id": "tenant-a",
        },
    },
    "InformationTransformation": {
        "transformation_id": "tx-1",
        "tenant_id": "tenant-a",
        "source_information_ref": {
            "information_id": "info-1",
            "kind": "message_content",
            "tenant_id": "tenant-a",
        },
        "derived_information_ref": {
            "information_id": "info-2",
            "kind": "summary",
            "tenant_id": "tenant-a",
        },
        "kind": "summarization",
        "occurred_at": "2026-09-03T12:00:00Z",
    },
    "CommunicationMessage": {
        "message_id": "msg-1",
        "tenant_id": "tenant-a",
        "occurred_at": "2026-09-03T12:00:00Z",
    },
    "ResolutionRecord": {
        "method": "participants+topics",
        "confidence": 0.9,
    },
    "ProviderThread": {
        "thread_id": "thread-1",
        "tenant_id": "tenant-a",
        "provider": "outlook",
        "external_thread_id": "ext-thread-1",
    },
    "Conversation": {
        "conversation_id": "conv-1",
        "tenant_id": "tenant-a",
    },
    "Matter": {
        "matter_id": "matter-1",
        "tenant_id": "tenant-a",
        "subject": "Onboarding",
    },
    "CommunicationAct": {
        "act_id": "act-1",
        "tenant_id": "tenant-a",
        "act_type": "commit",
        "actor_entity_id": "entity-1",
        "occurred_at": "2026-09-03T12:00:00Z",
    },
    "Request": {
        "request_id": "req-1",
        "tenant_id": "tenant-a",
        "requester_entity_id": "entity-1",
        "occurred_at": "2026-09-03T12:00:00Z",
    },
    "Commitment": {
        "commitment_id": "comm-1",
        "tenant_id": "tenant-a",
        "committer_entity_id": "entity-1",
        "occurred_at": "2026-09-03T12:00:00Z",
    },
    "ResponseExpectation": {
        "expectation_id": "exp-1",
        "tenant_id": "tenant-a",
        "occurred_at": "2026-09-03T12:00:00Z",
    },
    "ParticipantBinding": {
        "binding_id": "pb-1",
        "tenant_id": "tenant-a",
        "communication_scope": "msg-1",
        "communication_scope_kind": "message",
        "entity_id": "entity-1",
        "role": "author",
    },
    "ContextInclusionRecord": {
        "record_id": "rec-1",
        "tenant_id": "tenant-a",
        "agent_entity_id": "agent-1",
    },
    "InterpretationRecord": {
        "record_id": "rec-2",
        "tenant_id": "tenant-a",
        "agent_entity_id": "agent-1",
    },
    "KnowledgeStateRecord": {
        "record_id": "rec-3",
        "tenant_id": "tenant-a",
        "subject_entity_id": "entity-1",
    },
    "AuthorityEvaluation": {
        "evaluation_id": "eval-1",
        "tenant_id": "tenant-a",
        "agent_entity_id": "agent-1",
        "communication_scope": "msg-1",
        "communication_scope_kind": "message",
    },
    "ProviderCapability": {
        "capability_id": "cap-1",
        "tenant_id": "tenant-a",
        "provider": "outlook",
    },
    "CommunicationQuality": {
        "quality_id": "qual-1",
        "tenant_id": "tenant-a",
        "communication_ref": "msg-1",
    },
}


def _model_families():
    """Yield (name, class) for every pydantic model family in ``__all__``."""
    for name in contracts_mod.__all__:
        obj = getattr(contracts_mod, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            yield name, obj


def _enum_vocabularies():
    """Yield (name, enum class) for every str-Enum vocabulary in ``__all__``."""
    for name in contracts_mod.__all__:
        obj = getattr(contracts_mod, name)
        if isinstance(obj, type) and issubclass(obj, Enum) and not issubclass(obj, BaseModel):
            yield name, obj


def test_surface_composition() -> None:
    assert len(contracts_mod.__all__) == 27
    model_names = [n for n, _ in _model_families()]
    enum_names = [n for n, _ in _enum_vocabularies()]
    assert len(model_names) == 21
    assert len(enum_names) == 6
    assert set(model_names) | set(enum_names) == set(contracts_mod.__all__)


@pytest.mark.parametrize("name", [n for n, _ in _model_families()])
def test_model_family_round_trips(name: str) -> None:
    cls = getattr(contracts_mod, name)
    instance = cls(**_MODEL_SAMPLES[name])
    assert isinstance(instance, BASE)
    dumped = instance.model_dump()
    rebuilt = cls.model_validate(dumped)
    assert rebuilt.model_dump() == dumped


@pytest.mark.parametrize("name", [n for n, _ in _model_families()])
def test_model_family_fails_closed_on_unknown_field(name: str) -> None:
    cls = getattr(contracts_mod, name)
    dumped = cls(**_MODEL_SAMPLES[name]).model_dump()
    poisoned = dict(dumped)
    poisoned["_definitely_not_a_real_field_"] = "drift"
    with pytest.raises(ValidationError):
        cls.model_validate(poisoned)


@pytest.mark.parametrize("name", [n for n, _ in _enum_vocabularies()])
def test_vocab_enums_are_str_enums(name: str) -> None:
    cls = getattr(contracts_mod, name)
    values = [member.value for member in cls]
    assert all(isinstance(v, str) and v for v in values)
    assert len(set(values)) == len(values)


def test_communication_participant_role_has_exactly_11_members() -> None:
    members = list(contracts_mod.CommunicationParticipantRole)
    assert len(members) == 11
    values = sorted(member.value for member in members)
    assert values == sorted([
        "actor", "author", "generator", "editor", "approver", "sender",
        "presented_sender", "principal", "delegator", "beneficiary",
        "accountable_party",
    ])


def test_no_redefinition_of_canonical_primitives() -> None:
    """The contracts module must import canonical primitives, never re-declare."""
    source = inspect.getsource(contracts_mod)
    for banned in ("EvidenceRef", "EntityRef", "CommunicationState",
                   "EpistemicStatus", "ContractModel"):
        assert f"class {banned}" not in source, f"contracts re-declares {banned}"
