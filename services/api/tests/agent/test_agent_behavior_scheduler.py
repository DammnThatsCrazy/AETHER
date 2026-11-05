"""Scheduled agent behavior job (default OFF, derived writes only)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ingestion.silver import writer as silver_writer
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector
from intelligence.agent_behavior import scheduler
from intelligence.agent_behavior.snapshot_store import BehaviorSnapshotRepository
from repositories.repos import reset_in_memory_stores

T = "tenant-sched"
NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    reset_in_memory_stores()
    silver_writer.reset_local_tables()
    yield
    reset_in_memory_stores()
    silver_writer.reset_local_tables()


async def _facts(day, status, n=30, agent="a1"):
    for i in range(n):
        r = AgentExecutionProjector().project({
            "messageId": f"{agent}-{day}-{i:03d}", "type": "agent_tool_invocation_observed", "tenantId": T,
            "timestamp": f"2026-11-{day}T10:00:{i:02d}Z",
            "properties": {"agentId": agent, "toolName": "t", "status": status}})
        await silver_writer.SilverFactWriter()._persist_generic(r.table, r.rows)


def test_window_is_the_last_complete_utc_day():
    assert scheduler.last_complete_day(NOW) == ("2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z")
    assert scheduler.last_complete_day(datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc))[0] == "2026-11-01T00:00:00Z"


@pytest.mark.asyncio
async def test_pass_records_snapshots_is_idempotent_and_skips_agents_without_facts():
    await _facts("01", "succeeded")
    first = await scheduler.run_once(NOW, agents=[(T, "a1"), (T, "ghost")])
    again = await scheduler.run_once(NOW, agents=[(T, "a1"), (T, "ghost")])
    assert first.snapshots_recorded == 1 and first.skipped_no_facts == 1 and not first.errors
    assert again.snapshots_recorded == 1
    rows = await BehaviorSnapshotRepository().windows(T, "a1")
    assert len(rows) == 1 and rows[0]["window_start"] == "2026-11-01T00:00:00Z"
    assert await BehaviorSnapshotRepository().windows("other-tenant", "a1") == []


@pytest.mark.asyncio
async def test_second_day_with_separated_behavior_detects_drift_and_persists_an_assessment():
    from intelligence.risk360.store import RiskAssessmentRepository

    await _facts("01", "succeeded")
    await scheduler.run_once(NOW, agents=[(T, "a1")])
    await _facts("02", "failed")
    nxt = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)
    report = await scheduler.run_once(nxt, agents=[(T, "a1")])
    assert report.drift_detected == 1 and report.assessments_persisted == 1
    rows = await RiskAssessmentRepository().find_many(filters={"tenant_id": T}, limit=10)
    assert rows and all(r.get("tenant_id") == T for r in rows)


@pytest.mark.asyncio
async def test_one_agent_failure_does_not_stop_the_pass(monkeypatch):
    await _facts("01", "succeeded", agent="good")
    real = scheduler.run_agent

    async def flaky(tenant, agent, window, report):
        if agent == "bad":
            raise RuntimeError("boom")
        await real(tenant, agent, window, report)

    monkeypatch.setattr(scheduler, "run_agent", flaky)
    report = await scheduler.run_once(NOW, agents=[(T, "bad"), (T, "good")])
    assert report.snapshots_recorded == 1 and report.errors == [f"{T}:bad:RuntimeError"]


@pytest.mark.asyncio
async def test_active_agents_lists_only_active_registered_deployments():
    from actions.agent.deployments import get_deployment_repository

    repo = get_deployment_repository()
    mk = lambda agent, t: repo.create(t, {"agent_id": agent, "display_name": "b", "external_platform": "web_widget",  # noqa: E731
                                          "environment": "production", "consent_mode": "tenant_managed"},
                                      actor="t", request_id="r")
    live, paused = await mk("live", T), await mk("paused", T)
    await mk("other", "tenant-b")
    await repo.transition(T, paused["id"], "paused", actor="t", request_id="r")
    assert await scheduler.active_agents() == [("tenant-b", "other"), (T, "live")]
    assert live["id"]


def test_worker_is_registered_off_by_default_under_maintenance():
    import dataclasses

    from config.settings import settings
    from workers.runtime.roles import ROLE_TO_SPEC_NAMES
    from workers.runtime.specs import build_worker_specs

    assert "agent_behavior_jobs" in ROLE_TO_SPEC_NAMES["maintenance"]
    spec = next(sp for sp in build_worker_specs(registry=None, settings=settings) if sp.name == "agent_behavior_jobs")
    assert spec.enabled() is False and not getattr(spec, "required", False)
    on = dataclasses.replace(settings.external_agent_telemetry, behavior_jobs_enabled=True)
    patched = dataclasses.replace(settings, external_agent_telemetry=on)
    spec_on = next(sp for sp in build_worker_specs(registry=None, settings=patched) if sp.name == "agent_behavior_jobs")
    assert spec_on.enabled() is True
