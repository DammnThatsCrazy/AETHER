"""Tests for the agent worker-team registry routes."""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        sys.modules.pop(prefix, None)
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            sys.modules.pop(prefix, None)
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def teams_routes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        mod = importlib.import_module("services.agent.teams_routes")
        importlib.reload(mod)
        # reset in-memory stores between tests
        mod._team_store._data.clear()
        mod._team_store._lists.clear()
        mod._team_lifecycle_store._data.clear()
        mod._team_lifecycle_store._lists.clear()
        mod._task_store._data.clear()
        yield mod


def make_request(tenant_id: str = "t-001"):
    """Build a minimal Request-like object with a tenant attribute."""
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        require_permission=lambda perm: None,
    )
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.mark.asyncio
async def test_create_team_with_valid_name(teams_routes):
    body = teams_routes.TeamCreate(name="discovery", member_agent_ids=["a-1", "a-2"])
    result = await teams_routes.create_team(body, make_request())
    data = result["data"]
    assert data["name"] == "discovery"
    assert data["status"] == "active"
    assert len(data["members"]) == 2
    assert {m["role"] for m in data["members"]} == {"worker"}


@pytest.mark.asyncio
async def test_create_team_rejects_unknown_name(teams_routes):
    body = teams_routes.TeamCreate(name="bogus")
    with pytest.raises(Exception) as exc_info:
        await teams_routes.create_team(body, make_request())
    assert "Invalid team name" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_team_with_coordinator_outside_members(teams_routes):
    body = teams_routes.TeamCreate(
        name="enrichment",
        coordinator_agent_id="coord-1",
        member_agent_ids=["a-1"],
    )
    result = await teams_routes.create_team(body, make_request())
    data = result["data"]
    roles = {m["agent_id"]: m["role"] for m in data["members"]}
    assert roles == {"a-1": "worker", "coord-1": "coordinator"}


@pytest.mark.asyncio
async def test_list_teams_filters_by_tenant(teams_routes):
    await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request("t-001")
    )
    await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request("t-002")
    )
    result = await teams_routes.list_teams(make_request("t-001"))
    assert result["data"]["count"] == 1
    assert result["data"]["teams"][0]["tenant_id"] == "t-001"


@pytest.mark.asyncio
async def test_get_team_returns_load_snapshot(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="verification"), make_request()
    )
    team_id = create["data"]["team_id"]
    result = await teams_routes.get_team(team_id, make_request())
    assert "load" in result["data"]
    assert result["data"]["load"]["total_tasks"] == 0
    assert result["data"]["load"]["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_get_team_404_for_unknown(teams_routes):
    with pytest.raises(Exception) as exc_info:
        await teams_routes.get_team("does-not-exist", make_request())
    assert "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_add_and_remove_member(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="commit"), make_request()
    )
    team_id = create["data"]["team_id"]

    add = await teams_routes.add_member(
        team_id, teams_routes.TeamMemberAdd(agent_id="a-9"), make_request()
    )
    assert any(m["agent_id"] == "a-9" for m in add["data"]["members"])

    remove = await teams_routes.remove_member(team_id, "a-9", make_request())
    assert all(m["agent_id"] != "a-9" for m in remove["data"]["members"])


@pytest.mark.asyncio
async def test_add_duplicate_member_fails(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="recovery", member_agent_ids=["a-1"]),
        make_request(),
    )
    team_id = create["data"]["team_id"]
    with pytest.raises(Exception) as exc_info:
        await teams_routes.add_member(
            team_id, teams_routes.TeamMemberAdd(agent_id="a-1"), make_request()
        )
    assert "already in team" in str(exc_info.value)


@pytest.mark.asyncio
async def test_lifecycle_event_recording(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request()
    )
    team_id = create["data"]["team_id"]

    await teams_routes.record_lifecycle(
        team_id,
        teams_routes.TeamLifecycleEvent(event_type="started"),
        make_request(),
    )
    listed = await teams_routes.list_lifecycle(team_id, make_request())
    events = listed["data"]["events"]
    assert any(e["event_type"] == "started" for e in events)


@pytest.mark.asyncio
async def test_lifecycle_invalid_event_type(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request()
    )
    team_id = create["data"]["team_id"]
    with pytest.raises(Exception) as exc_info:
        await teams_routes.record_lifecycle(
            team_id,
            teams_routes.TeamLifecycleEvent(event_type="bogus_event"),
            make_request(),
        )
    assert "Invalid event_type" in str(exc_info.value)


@pytest.mark.asyncio
async def test_update_team_status(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request()
    )
    team_id = create["data"]["team_id"]
    body = teams_routes.TeamUpdate(status="paused")
    result = await teams_routes.update_team(team_id, body, make_request())
    assert result["data"]["status"] == "paused"


@pytest.mark.asyncio
async def test_update_team_invalid_status(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request()
    )
    team_id = create["data"]["team_id"]
    body = teams_routes.TeamUpdate(status="bogus")
    with pytest.raises(Exception) as exc_info:
        await teams_routes.update_team(team_id, body, make_request())
    assert "Invalid status" in str(exc_info.value)


@pytest.mark.asyncio
async def test_load_snapshot_computes_error_rate(teams_routes):
    create = await teams_routes.create_team(
        teams_routes.TeamCreate(name="discovery"), make_request()
    )
    team_id = create["data"]["team_id"]

    await teams_routes._task_store.set(
        "task-1", {"tenant_id": "t-001", "worker_type": "discovery_alpha", "status": "completed"}
    )
    await teams_routes._task_store.set(
        "task-2", {"tenant_id": "t-001", "worker_type": "discovery_beta", "status": "failed"}
    )
    await teams_routes._task_store.set(
        "task-3", {"tenant_id": "t-001", "worker_type": "enrichment_x", "status": "completed"}
    )

    result = await teams_routes.get_load(team_id, make_request())
    load = result["data"]
    assert load["total_tasks"] == 2
    assert load["completed"] == 1
    assert load["failed"] == 1
    assert load["error_rate"] == 0.5
