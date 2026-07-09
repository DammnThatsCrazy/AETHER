"""Tests for the external agent deployment registry (models + repository)."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import BadRequestError, ConflictError, NotFoundError  # noqa: E402
from services.agent.deployments import (  # noqa: E402
    AgentDeploymentRepository,
    record_event_outcome,
    sanitize_metadata,
    validate_deployment_context,
)


def _tenant() -> str:
    return f"tenant-{uuid.uuid4().hex[:8]}"


def _base_payload(**overrides) -> dict:
    payload = {
        "agent_id": "agent-1",
        "display_name": "Support widget",
        "external_platform": "web_widget",
        "environment": "production",
        "consent_mode": "tenant_managed",
    }
    payload.update(overrides)
    return payload


async def _create(repo: AgentDeploymentRepository, tenant_id: str, **overrides) -> dict:
    return await repo.create(tenant_id, _base_payload(**overrides), actor="tester", request_id="req-1")


# ── Creation + validation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_defaults_to_active_and_writes_audit():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    record = await _create(repo, tenant_id)
    assert record["status"] == "active"
    assert record["tenant_id"] == tenant_id
    assert record["id"]

    audit = await repo.audit_trail(tenant_id, record["id"])
    assert [a["action"] for a in audit] == ["created"]
    assert audit[0]["actor"] == "tester"
    assert audit[0]["request_id"] == "req-1"


@pytest.mark.asyncio
async def test_create_rejects_unknown_platform_environment_consent_mode():
    repo = AgentDeploymentRepository()
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), external_platform="app_store")
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), environment="qa")
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), consent_mode="nobody_managed")


@pytest.mark.asyncio
async def test_create_validates_event_families_and_consent_purposes():
    repo = AgentDeploymentRepository()
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), allowed_event_families=["not_a_family"])
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), required_consent_purposes=["not_a_purpose"])

    # Registry-known values are accepted.
    record = await _create(
        repo, _tenant(),
        allowed_event_families=["agent", "wallet"],
        required_consent_purposes=["analytics"],
    )
    assert record["allowed_event_families"] == ["agent", "wallet"]
    assert record["required_consent_purposes"] == ["analytics"]


@pytest.mark.asyncio
async def test_create_bounds_capability_scopes():
    repo = AgentDeploymentRepository()
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), capability_scopes=["x" * 500])
    with pytest.raises(BadRequestError):
        await _create(repo, _tenant(), capability_scopes=[f"scope-{i}" for i in range(100)])
    record = await _create(repo, _tenant(), capability_scopes=["observe:conversations"])
    assert record["capability_scopes"] == ["observe:conversations"]


# ── Metadata secret sanitization ──────────────────────────────────────────────

def test_sanitize_metadata_strips_secret_keys_recursively():
    dirty = {
        "api_key": "sk-123",
        "Authorization": "Bearer abc",
        "nested": {"client_secret": "x", "webhook_TOKEN": "y", "safe": 1},
        "items": [{"password": "p"}, {"ok": True}],
        "region": "eu-west-1",
    }
    clean, had_secret = sanitize_metadata(dirty)
    assert had_secret is True
    assert clean == {"nested": {"safe": 1}, "items": [{}, {"ok": True}], "region": "eu-west-1"}


@pytest.mark.asyncio
async def test_create_strips_secret_metadata_before_persistence():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    record = await _create(repo, tenant_id, metadata={
        "api_key": "sk-123",
        "deep": {"private_key": "pem", "channel": "support"},
        "team": "growth",
    })
    assert record["metadata"] == {"deep": {"channel": "support"}, "team": "growth"}
    stored = await repo.get(tenant_id, record["id"])
    assert "api_key" not in stored["metadata"]
    assert "private_key" not in stored["metadata"]["deep"]


# ── Lifecycle state machine ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_lifecycle_valid_transitions():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    record = await _create(repo, tenant_id)
    dep_id = record["id"]

    paused = await repo.transition(tenant_id, dep_id, "paused")
    assert paused["status"] == "paused"
    active = await repo.transition(tenant_id, dep_id, "active")
    assert active["status"] == "active"
    errored = await repo.transition(tenant_id, dep_id, "error")
    assert errored["status"] == "error"
    reactivated = await repo.transition(tenant_id, dep_id, "active")
    assert reactivated["status"] == "active"
    revoked = await repo.transition(tenant_id, dep_id, "revoked")
    assert revoked["status"] == "revoked"
    assert revoked["revoked_at"]
    archived = await repo.transition(tenant_id, dep_id, "archived")
    assert archived["status"] == "archived"
    assert archived["archived_at"]


@pytest.mark.asyncio
async def test_invalid_transitions_raise_conflict():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]

    # active → active is not a transition
    with pytest.raises(ConflictError):
        await repo.transition(tenant_id, dep_id, "active")

    await repo.transition(tenant_id, dep_id, "revoked")
    # revoked → only archived
    for target in ("active", "paused", "error"):
        with pytest.raises(ConflictError):
            await repo.transition(tenant_id, dep_id, target)

    await repo.transition(tenant_id, dep_id, "archived")
    # archived is terminal
    for target in ("active", "paused", "revoked", "error"):
        with pytest.raises(ConflictError):
            await repo.transition(tenant_id, dep_id, target)


@pytest.mark.asyncio
async def test_unknown_target_status_is_bad_request():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]
    with pytest.raises(BadRequestError):
        await repo.transition(tenant_id, dep_id, "hibernating")


@pytest.mark.asyncio
async def test_lifecycle_changes_write_audit_records():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]
    await repo.transition(tenant_id, dep_id, "paused", actor="op-1", request_id="req-2", reason="maintenance")
    await repo.transition(tenant_id, dep_id, "active", actor="op-1")
    await repo.transition(tenant_id, dep_id, "revoked", actor="op-2")

    audit = await repo.audit_trail(tenant_id, dep_id)
    actions = {a["action"] for a in audit}
    assert {"created", "paused", "reactivated", "revoked"} <= actions
    paused_record = next(a for a in audit if a["action"] == "paused")
    assert paused_record["detail"]["reason"] == "maintenance"
    assert paused_record["detail"]["from_status"] == "active"
    assert paused_record["actor"] == "op-1"


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_mutable_fields_only():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]

    updated = await repo.update(tenant_id, dep_id, {
        "display_name": "Renamed widget",
        "allowed_event_families": ["agent"],
        "consent_mode": "platform_managed",
    })
    assert updated["display_name"] == "Renamed widget"
    assert updated["allowed_event_families"] == ["agent"]
    assert updated["consent_mode"] == "platform_managed"

    with pytest.raises(BadRequestError):
        await repo.update(tenant_id, dep_id, {"status": "archived"})
    with pytest.raises(BadRequestError):
        await repo.update(tenant_id, dep_id, {"allowed_event_families": ["nope"]})

    audit = await repo.audit_trail(tenant_id, dep_id)
    updated_audit = next(a for a in audit if a["action"] == "updated")
    assert set(updated_audit["detail"]["fields"]) == {
        "allowed_event_families", "consent_mode", "display_name",
    }


@pytest.mark.asyncio
async def test_update_archived_deployment_conflicts():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]
    await repo.transition(tenant_id, dep_id, "archived")
    with pytest.raises(ConflictError):
        await repo.update(tenant_id, dep_id, {"display_name": "too late"})


# ── Tenant isolation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_isolation_not_found_for_other_tenant():
    repo = AgentDeploymentRepository()
    tenant_a, tenant_b = _tenant(), _tenant()
    dep_id = (await _create(repo, tenant_a))["id"]

    with pytest.raises(NotFoundError):
        await repo.get(tenant_b, dep_id)
    with pytest.raises(NotFoundError):
        await repo.transition(tenant_b, dep_id, "paused")
    with pytest.raises(NotFoundError):
        await repo.update(tenant_b, dep_id, {"display_name": "hijack"})

    listed_b = await repo.list(tenant_b)
    assert all(r["tenant_id"] == tenant_b for r in listed_b)
    assert dep_id not in {r["id"] for r in listed_b}


@pytest.mark.asyncio
async def test_list_filters_by_status_platform_agent():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    a = await _create(repo, tenant_id, agent_id="agent-a", external_platform="slack_app")
    b = await _create(repo, tenant_id, agent_id="agent-b", external_platform="discord_bot")
    await repo.transition(tenant_id, b["id"], "paused")

    assert {r["id"] for r in await repo.list(tenant_id)} == {a["id"], b["id"]}
    assert [r["id"] for r in await repo.list(tenant_id, status="paused")] == [b["id"]]
    assert [r["id"] for r in await repo.list(tenant_id, platform="slack_app")] == [a["id"]]
    assert [r["id"] for r in await repo.list(tenant_id, agent_id="agent-b")] == [b["id"]]


# ── validate_deployment_context ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_validate_deployment_context_paths():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    record = await _create(repo, tenant_id, allowed_event_families=["agent", "core"])
    dep_id = record["id"]

    ok, reason = await validate_deployment_context(
        tenant_id, {"deploymentId": dep_id}, event_family="core"
    )
    assert (ok, reason) == (True, "ok")

    # snake_case deployment id key is accepted too
    ok, _ = await validate_deployment_context(
        tenant_id, {"deployment_id": dep_id}, event_family="agent"
    )
    assert ok is True

    ok, reason = await validate_deployment_context(tenant_id, {}, event_family="core")
    assert (ok, reason) == (False, "missing_deployment_id")

    ok, reason = await validate_deployment_context(
        tenant_id, {"deploymentId": "nope"}, event_family="core"
    )
    assert (ok, reason) == (False, "deployment_not_found")

    # Cross-tenant lookup must read as not-found
    ok, reason = await validate_deployment_context(
        _tenant(), {"deploymentId": dep_id}, event_family="core"
    )
    assert (ok, reason) == (False, "deployment_not_found")

    ok, reason = await validate_deployment_context(
        tenant_id, {"deploymentId": dep_id}, event_family="wallet"
    )
    assert (ok, reason) == (False, "event_family_not_allowed")

    await repo.transition(tenant_id, dep_id, "paused")
    ok, reason = await validate_deployment_context(
        tenant_id, {"deploymentId": dep_id}, event_family="core"
    )
    assert (ok, reason) == (False, "deployment_not_active")


@pytest.mark.asyncio
async def test_validate_deployment_context_empty_families_allows_any():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]  # no family restriction declared
    ok, reason = await validate_deployment_context(
        tenant_id, {"deploymentId": dep_id}, event_family="wallet"
    )
    assert (ok, reason) == (True, "ok")


# ── Health counters ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_event_outcome_updates_counters_and_timestamps():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]

    await record_event_outcome(tenant_id, dep_id, "accepted")
    await record_event_outcome(tenant_id, dep_id, "accepted")
    await record_event_outcome(tenant_id, dep_id, "rejected")
    await record_event_outcome(tenant_id, dep_id, "consent_blocked")
    await record_event_outcome(tenant_id, dep_id, "error")

    record = await repo.get(tenant_id, dep_id)
    assert record["event_count_24h"] == 5
    assert record["accepted_count_24h"] == 2
    assert record["rejected_count_24h"] == 1
    assert record["consent_blocked_count_24h"] == 1
    assert record["error_count_24h"] == 1
    assert record["first_seen_at"]
    assert record["last_seen_at"]
    assert record["last_event_at"]
    assert record["counters_reset_at"]


@pytest.mark.asyncio
async def test_record_event_outcome_date_rollover_resets_counters():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]
    await record_event_outcome(tenant_id, dep_id, "accepted")

    # Simulate a stale counter window from a previous UTC day.
    record = await repo.get(tenant_id, dep_id)
    record["counters_reset_at"] = "2000-01-01"
    await repo._store.set(f"{tenant_id}:{dep_id}", record)

    await record_event_outcome(tenant_id, dep_id, "rejected")
    record = await repo.get(tenant_id, dep_id)
    assert record["event_count_24h"] == 1
    assert record["accepted_count_24h"] == 0
    assert record["rejected_count_24h"] == 1


@pytest.mark.asyncio
async def test_record_event_outcome_unknown_outcome_and_missing_deployment():
    repo = AgentDeploymentRepository()
    tenant_id = _tenant()
    dep_id = (await _create(repo, tenant_id))["id"]
    with pytest.raises(BadRequestError):
        await record_event_outcome(tenant_id, dep_id, "vanished")
    # Missing deployment is a silent no-op (ingestion never fails on health bookkeeping).
    await record_event_outcome(tenant_id, "missing-deployment", "accepted")
