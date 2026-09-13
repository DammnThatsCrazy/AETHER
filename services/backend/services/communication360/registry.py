"""Communication360 dimension seeds — Phase-3 registry vocabulary alignment.

The ratified Phase-2 vocabularies live ONCE in ``services/communication360/
contracts.py`` (the canonical contract surface). This module never re-declares
them: each dimension seed below derives its member values directly from the
contracts enums by import, so a member added to a contracts enum is visible to
every dimension consumer (Phase-4 provider capability validation, Phase-5/6 act
extraction and registry alignment) without a second source of truth.

``kind`` discriminators for the ``communication360_facts`` table (information,
conversation, ...) are intentionally NOT enum-backed (see the migration) and are
not listed here — only the six enum-backed dimensions are seeded.
"""

from __future__ import annotations

from services.communication360.contracts import (
    AgentConsumptionState,
    AuthorityState,
    CapabilityState,
    CommunicationActType,
    CommunicationParticipantRole,
    ConversationState,
)

#: Vocabulary map: dimension name -> sorted member values, derived from the
#: contracts enums. Treat as read-only (module constant).
COMMUNICATION360_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "communication_participant_role": tuple(
        sorted(member.value for member in CommunicationParticipantRole)
    ),
    "communication_act_type": tuple(
        sorted(member.value for member in CommunicationActType)
    ),
    "conversation_state": tuple(
        sorted(member.value for member in ConversationState)
    ),
    "agent_consumption_state": tuple(
        sorted(member.value for member in AgentConsumptionState)
    ),
    "authority_state": tuple(
        sorted(member.value for member in AuthorityState)
    ),
    "capability_state": tuple(
        sorted(member.value for member in CapabilityState)
    ),
}

#: Dimension name -> source contracts enum (kept for downstream consumers that
#: need to coerce a seeded value back to a typed enum member).
COMMUNICATION360_DIMENSION_ENUMS: dict[str, type] = {
    "communication_participant_role": CommunicationParticipantRole,
    "communication_act_type": CommunicationActType,
    "conversation_state": ConversationState,
    "agent_consumption_state": AgentConsumptionState,
    "authority_state": AuthorityState,
    "capability_state": CapabilityState,
}


def dimension(name: str) -> tuple[str, ...]:
    """Return the sorted member values for one dimension.

    Raises ``KeyError`` for an unknown dimension name (fail closed).
    """
    return COMMUNICATION360_DIMENSIONS[name]


def is_dimension_value(name: str, value: str) -> bool:
    """Return True when ``value`` is a member of the named dimension."""
    return value in COMMUNICATION360_DIMENSIONS.get(name, ())
