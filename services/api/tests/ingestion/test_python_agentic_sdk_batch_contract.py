"""The Python SDK's behavior-event helper must emit events /v1/batch accepts.

``BaseEvent`` requires ``id``, ``sessionId`` and ``anonymousId`` and forbids
unknown keys. The helper used to emit ``messageId`` without either identity
field, so every batch built with it answered 422 (Codex review on #867).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from ingestion.ingestion.batch import BaseEvent

SDK = Path(__file__).resolve().parents[4] / "packages/sdk/python/aether_agentic/agentic.py"


def _sdk():
    spec = importlib.util.spec_from_file_location("aether_agentic_contract", SDK)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def test_behavior_event_validates_against_the_batch_event_model():
    sdk = _sdk()
    dep = {"deploymentId": "dep-1", "agentId": "a1", "externalPlatform": "mcp_server",
           "environment": "production", "consentMode": "tenant_managed"}
    for extra in ({}, {"user_id": "u-1"}):
        event = sdk.build_behavior_event(
            event_type="agent_quote_received", agent_id="a1", message_id="m1",
            timestamp="2026-10-22T10:00:00Z", session_id="s1", anonymous_id="anon-1",
            properties={"amount": "10.5"}, deployment=dep, **extra)
        parsed = BaseEvent.model_validate(event)
        assert (parsed.id, parsed.sessionId, parsed.anonymousId) == ("m1", "s1", "anon-1")
        assert parsed.userId == extra.get("user_id")
        assert parsed.context.agentDeployment["deploymentId"] == "dep-1"
