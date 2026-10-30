"""Validated agents become non-resolving source identities (WO-013)."""
from __future__ import annotations

import dataclasses

import pytest

from identity.identity import ingestion_worker
from identity.identity.routes import get_identity_resolver
from identity.identity.source_identity_registry import SourceIdentityRegistry
from shared.events.events import Event, Topic

T = "tenant-agent-src"


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _event(event_id, marker=None, **payload):
    body = {"event_id": event_id, "event_type": "agent_tool_invocation_observed", "tenant_id": T,
            "properties": {"agentId": "spoofed-agent", "toolName": "search"}, "context": {}, **payload}
    if marker is not None:
        body["validated_agent_deployment"] = marker
    return Event(topic=Topic.SDK_EVENTS_VALIDATED, payload=body, tenant_id=T)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "identity_continuity",
                        dataclasses.replace(settings.identity_continuity, resolution_enabled=True))


async def _lookup(agent_id, deployment_id):
    repo = get_identity_resolver()._repo
    return await SourceIdentityRegistry(repo).find_existing_source_identity(
        T, source_namespace=f"tenant:{T}:agent:deployment:{deployment_id}", agent_id=agent_id)


@pytest.mark.asyncio
async def test_validated_agent_is_registered_once_and_never_resolved():
    producer = _Producer()
    marker = {"deployment_id": "dep-7", "agent_id": "registry-agent"}
    await ingestion_worker.resolve_sdk_observation(_event("ev-a1", marker), producer)
    await ingestion_worker.resolve_sdk_observation(_event("ev-a2", marker), producer)
    src = await _lookup("registry-agent", "dep-7")
    assert src is not None and src.agent_id == "registry-agent"
    assert not src.canonical_entity_id, "an agent source identity is never resolved to a person"
    assert producer.events == [], "no identity-resolved event for an agent-only observation"
    assert await _lookup("spoofed-agent", "dep-7") is None, "the registry agent id wins over the payload"


@pytest.mark.asyncio
async def test_unvalidated_agent_refs_create_no_identity():
    await ingestion_worker.resolve_sdk_observation(_event("ev-b1"), _Producer())
    await ingestion_worker.resolve_sdk_observation(
        _event("ev-b2", {"deployment_id": "dep-8"}), _Producer())
    assert await _lookup("spoofed-agent", "dep-8") is None
