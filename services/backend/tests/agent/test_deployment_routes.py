"""Route-level tests for the external agent deployment APIs."""

from __future__ import annotations

import dataclasses
import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from shared.common.common import BadRequestError, ConflictError, NotFoundError  # noqa: E402
from services.agent.deployment_routes import (  # noqa: E402
    DeploymentCreate,
    DeploymentPatch,
    LifecycleAction,
    archive_deployment,
    create_deployment,
    deployment_activity,
    deployment_health,
    get_deployment,
    kyber_deployment_detail,
    kyber_fleet_overview,
    list_deployments,
    patch_deployment,
    pause_deployment,
    reactivate_deployment,
    revoke_deployment,
)


class FakeTenant:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.permissions = permissions if permissions is not None else {"agent:manage", "admin"}

    def require_permission(self, permission: str) -> None:
        assert permission in self.permissions or "admin" in self.permissions


class FakeRequest:
    def __init__(self, tenant_id: str, permissions: set[str] | None = None):
        self.state = SimpleNamespace(
            tenant=FakeTenant(tenant_id, permissions), request_id=f"req-{tenant_id}"
        )
        self.headers = {}


@pytest.fixture(autouse=True)
def _enable_telemetry_plane(monkeypatch):
    patched = dataclasses.replace(
        settings.external_agent_telemetry,
        enabled=True, registry_enabled=True, kyber_enabled=True,
    )
    monkeypatch.setattr(settings, "external_agent_telemetry", patched)


def _tenant_id() -> str:
    return f"tenant-{uuid.uuid4().hex[:8]}"


def _create_body(**overrides) -> DeploymentCreate:
    payload = {
        "agent_id": "agent-1",
        "display_name": "Discord support bot",
        "external_platform": "discord_bot",
        "environment": "production",
        "allowed_event_families": ["agent"],
    }
    payload.update(overrides)
    return DeploymentCreate(**payload)


# ── CRUD + lifecycle flow ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_pause_reactivate_revoke_archive_flow():
    request = FakeRequest(_tenant_id())

    created = await create_deployment(_create_body(), request)
    dep = created["data"]
    assert dep["status"] == "active"
    dep_id = dep["id"]

    listed = await list_deployments(request)
    assert listed["data"]["count"] == 1

    fetched = await get_deployment(dep_id, request)
    assert fetched["data"]["id"] == dep_id

    paused = await pause_deployment(dep_id, request, LifecycleAction(reason="hold"))
    assert paused["data"]["status"] == "paused"

    reactivated = await reactivate_deployment(dep_id, request)
    assert reactivated["data"]["status"] == "active"

    revoked = await revoke_deployment(dep_id, request)
    assert revoked["data"]["status"] == "revoked"

    # revoked → paused is invalid
    with pytest.raises(ConflictError):
        await pause_deployment(dep_id, request)

    archived = await archive_deployment(dep_id, request)
    assert archived["data"]["status"] == "archived"

    # archived is terminal
    with pytest.raises(ConflictError):
        await reactivate_deployment(dep_id, request)

    activity = await deployment_activity(dep_id, request)
    actions = {a["action"] for a in activity["data"]["audit"]}
    assert {"created", "paused", "reactivated", "revoked", "archived"} <= actions


@pytest.mark.asyncio
async def test_patch_updates_mutable_fields():
    request = FakeRequest(_tenant_id())
    dep_id = (await create_deployment(_create_body(), request))["data"]["id"]

    patched = await patch_deployment(
        dep_id,
        DeploymentPatch(display_name="Renamed", capability_scopes=["observe:messages"]),
        request,
    )
    assert patched["data"]["display_name"] == "Renamed"
    assert patched["data"]["capability_scopes"] == ["observe:messages"]

    with pytest.raises(BadRequestError):
        await patch_deployment(dep_id, DeploymentPatch(), request)


