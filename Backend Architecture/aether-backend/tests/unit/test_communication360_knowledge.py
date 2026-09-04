"""Unit tests for Communication360 Phase-5 knowledge/context mapping (R4).

Pure-logic coverage of the R4 "delivery is not knowledge" discipline over the
frozen Phase-3 knowledge records and the shipped agentic-observability envelope:

* agent-side consumption markers → ``AgentConsumptionState`` records;
* context-inclusion events → ``ContextInclusionRecord``;
* interpretation events → ``InterpretationRecord`` capped at INFERRED;
* the hard guard ``consumption_from_delivery_state`` always returns UNKNOWN;
* a delivery/engagement observation can never yield
  ingested / parsed / included_in_context / used.
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

from services.communication360.knowledge import (  # noqa: E402
    consumption_from_delivery_state,
    context_inclusion_from_observation,
    interpretation_from_observation,
    knowledge_state_from_observation,
)
from services.communication360.contracts import (  # noqa: E402
    AgentConsumptionState,
    CommunicationState,
)
from services.agentic_observability.models import (  # noqa: E402
    ActionStatus,
    ActorType,
    AgenticObservationRecord,
    AgentRef,
    AutonomyLevel,
    CorrelationRef,
    ObservationAction,
    ObservationActor,
    ObservationObject,
    ObservationProvenance,
    ObservationSource,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402

FACTUAL = {"verified", "resolved", "causally_supported"}
OBSERVED = {"observed", "inferred", "derived"}  # allowed record claim states


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_observation(
    event_name: str,
    *,
    action_name: str = "consume",
    action_outcome: str | None = None,
    object_type: str = "message_content",
    object_id: str = "info_x",
    agent_id: str = "agent-1",
    observation_id: str = "obs-1",
    session_id: str | None = None,
) -> AgenticObservationRecord:
    return AgenticObservationRecord(
        observation_id=observation_id,
        event_name=event_name,
        tenant_id="tenant-a",
        observed_at="2026-09-03T12:00:00Z",
        source=ObservationSource(),
        actor=ObservationActor(actor_type=ActorType.AGENT, actor_id=agent_id),
        agent=AgentRef(
            agent_id=agent_id,
            autonomy_level=AutonomyLevel.AUTONOMOUS_OBSERVED,
        ),
        object=ObservationObject(object_type=object_type, object_id=object_id),
        action=ObservationAction(
            name=action_name,
            status=ActionStatus.OBSERVED,
            outcome=action_outcome,
        ),
        provenance=ObservationProvenance(raw_event_hash="h", normalized_by="unit-test"),
        correlation=CorrelationRef(session_id=session_id),
    )


# ---------------------------------------------------------------------------
# consumption_from_delivery_state — the hard R4 guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "state",
    [
        "sent",
        "delivered",
        "opened",
        "received",
        "clicked",
        "processed",
        "queued",
        "replied",
        CommunicationState.DELIVERED,
        CommunicationState.SENT,
        CommunicationState.OPENED,
    ],
)
def test_consumption_from_delivery_state_is_always_unknown(state: object) -> None:
    # A delivery/engagement state carries no knowledge weight — ever.
    assert consumption_from_delivery_state(state) is AgentConsumptionState.UNKNOWN
    assert consumption_from_delivery_state(state) not in {
        AgentConsumptionState.INGESTED,
        AgentConsumptionState.PARSED,
        AgentConsumptionState.INCLUDED_IN_CONTEXT,
        AgentConsumptionState.USED,
    }


def test_delivery_observation_never_yields_a_knowledge_record() -> None:
    # Even a delivery observation whose object mentions "context" and whose
    # action outcome is ambiguous must not grant recipient knowledge (R4).
    obs = make_observation(
        "email_delivered",
        action_name="deliver",
        action_outcome="message placed in recipient context",
        object_type="context",
        object_id="ctx-1",
    )
    assert knowledge_state_from_observation(obs) is None
    assert context_inclusion_from_observation(obs) is None
    assert interpretation_from_observation(obs) is None


def test_delivery_observation_with_explicit_included_marker_is_still_not_knowledge() -> None:
    flat = {
        "observation_id": "obs-deliv",
        "event_name": "comms.email_sent",
        "tenant_id": "tenant-a",
        "observed_at": "2026-09-03T12:00:00Z",
        "agent_id": "agent-1",
        "action": {"name": "send"},
        "included": True,
    }
    # A message-send observation is a delivery event; the explicit included
    # marker is not an agent-side context observation and must be ignored.
    assert context_inclusion_from_observation(flat) is None
    assert knowledge_state_from_observation(flat) is None


# ---------------------------------------------------------------------------
# Knowledge-state mapping from consumption markers
# ---------------------------------------------------------------------------

def test_used_marker_maps_to_used_state() -> None:
    obs = make_observation(
        "agent.message_used",
        action_name="consume",
        action_outcome="applied constraint",
        object_id="info_request",
    )
    record = knowledge_state_from_observation(obs)
    assert record is not None
    assert record.state is AgentConsumptionState.USED
    assert record.subject_entity_id == "agent-1"
    assert record.tenant_id == "tenant-a"
    assert record.information_ref is not None
    assert record.information_ref.information_id == "info_request"
    assert record.known_since == "2026-09-03T12:00:00Z"
    assert record.claim_state is EpistemicStatus.OBSERVED


def test_ingested_marker_maps_to_ingested_state() -> None:
    obs = make_observation(
        "agent.message_ingested",
        action_name="ingest",
        object_id="info_request",
    )
    record = knowledge_state_from_observation(obs)
    assert record is not None
    assert record.state is AgentConsumptionState.INGESTED


def test_parsed_marker_maps_to_parsed_state() -> None:
    obs = make_observation(
        "agent.attachment_parsed_observed",
        action_name="parse",
        object_id="info_attach",
    )
    record = knowledge_state_from_observation(obs)
    assert record is not None
    assert record.state is AgentConsumptionState.PARSED


def test_context_event_maps_to_included_in_context_knowledge_state() -> None:
    obs = make_observation(
        "agent.context_inclusion",
        action_name="included_in_context",
        object_id="info_request",
        session_id="session-9",
    )
    record = knowledge_state_from_observation(obs)
    assert record is not None
    assert record.state is AgentConsumptionState.INCLUDED_IN_CONTEXT


def test_no_consumption_marker_returns_none() -> None:
    obs = make_observation("agent.task_started", action_name="start", object_id="task_1")
    assert knowledge_state_from_observation(obs) is None
    assert context_inclusion_from_observation(obs) is None


def test_no_agent_resolvable_returns_none() -> None:
    flat = {
        "observation_id": "obs-null",
        "event_name": "agent.message_used",
        "tenant_id": "tenant-a",
        "observed_at": "2026-09-03T12:00:00Z",
    }
    assert knowledge_state_from_observation(flat) is None


# ---------------------------------------------------------------------------
# Context-inclusion mapping
# ---------------------------------------------------------------------------

def test_context_inclusion_event_builds_record() -> None:
    obs = make_observation(
        "agent.context_inclusion",
        action_name="included_in_context",
        object_id="info_request",
        session_id="session-9",
    )
    record = context_inclusion_from_observation(obs)
    assert record is not None
    assert record.included is True
    assert record.agent_entity_id == "agent-1"
    assert record.tenant_id == "tenant-a"
    assert record.source_observation_id == "obs-1"
    assert record.context_ref == "session-9"
    assert record.claim_state is EpistemicStatus.OBSERVED
    assert len(record.evidence_refs) == 1


def test_explicit_included_true_marker_on_plain_dict() -> None:
    flat = {
        "observation_id": "obs-ctx",
        "event_name": "agent.context_inclusion",
        "tenant_id": "tenant-a",
        "observed_at": "2026-09-03T12:00:00Z",
        "agent_id": "agent-1",
        "context_ref": "session-9",
        "included": True,
    }
    record = context_inclusion_from_observation(flat)
    assert record is not None
    assert record.included is True
    assert record.context_ref == "session-9"


def test_explicit_included_false_records_exclusion() -> None:
    flat = {
        "observation_id": "obs-excl",
        "event_name": "agent.context_update",
        "tenant_id": "tenant-a",
        "observed_at": "2026-09-03T12:00:00Z",
        "agent_id": "agent-1",
        "included": False,
    }
    record = context_inclusion_from_observation(flat)
    assert record is not None
    assert record.included is False


def test_context_word_alone_is_not_a_context_event() -> None:
    obs = make_observation(
        "agent.message_used",
        action_name="consume",
        object_type="context",  # context appears only as the object type
        object_id="ctx-1",
    )
    assert context_inclusion_from_observation(obs) is None


# ---------------------------------------------------------------------------
# Interpretation mapping
# ---------------------------------------------------------------------------

def test_derived_content_event_maps_to_interpretation() -> None:
    obs = make_observation(
        "agent.derived_content_recorded",
        action_name="derive",
        action_outcome="wrote a summary of the request",
        object_type="summary",
        object_id="info_summary",
    )
    record = interpretation_from_observation(obs)
    assert record is not None
    assert record.agent_entity_id == "agent-1"
    assert record.claim_state is EpistemicStatus.INFERRED
    assert record.claim_state not in {EpistemicStatus.VERIFIED, EpistemicStatus.RESOLVED, EpistemicStatus.CAUSALLY_SUPPORTED}
    assert record.text is not None and "summary" in record.text


def test_interpretation_event_maps_to_interpretation() -> None:
    obs = make_observation(
        "agent.interpretation_recorded",
        action_name="interpret",
        action_outcome="interpreted intent",
        object_id="info_request",
    )
    record = interpretation_from_observation(obs)
    assert record is not None
    assert record.claim_state is EpistemicStatus.INFERRED


def test_non_interpretation_event_returns_none() -> None:
    obs = make_observation("agent.message_used", action_name="consume")
    assert interpretation_from_observation(obs) is None


# ---------------------------------------------------------------------------
# Epistemic capping — no record claims a factual status
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "event_name,action_name,builder",
    [
        ("agent.message_used", "consume", knowledge_state_from_observation),
        ("agent.context_inclusion", "included_in_context", context_inclusion_from_observation),
        ("agent.derived_content_recorded", "derive", interpretation_from_observation),
    ],
)
def test_no_record_in_factual_band(
    event_name: str,
    action_name: str,
    builder: object,
) -> None:
    obs = make_observation(event_name, action_name=action_name, object_id="info_x")
    record = builder(obs)  # type: ignore[operator]
    assert record is not None
    assert record.claim_state is not None
    assert record.claim_state.value not in FACTUAL
