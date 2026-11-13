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
    cal = (await routes.behavior_calibration("a1", req()))["data"]["calibration"]
    assert cal["calibrated"] is False
    assert cal["features"]["tool_success_rate"]["status"] == "insufficient_evidence"
    assert (await routes.behavior_calibration("a1", req("other-tenant")))["data"]["calibration"]["agents"] == 0
    with pytest.raises(BadRequestError):
        await routes.record_behavior_snapshot(
            "a1", routes.BehaviorSnapshotRequest(window_start=D2[0], window_end=D1[0]), req())
    silver_writer.reset_local_tables()


@pytest.mark.asyncio
async def test_window_bounds_compare_as_instants_not_strings():
    # Codex review on #867: as strings, a "+00:00" bound or a date-only bound
    # orders wrongly against the facts' "...Z" times.
    repo = BehaviorSnapshotRepository()
    f = facts("22", "succeeded")
    for window in (("2026-10-22T00:00:00+00:00", "2026-10-23T00:00:00+00:00"),
                   ("2026-10-22", "2026-10-23"),
                   ("2026-10-21T20:00:00-04:00", "2026-10-22T20:00:00-04:00")):
        snap = await record_window(repo, T, "a1", f, window)
        assert snap["rates"]["tool_success_rate"]["n"] == 30, window
    # The 10:00Z facts sit before a 10:00 bound expressed as 06:00-04:00 +1s.
    late = await record_window(repo, T, "a1", f, ("2026-10-22T06:00:30-04:00", "2026-10-23T00:00:00Z"))
    assert late["rates"]["tool_success_rate"]["n"] == 0


@pytest.mark.asyncio
async def test_purge_before_compares_instants():
    repo = BehaviorSnapshotRepository()
    await record_window(repo, T, "a1", facts("22", "succeeded"), D1)
    # 23:00-02:00 on the 22nd is 01:00Z on the 23rd, so D1 (ending 00:00Z) is
    # older and purged; as strings "2026-10-23..." sorts after "2026-10-22...".
    assert await repo.purge_before(T, "a1", "2026-10-22T23:00:00-02:00") == 1


@pytest.mark.asyncio
async def test_snapshot_route_reads_the_window_and_skips_a_truncated_one(monkeypatch):
    # Codex review on #867: the route used the newest 1,000 facts, so a busy
    # agent's older window was stored partial over a complete snapshot.
    import dataclasses
    from types import SimpleNamespace

    import actions.agent.behavior_read_model as read_model
    import actions.agent.deployment_routes as routes

    routes.settings.external_agent_telemetry = dataclasses.replace(
        routes.settings.external_agent_telemetry, enabled=True, registry_enabled=True)
    t = SimpleNamespace(tenant_id=T, user_id="u", site_ids=[], require_permission=lambda _: None)
    req = SimpleNamespace(state=SimpleNamespace(tenant=t))
    calls = []

    async def window_facts(tenant_id, agent_ref, window):
        calls.append((tenant_id, agent_ref, window))
        return facts("22", "succeeded"), truncated

    async def newest_facts(*_a, **_k):
        raise AssertionError("snapshot must not use the newest-facts read")

    monkeypatch.setattr(read_model, "load_window_facts", window_facts)
    monkeypatch.setattr(read_model, "load_behavior_facts", newest_facts)
    body = routes.BehaviorSnapshotRequest(window_start=D1[0], window_end=D1[1])

    truncated = True
    out = (await routes.record_behavior_snapshot("a1", body, req))["data"]
    assert out == {"snapshot": None, "recorded": False, "source_truncated": True}
    assert await BehaviorSnapshotRepository().windows(T, "a1") == []

    truncated = False
    out = (await routes.record_behavior_snapshot("a1", body, req))["data"]
    assert out["recorded"] is True and out["snapshot"]["rates"]["tool_success_rate"]["n"] == 30
    assert calls == [(T, "a1", D1), (T, "a1", D1)]
