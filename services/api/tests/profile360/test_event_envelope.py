"""Round-trip tests for the v2 event envelope (additive, optional)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from shared.events.events import Event, EventEnvelopeV2, Topic


def test_v1_event_unchanged():
    event = Event(topic=Topic.PROFILE_UPDATED, payload={"user_id": "u1"})
    raw = event.serialize()
    back = Event.deserialize(raw)
    assert back.version == "1.0"
    assert back.envelope is None
    assert back.payload == {"user_id": "u1"}


def test_v2_envelope_round_trip():
    envelope = EventEnvelopeV2(
        actor={"entity_id": "agent1", "entity_type": "agent"},
        beneficiary={"entity_id": "user1", "entity_type": "human"},
        causality={"triggered_by_event_id": "evt-prev"},
        delegation={"delegation_id": "d1", "scope": {"actions": ["transfer"]}},
        agent_intelligence={"reasoning": "ran budget check", "confidence": 0.85},
        identity_confidence=0.95,
    )
    event = Event(
        topic=Topic.AGENT_EXECUTION_COMPLETED,
        payload={"agent_id": "agent1"},
    ).with_v2(envelope)

    raw = event.serialize()
    back = Event.deserialize(raw)
    assert back.version == "2.0"
    assert back.envelope is not None
    assert back.envelope.actor == {"entity_id": "agent1", "entity_type": "agent"}
    assert back.envelope.causality["triggered_by_event_id"] == "evt-prev"
    assert back.envelope.identity_confidence == 0.95


def test_envelope_omits_none_fields():
    envelope = EventEnvelopeV2(actor={"entity_id": "x", "entity_type": "human"})
    out = envelope.to_dict()
    assert list(out.keys()) == ["actor"]
