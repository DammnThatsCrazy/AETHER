"""Validated agents become non-resolving source identities (WO-013)."""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from actions.agent.deployments import get_deployment_repository
from identity.identity import ingestion_worker
from identity.identity.pending_review import PendingIdentityReviewRepository
from identity.identity.routes import get_identity_resolver
from identity.identity.source_identity_registry import SourceIdentityRegistry
from shared.events.events import Event, Topic


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _event(tenant, event_id, marker=None, namespace=None):
    body = {"event_id": event_id, "event_type": "agent_tool_invocation_observed", "tenant_id": tenant,
            "properties": {"agentId": "spoofed-agent", "toolName": "search"},
            "context": {"identity_namespace": namespace} if namespace else {}}
    if marker is not None:
        body["validated_agent_deployment"] = marker
    return Event(topic=Topic.SDK_EVENTS_VALIDATED, payload=body, tenant_id=tenant)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "identity_continuity",
                        dataclasses.replace(settings.identity_continuity, resolution_enabled=True))


async def _deployment(tenant, agent_id, **extra):
    return await get_deployment_repository().create(tenant, {
        "agent_id": agent_id, "display_name": "bot", "external_platform": "web_widget",
        "environment": "production", "consent_mode": "tenant_managed", **extra,
    }, actor="t", request_id="r")


async def _lookup(tenant, agent_id, deployment_id):
    repo = get_identity_resolver()._repo
    return await SourceIdentityRegistry(repo).find_existing_source_identity(
        tenant, source_namespace=f"tenant:{tenant}:agent:deployment:{deployment_id}", agent_id=agent_id)


@pytest.mark.asyncio
async def test_validated_agent_is_registered_from_the_registry_and_never_resolved():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    dep = await _deployment(tenant, "registry-agent")
    producer = _Producer()
    # The marker's agent id is ignored; the registry record is authoritative.
    marker = {"deployment_id": dep["id"], "agent_id": "forged-agent"}
    await ingestion_worker.resolve_sdk_observation(_event(tenant, "ev-a1", marker, namespace="evil-ns"), producer)
    await ingestion_worker.resolve_sdk_observation(_event(tenant, "ev-a2", marker), producer)
    src = await _lookup(tenant, "registry-agent", dep["id"])
    assert src is not None and not src.canonical_entity_id
    assert producer.events == []
    assert await _lookup(tenant, "forged-agent", dep["id"]) is None


@pytest.mark.asyncio
async def test_unknown_or_inactive_deployments_create_no_identity():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    await ingestion_worker.resolve_sdk_observation(_event(tenant, "ev-b1"), _Producer())
    await ingestion_worker.resolve_sdk_observation(
        _event(tenant, "ev-b2", {"deployment_id": "not-registered", "agent_id": "x"}), _Producer())
    repo = get_identity_resolver()._repo
    assert await repo.list_source_identities_by_identifier(tenant, "agent_id", "x") == []


@pytest.mark.asyncio
async def test_same_agent_ref_from_two_deployments_queues_a_continuity_review():
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    a = await _deployment(tenant, "shared-ref")
    b = await _deployment(tenant, "shared-ref", external_platform="slack_app")
    await ingestion_worker.resolve_sdk_observation(_event(tenant, "ev-c1", {"deployment_id": a["id"], "agent_id": "shared-ref"}), _Producer())
    await ingestion_worker.resolve_sdk_observation(_event(tenant, "ev-c2", {"deployment_id": b["id"], "agent_id": "shared-ref"}), _Producer())
    pending = PendingIdentityReviewRepository()
    assert await pending.list_open(tenant) == [], "agent items stay out of the late-binding queue"
    items = await pending.list_for_review(tenant, entry_type="agent_continuity_candidate")
    assert len(items) == 1
    assert await pending.get(tenant, items[0]["id"]) is None, "approve/merge routes cannot load it"
    assert (await pending.get(tenant, items[0]["id"], entry_type="agent_continuity_candidate"))["id"] == items[0]["id"]
    item = items[0]
    assert item["reason_codes"] == ["agent_ref_reported_by_multiple_deployments"]
    assert item["authority"] == "none" and item["status"] == "open"
    sa, sb = await _lookup(tenant, "shared-ref", a["id"]), await _lookup(tenant, "shared-ref", b["id"])
    assert sa.id != sb.id and not sa.canonical_entity_id and not sb.canonical_entity_id


@pytest.mark.asyncio
async def test_pending_review_rejects_unknown_entry_types():
    with pytest.raises(ValueError):
        await PendingIdentityReviewRepository().upsert_candidate(
            tenant_id="t", identify_source_identity_id="s", candidate_source_identity_ids=["c"],
            reason_codes=["r"], evidence=[], entry_type="merge_now")
