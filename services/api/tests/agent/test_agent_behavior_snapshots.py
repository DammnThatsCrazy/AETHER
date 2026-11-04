"""Stored BehaviorSnapshots and drift over stored windows (WO-100)."""
from __future__ import annotations

import pytest

from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior.facts import normalize_rows
from intelligence.agent_behavior.snapshot_store import (
    BehaviorSnapshotRepository, drift_over_stored_windows, record_window, snapshot_id,
)
from repositories.repos import reset_in_memory_stores

T = "tenant-snap"
D1, D2 = ("2026-10-22T00:00:00Z", "2026-10-23T00:00:00Z"), ("2026-10-23T00:00:00Z", "2026-10-24T00:00:00Z")


def facts(day, status, tenant=T, n=30):
    rows = []
    for i in range(n):
        rows.extend(AgentExecutionProjector().project({
            "messageId": f"{tenant}-{day}-{i:03d}", "type": "agent_tool_invocation_observed", "tenantId": tenant,
            "timestamp": f"2026-10-{day}T10:{i // 60:02d}:{i % 60:02d}Z",
            "properties": {"agentId": "a1", "toolName": "t", "status": status}}).rows)
    return normalize_rows(rows, tenant)


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_recompute_is_idempotent_and_rebuildable():
    repo = BehaviorSnapshotRepository()
    f = facts("22", "succeeded")
    first = await record_window(repo, T, "a1", f, D1)
    again = await record_window(repo, T, "a1", list(reversed(f)), D1)
    assert first == again
    rows = await repo.windows(T, "a1")
    assert len(rows) == 1 and rows[0]["id"] == snapshot_id(T, "a1", D1)
    assert rows[0]["snapshot"]["rates"]["tool_success_rate"]["n"] == 30
    assert await repo.delete_by_agent(T, "a1") == 1
    assert await repo.windows(T, "a1") == []
    assert await record_window(repo, T, "a1", f, D1) == first, "deleting a cache loses no evidence"


@pytest.mark.asyncio
async def test_windows_only_include_facts_inside_the_window_and_tenant():
    repo = BehaviorSnapshotRepository()
    mixed = facts("22", "succeeded") + facts("23", "failed") + facts("22", "failed", tenant="other")
    snap = await record_window(repo, T, "a1", mixed, D1)
    assert snap["rates"]["tool_success_rate"]["value"] == 1.0 and snap["rates"]["tool_success_rate"]["n"] == 30
    assert await repo.windows("other", "a1") == []


@pytest.mark.asyncio
async def test_drift_needs_two_windows_then_detects_separation():
    repo = BehaviorSnapshotRepository()
    assert (await drift_over_stored_windows(repo, T, "a1"))["status"] == "insufficient_windows"
    await record_window(repo, T, "a1", facts("22", "succeeded"), D1)
    assert (await drift_over_stored_windows(repo, T, "a1"))["status"] == "insufficient_windows"
    await record_window(repo, T, "a1", facts("23", "failed"), D2)
    drift = await drift_over_stored_windows(repo, T, "a1", [{"first_seen": "2026-10-23T05:00:00Z"}])
    assert drift["status"] == "drift_detected" and drift["dimensions"][0]["feature"] == "tool_success_rate"
    assert drift["coincident_configuration_changes"]
    assert await repo.purge_before(T, "a1", D2[1]) == 1
    assert len(await repo.windows(T, "a1")) == 1


@pytest.mark.asyncio
async def test_snapshot_routes_store_and_report_drift():
    import dataclasses
    from types import SimpleNamespace

    import actions.agent.deployment_routes as routes
    from ingestion.silver import writer as silver_writer
    from shared.common.common import BadRequestError

    routes.settings.external_agent_telemetry = dataclasses.replace(
        routes.settings.external_agent_telemetry, enabled=True, registry_enabled=True)
    silver_writer.reset_local_tables()

    def req(tenant=T):
        t = SimpleNamespace(tenant_id=tenant, user_id="u", site_ids=[], require_permission=lambda _: None)
        return SimpleNamespace(state=SimpleNamespace(tenant=t))

    for day, status in (("22", "succeeded"), ("23", "failed")):
        for i in range(30):
            r = AgentExecutionProjector().project({
                "messageId": f"rt-{day}-{i:03d}", "type": "agent_tool_invocation_observed", "tenantId": T,
                "timestamp": f"2026-10-{day}T10:00:{i:02d}Z",
                "properties": {"agentId": "a1", "toolName": "t", "status": status}})
            await silver_writer.SilverFactWriter()._persist_generic(r.table, r.rows)
    for w in (D1, D2):
        out = (await routes.record_behavior_snapshot(
            "a1", routes.BehaviorSnapshotRequest(window_start=w[0], window_end=w[1]), req()))["data"]
        assert out["snapshot"]["rates"]["tool_success_rate"]["n"] == 30
    drift = (await routes.behavior_drift("a1", req()))["data"]["drift"]
    assert drift["status"] == "drift_detected"
    assert (await routes.behavior_drift("a1", req("other-tenant")))["data"]["drift"]["status"] == "insufficient_windows"
    with pytest.raises(BadRequestError):
        await routes.record_behavior_snapshot(
            "a1", routes.BehaviorSnapshotRequest(window_start=D2[0], window_end=D1[0]), req())
    silver_writer.reset_local_tables()
