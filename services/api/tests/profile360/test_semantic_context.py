"""Tests for the additive Semantic Context Intelligence Layer."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from shared.events.events import Event, EventEnvelopeV2, Topic
from shared.semantic_context import (
    RelationshipKind,
    RelationshipRef,
    SemanticContextEnvelope,
    SemanticDelta,
    SemanticEpisodeHeuristics,
    SemanticLayer,
)


def test_pulse_envelope_is_transient_and_not_vectorized():
    envelope = SemanticContextEnvelope(
        primary_layer=SemanticLayer.PULSE,
        confidence=0.91,
        compressed_payload={"symbol": "checkout"},
    )

    out = envelope.to_dict()

    assert out["primary_layer"] == "pulse"
    assert out["persistence"]["class"] == "transient"
    assert out["enrichment"]["vectorize"] is False
    assert envelope.should_vectorize() is False


def test_semantic_envelope_attaches_without_mutating_record():
    record = {"id": "evt-1", "type": "track"}
    envelope = SemanticContextEnvelope(
        primary_layer=SemanticLayer.SEMANTIC,
        confidence=0.86,
        semantic_deltas=(SemanticDelta("intent", "inferred", "checkout risk review", 0.82),),
        relationship_refs=(
            RelationshipRef(RelationshipKind.SEMANTICALLY_SIMILAR, "sir:checkout", 0.74, 0.81),
        ),
    )

    attached = envelope.attach_to(record)

    assert "semantic_context" not in record
    assert attached["semantic_context"]["semantic_deltas"][0]["field"] == "intent"
    assert envelope.should_vectorize() is True


def test_episode_heuristics_infer_auth_workflow():
    episode = SemanticEpisodeHeuristics.infer(
        [
            {"path": "auth.ts", "text": "jwt validation", "timestamp_ms": 1000},
            {"path": "gateway.rs", "text": "session auth hardening", "timestamp_ms": 2000},
            {"path": "jwt.rs", "text": "oauth token rotation", "timestamp_ms": 3000},
        ],
        tenant_id="tenant-a",
    )

    assert episode is not None
    assert episode.label == "Authentication Hardening Workflow"
    assert episode.confidence > 0.7
    assert len(episode.relationship_refs) == 3


def test_event_envelope_accepts_semantic_context_block():
    semantic = SemanticContextEnvelope(
        primary_layer=SemanticLayer.WORKFLOW,
        confidence=0.78,
        workflow_refs=("wf:auth-hardening",),
    )
    event = Event(
        topic=Topic.AGENT_EXECUTION_COMPLETED,
        payload={"agent_id": "agent1"},
    ).with_v2(EventEnvelopeV2(semantic_context=semantic.to_dict()))

    back = Event.deserialize(event.serialize())

    assert back.version == "2.0"
    assert back.envelope is not None
    assert back.envelope.semantic_context is not None
    assert back.envelope.semantic_context["primary_layer"] == "workflow"
