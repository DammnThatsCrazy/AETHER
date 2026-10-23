"""Spawn-lineage tree: orchestrator -> sub-agents -> tool calls and outcomes."""

from __future__ import annotations

from actions.agent.lineage import (
    MAX_DEPTH, agent_refs_in_tree, build_lineage_tree,
)

T = "tenant-a"


def _spawn(parent, child, at, **extra):
    return {
        "tenant_id": T, "source_event_type": "agent_subagent_spawned",
        "agent_id": parent, "parent_agent_ref": parent, "child_agent_ref": child,
        "occurred_at": at, "source_event_id": f"ev-{parent}-{child}", **extra,
    }


def _tool(agent, tool, at, run="run-1"):
    return {
        "tenant_id": T, "event_name": "agent_tool_invocation_observed",
        "agent_id": agent, "tool_name": tool, "occurred_at": at, "run_id": run,
    }


def test_three_level_tree_with_rollups():
    spawns = [
        _spawn("orch", "sub-1", "2026-10-22T10:00:01Z"),
        _spawn("orch", "sub-2", "2026-10-22T10:00:02Z"),
        _spawn("sub-1", "leaf-1", "2026-10-22T10:00:03Z"),
    ]
    activity = {
        "sub-1": [_tool("sub-1", "wallet_scan", "2026-10-22T10:01:00Z")],
        "sub-2": [
            _tool("sub-2", "wallet_scan", "2026-10-22T10:01:10Z"),
            _tool("sub-2", "wallet_scan", "2026-10-22T10:01:11Z"),
            {"tenant_id": T, "event_name": "agent_task_completed", "agent_id": "sub-2",
             "outcome": "completed", "occurred_at": "2026-10-22T10:02:00Z"},
        ],
    }
    out = build_lineage_tree(
        tenant_id=T, root_agent_ref="orch", spawn_rows=spawns, activity_rows=activity
    )
    assert out["totals"]["agent_count"] == 4
    assert out["totals"]["max_depth"] == 2
    assert out["totals"]["tool_call_count"] == 3
    assert out["attribution"] == "none"
    assert [c["agent_ref"] for c in out["tree"]["children"]] == ["sub-1", "sub-2"]
    sub2 = out["tree"]["children"][1]
    assert sub2["activity"]["tools"] == [{"tool_name": "wallet_scan", "calls": 2}]
    assert sub2["activity"]["outcomes"] == {"completed": 1}
    assert sub2["spawned_by"]["evidence_status"] == "source_reported"
    assert set(agent_refs_in_tree(out["tree"])) == {"orch", "sub-1", "sub-2", "leaf-1"}


def test_cross_tenant_rows_and_self_spawns_are_ignored():
    spawns = [
        _spawn("orch", "sub-1", "2026-10-22T10:00:01Z"),
        {**_spawn("orch", "intruder", "2026-10-22T10:00:02Z"), "tenant_id": "other"},
        _spawn("orch", "orch", "2026-10-22T10:00:03Z"),
    ]
    out = build_lineage_tree(tenant_id=T, root_agent_ref="orch", spawn_rows=spawns)
    assert [c["agent_ref"] for c in out["tree"]["children"]] == ["sub-1"]


def test_cycles_do_not_loop_and_are_reported():
    spawns = [_spawn("a", "b", "t1"), _spawn("b", "c", "t2"), _spawn("c", "a", "t3")]
    out = build_lineage_tree(tenant_id=T, root_agent_ref="a", spawn_rows=spawns)
    assert out["totals"]["agent_count"] == 3
    assert out["cycles_ignored"] == [{"parent": "c", "child": "a"}]


def test_depth_and_node_bounds_are_reported():
    chain = [_spawn(f"n{i}", f"n{i + 1}", f"t{i:02d}") for i in range(MAX_DEPTH + 3)]
    out = build_lineage_tree(tenant_id=T, root_agent_ref="n0", spawn_rows=chain)
    assert out["totals"]["max_depth"] == MAX_DEPTH
    assert out["truncated"] == ["max_depth"]
    wide = [_spawn("root", f"c{i:03d}", f"t{i:03d}") for i in range(20)]
    out = build_lineage_tree(
        tenant_id=T, root_agent_ref="root", spawn_rows=wide, max_nodes=5
    )
    assert out["totals"]["agent_count"] == 5
    assert out["truncated"] == ["max_nodes"]


def test_unknown_root_is_a_single_node_tree():
    out = build_lineage_tree(tenant_id=T, root_agent_ref="ghost", spawn_rows=[])
    assert out["totals"]["agent_count"] == 1
    assert out["tree"]["children"] == []


import dataclasses
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_lineage_route_is_tenant_scoped_and_reads_activity(monkeypatch):
    import actions.agent.deployment_routes as routes_module
    from actions.agent.deployment_routes import agent_spawn_lineage
    from repositories.repos import AnalyticsRepository

    # Patch the settings object the route module actually holds: other tests
    # reload config.settings, so importing it here can yield a different object.
    settings = routes_module.settings

    calls = []

    async def query_silver(self, table, filters, *, limit=50):
        calls.append(dict(filters))
        if filters.get("source_event_type") == "agent_subagent_spawned":
            return [_spawn("orch", "sub-1", "2026-10-22T10:00:01Z")]
        if filters.get("agent_id") == "sub-1":
            return [_tool("sub-1", "wallet_scan", "2026-10-22T10:01:00Z")]
        return []

    monkeypatch.setattr(AnalyticsRepository, "query_silver", query_silver)
    monkeypatch.setattr(
        settings, "external_agent_telemetry",
        dataclasses.replace(settings.external_agent_telemetry, enabled=True, registry_enabled=True),
    )
    request = SimpleNamespace(state=SimpleNamespace(
        tenant=SimpleNamespace(tenant_id=T, user_id="u", require_permission=lambda _: None),
    ))
    response = await agent_spawn_lineage("orch", request, max_depth=8)
    data = response["data"]
    assert data["source_status"] == "available"
    assert data["totals"]["tool_call_count"] == 1
    assert all(f["tenant_id"] == T for f in calls)