@pytest.mark.asyncio
async def test_list_filters_and_health():
    request = FakeRequest(_tenant_id())
    a = (await create_deployment(_create_body(agent_id="agent-a"), request))["data"]
    b = (await create_deployment(
        _create_body(agent_id="agent-b", external_platform="slack_app"), request
    ))["data"]
    await pause_deployment(b["id"], request)

    only_paused = await list_deployments(request, status="paused")
    assert [d["id"] for d in only_paused["data"]["deployments"]] == [b["id"]]

    only_discord = await list_deployments(request, platform="discord_bot")
    assert [d["id"] for d in only_discord["data"]["deployments"]] == [a["id"]]

    only_agent_b = await list_deployments(request, agent_id="agent-b")
    assert [d["id"] for d in only_agent_b["data"]["deployments"]] == [b["id"]]

    health = await deployment_health(a["id"], request)
    assert health["data"]["status"] == "active"
    assert health["data"]["event_count_24h"] == 0


# ── Tenant isolation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_tenant_access_is_not_found():
    request_a = FakeRequest(_tenant_id())
    request_b = FakeRequest(_tenant_id())
    dep_id = (await create_deployment(_create_body(), request_a))["data"]["id"]

    with pytest.raises(NotFoundError):
        await get_deployment(dep_id, request_b)
    with pytest.raises(NotFoundError):
        await patch_deployment(dep_id, DeploymentPatch(display_name="steal"), request_b)
    with pytest.raises(NotFoundError):
        await pause_deployment(dep_id, request_b)
    with pytest.raises(NotFoundError):
        await deployment_health(dep_id, request_b)

    listed_b = await list_deployments(request_b)
    assert dep_id not in {d["id"] for d in listed_b["data"]["deployments"]}


# ── Flag gating ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_registry_routes_disabled_without_flags(monkeypatch):
    patched = dataclasses.replace(
        settings.external_agent_telemetry,
        enabled=False, registry_enabled=False, kyber_enabled=False,
    )
    monkeypatch.setattr(settings, "external_agent_telemetry", patched)
    request = FakeRequest(_tenant_id())
    with pytest.raises(BadRequestError):
        await list_deployments(request)
    with pytest.raises(BadRequestError):
        await kyber_fleet_overview(request)


# ── Kyber operator routes ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kyber_fleet_overview_aggregates_without_tenant_metadata():
    tenant_a, tenant_b = _tenant_id(), _tenant_id()
    dep_a = (await create_deployment(
        _create_body(metadata={"internal_note": "confidential"}), FakeRequest(tenant_a)
    ))["data"]
    await create_deployment(
        _create_body(external_platform="slack_app"), FakeRequest(tenant_b)
    )

    operator = FakeRequest("olympus_internal", permissions={"admin"})
    overview = (await kyber_fleet_overview(operator))["data"]

    ids = {row["id"] for row in overview["deployments"]}
    assert dep_a["id"] in ids
    assert overview["by_platform"].get("discord_bot", 0) >= 1
    assert overview["by_status"].get("active", 0) >= 2
    for row in overview["deployments"]:
        # Operator fleet rows never carry tenant-private payloads.
        assert "metadata" not in row
        assert "display_name" not in row
        assert "description" not in row
        assert {"id", "tenant_id", "status", "external_platform"} <= set(row)


@pytest.mark.asyncio
async def test_kyber_detail_and_permission_gate():
    tenant_a = _tenant_id()
    dep = (await create_deployment(_create_body(), FakeRequest(tenant_a)))["data"]

    operator = FakeRequest("olympus_internal", permissions={"admin"})
    detail = (await kyber_deployment_detail(tenant_a, dep["id"], operator))["data"]
    assert detail["deployment"]["id"] == dep["id"]
    assert detail["audit_count"] >= 1

    # Non-admin tenants are rejected with 403 (foundation permission pattern).
    non_operator = FakeRequest(tenant_a, permissions={"agent:manage"})
    with pytest.raises(HTTPException) as exc_info:
        await kyber_fleet_overview(non_operator)
    assert exc_info.value.status_code == 403
    with pytest.raises(HTTPException):
        await kyber_deployment_detail(tenant_a, dep["id"], non_operator)
