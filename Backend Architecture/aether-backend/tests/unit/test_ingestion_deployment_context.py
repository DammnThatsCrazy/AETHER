"""Tests for deployment-context validation and canonical ID stripping in batch ingestion."""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.agent.deployments import AgentDeploymentRepository  # noqa: E402
from services.ingestion.batch import (  # noqa: E402
    BaseEvent,
    EventContext,
    REJECT_DEPLOYMENT_CONTEXT,
    _build_normalized_payload,
    _process_single_event,
)
from services.ingestion.generated_registry import EVENT_FAMILY  # noqa: E402

TRACK_FAMILY = EVENT_FAMILY.get("track", "core")
OTHER_FAMILY = "wallet" if TRACK_FAMILY != "wallet" else "agent"


class FakeCache:
    """Idempotency-check stub: nothing is ever a duplicate."""

    async def get(self, key: str):
        return None


def _tenant() -> str:
    return f"tenant-{uuid.uuid4().hex[:8]}"


def _event(deployment_ctx: dict | None = None, **overrides) -> BaseEvent:
    context = EventContext(agentDeployment=deployment_ctx) if deployment_ctx else EventContext()
    payload = {
        "id": f"evt-{uuid.uuid4().hex[:8]}",
        "type": "track",
        "timestamp": "2026-07-09T00:00:00Z",
        "sessionId": "sess-1",
        "anonymousId": "anon-1",
        "properties": {},
        "context": context,
    }
    payload.update(overrides)
    return BaseEvent(**payload)


async def _process(event: BaseEvent, tenant_id: str):
    return await _process_single_event(
        sdk_event=event,
        tenant_id=tenant_id,
        batch_id="batch-1",
        received_at="2026-07-09T00:00:00+00:00",
        cache=FakeCache(),
    )


async def _seed_deployment(tenant_id: str, **overrides) -> dict:
    repo = AgentDeploymentRepository()
    payload = {
        "agent_id": "agent-1",
        "display_name": "Widget",
        "external_platform": "web_widget",
        "allowed_event_families": [TRACK_FAMILY],
    }
    payload.update(overrides)
    return await repo.create(tenant_id, payload)


@pytest.fixture
def flag_on(monkeypatch):
    patched = dataclasses.replace(settings.external_agent_telemetry, enabled=True)
    monkeypatch.setattr(settings, "external_agent_telemetry", patched)


@pytest.fixture
def flag_off(monkeypatch):
    patched = dataclasses.replace(settings.external_agent_telemetry, enabled=False)
    monkeypatch.setattr(settings, "external_agent_telemetry", patched)


# ── Flag ON: deployment-context validation ────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_deployment_context_accepted_and_counted(flag_on):
    tenant_id = _tenant()
    deployment = await _seed_deployment(tenant_id)
    result = await _process(_event({"deploymentId": deployment["id"]}), tenant_id)
    assert result.status == "accepted"
    assert result.reason is None

    record = await AgentDeploymentRepository().get(tenant_id, deployment["id"])
    assert record["accepted_count_24h"] == 1
    assert record["event_count_24h"] == 1
    assert record["last_event_at"]


@pytest.mark.asyncio
async def test_snake_case_deployment_context_accepted(flag_on):
    tenant_id = _tenant()
    deployment = await _seed_deployment(tenant_id)
    event = _event(None)
    event.context.agent_deployment = {"deployment_id": deployment["id"]}
    result = await _process(event, tenant_id)
    assert result.status == "accepted"


@pytest.mark.asyncio
async def test_unknown_deployment_rejected(flag_on):
    tenant_id = _tenant()
    result = await _process(_event({"deploymentId": "does-not-exist"}), tenant_id)
    assert result.status == "rejected"
    assert result.reason == f"{REJECT_DEPLOYMENT_CONTEXT}:deployment_not_found"


@pytest.mark.asyncio
async def test_revoked_deployment_rejected_and_counted(flag_on):
    tenant_id = _tenant()
    repo = AgentDeploymentRepository()
    deployment = await _seed_deployment(tenant_id)
    await repo.transition(tenant_id, deployment["id"], "revoked")

    result = await _process(_event({"deploymentId": deployment["id"]}), tenant_id)
    assert result.status == "rejected"
    assert result.reason == f"{REJECT_DEPLOYMENT_CONTEXT}:deployment_not_active"

    record = await repo.get(tenant_id, deployment["id"])
    assert record["rejected_count_24h"] == 1


@pytest.mark.asyncio
async def test_disallowed_event_family_rejected(flag_on):
    tenant_id = _tenant()
    deployment = await _seed_deployment(tenant_id, allowed_event_families=[OTHER_FAMILY])
    result = await _process(_event({"deploymentId": deployment["id"]}), tenant_id)
    assert result.status == "rejected"
    assert result.reason == f"{REJECT_DEPLOYMENT_CONTEXT}:event_family_not_allowed"


@pytest.mark.asyncio
async def test_cross_tenant_deployment_reads_as_not_found(flag_on):
    tenant_a, tenant_b = _tenant(), _tenant()
    deployment = await _seed_deployment(tenant_a)
    result = await _process(_event({"deploymentId": deployment["id"]}), tenant_b)
    assert result.status == "rejected"
    assert result.reason == f"{REJECT_DEPLOYMENT_CONTEXT}:deployment_not_found"


@pytest.mark.asyncio
async def test_event_without_deployment_context_unaffected(flag_on):
    result = await _process(_event(None), _tenant())
    assert result.status == "accepted"


# ── Flag OFF: exactly as before ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flag_off_ignores_deployment_context(flag_off):
    tenant_id = _tenant()
    # Even an unknown deployment id passes through untouched when the plane is off.
    result = await _process(_event({"deploymentId": "does-not-exist"}), tenant_id)
    assert result.status == "accepted"
    assert result.reason is None


@pytest.mark.asyncio
async def test_flag_off_plain_event_accepted(flag_off):
    result = await _process(_event(None), _tenant())
    assert result.status == "accepted"


# ── canonical_entity_id stripping (flag-independent) ──────────────────────────

def test_canonical_entity_id_stripped_from_normalized_payload():
    event = _event(None, properties={
        "canonical_entity_id": "spoofed",
        "nested": {"canonicalEntityId": "spoofed-camel", "keep": 1},
        "items": [{"canonical_entity_id": "spoofed-list"}],
        "plan": "pro",
    })
    event.context.provenance = {"canonical_entity_id": "spoofed-ctx", "source": "sdk"}

    normalized = _build_normalized_payload(
        sdk_event=event,
        tenant_id="tenant-x",
        batch_id="batch-1",
        received_at="2026-07-09T00:00:00+00:00",
    )
    props = normalized["properties"]
    assert "canonical_entity_id" not in props
    assert "canonicalEntityId" not in props["nested"]
    assert props["nested"]["keep"] == 1
    assert props["items"] == [{}]
    assert props["plan"] == "pro"
    assert "canonical_entity_id" not in normalized["context"].get("provenance", {})
    assert normalized["context"]["provenance"]["source"] == "sdk"
