"""Durable operator briefings and compressed ops alerts: durability across
store handles, live-state content, compression, routing fail-open/throttle,
tenant isolation, retention, and flag gating."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import BadRequestError, NotFoundError  # noqa: E402
from shared.store import get_store  # noqa: E402
from services.agent import briefings, ops_alerts  # noqa: E402
from services.agent.briefings import (  # noqa: E402
    BriefingRequest,
    generate_briefing,
    generate_briefing_route,
    get_briefing_detail,
    get_briefings,
    prune_briefings,
)
from services.agent.ops_alerts import (  # noqa: E402
    AlertSubmission,
    get_ops_alerts,
    list_alerts,
    post_ops_alert,
    record_alert,
    resolve_alert,
)
from services.agent.routes import (  # noqa: E402
    KillSwitchAction,
    ObjectiveSubmission,
    _runtime_repo,
    submit_objective,
    toggle_kill_switch,
)

from one_person_ops.conftest import FakeRequest, tenant_id  # noqa: E402

pytestmark = pytest.mark.asyncio


# ── Briefings ──────────────────────────────────────────────────────────────

async def test_briefings_are_durable_across_store_handles(ops_enabled):
    tenant = tenant_id()
    briefing = await generate_briefing(tenant, "daily")
    # A second handle to the same named store sees the same data — the record
    # lives in the durable store, not in module state.
    other_handle = get_store("agent_briefings")
    stored = await other_handle.get(briefing["briefing_id"])
    assert stored is not None
    assert stored["tenant_id"] == tenant
    assert stored["type"] == "daily"


async def test_generate_includes_stuck_runs_review_and_kill_switch(ops_enabled):
    tenant = tenant_id()
    request = FakeRequest(tenant)
    # Pending review batch via staged mutations.
    await submit_objective(ObjectiveSubmission(
        goal="Needs review",
        payload={"staged_mutations": [{"mutation_class": 1, "operation": "upsert"}]},
    ), request)
    # A stuck run: dispatched long ago with no heartbeat since.
    runnable = (await submit_objective(ObjectiveSubmission(goal="Will get stuck"), request))["data"]
    dispatched = await _runtime_repo.record_dispatch(tenant, runnable["objective_id"], "nous", "op", "req")
    run = dispatched["run"]
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    run["heartbeat_at"] = old
    run["updated_at"] = old
    await _runtime_repo.worker_runs.set(run["run_id"], run)
    # Kill switch engaged.
    await toggle_kill_switch(KillSwitchAction(action="engage", reason="drill"), request)
    # An open alert.
    await record_alert(tenant, "P1", "worker_stale", "worker w-1 stale", dedupe_key=f"{tenant}:stale")

    briefing = await generate_briefing(tenant, "handoff", actor_id="op")
    sections = briefing["sections"]
    assert sections["review"]["pending_batches"] == 1
    assert run["run_id"] in {r["run_id"] for r in sections["stuck_runs"]}
    assert sections["kill_switch"]["enabled"] is True
    assert sections["staged_mutations"]["staged"] == 1
    assert any(a["kind"] == "worker_stale" for a in sections["alerts"])
    assert sections["objectives"]["awaiting_review"] == 1
    attention = " ".join(sections["attention"])
    assert "Kill switch" in attention
    assert "stuck run" in attention
    assert "review batch" in attention
    assert briefing["summary"] != "All clear — no items need attention"


async def test_briefing_all_clear_summary(ops_enabled):
    briefing = await generate_briefing(tenant_id(), "daily")
    assert briefing["summary"] == "All clear — no items need attention"
    assert briefing["sections"]["attention"] == []


async def test_briefing_type_validated(ops_enabled):
    with pytest.raises(BadRequestError):
        await generate_briefing(tenant_id(), "gossip")


async def test_briefing_routes_generate_list_and_detail(ops_enabled):
    request = FakeRequest(tenant_id())
    generated = await generate_briefing_route(BriefingRequest(briefing_type="daily"), request)
    briefing_id = generated["data"]["briefing_id"]
    listed = await get_briefings(request)
    assert listed["data"]["total"] >= 1
    detail = await get_briefing_detail(briefing_id, request)
    assert detail["data"]["briefing_id"] == briefing_id
    filtered = await get_briefings(request, briefing_type="handoff")
    assert filtered["data"]["total"] == 0


async def test_briefing_tenant_isolation(ops_enabled):
    tenant_a = tenant_id()
    briefing = await generate_briefing(tenant_a, "daily")
    other = FakeRequest(tenant_id())
    with pytest.raises(NotFoundError):
        await get_briefing_detail(briefing["briefing_id"], other)
    listed = await get_briefings(other)
    assert all(b["tenant_id"] != tenant_a for b in listed["data"]["briefings"])


async def test_briefing_retention_prunes_old_records(ops_enabled):
    tenant = tenant_id()
    old_briefing = await generate_briefing(tenant, "daily")
    old_briefing["created_at"] = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    await briefings._briefings.set(old_briefing["briefing_id"], old_briefing)
    fresh = await generate_briefing(tenant, "daily")
    pruned = await prune_briefings(tenant, keep_days=30)
    assert pruned == 1
    assert await briefings.get_briefing(tenant, old_briefing["briefing_id"]) is None
    assert await briefings.get_briefing(tenant, fresh["briefing_id"]) is not None


async def test_briefing_routes_gated_off_by_default():
    request = FakeRequest(tenant_id())
    with pytest.raises(BadRequestError):
        await get_briefings(request)
    with pytest.raises(BadRequestError):
        await generate_briefing_route(BriefingRequest(), request)
    with pytest.raises(BadRequestError):
        await get_briefing_detail("brief_x", request)


# ── Alerts ─────────────────────────────────────────────────────────────────

async def test_same_dedupe_key_compresses_instead_of_duplicating(ops_enabled):
    tenant = tenant_id()
    first = await record_alert(tenant, "P2", "queue_backlog", "depth 100", dedupe_key="queue:default")
    second = await record_alert(tenant, "P2", "queue_backlog", "depth 120", dedupe_key="queue:default")
    assert first["compressed"] is False
    assert second["compressed"] is True
    assert second["alert_id"] == first["alert_id"]
    assert second["count"] == 2
    rows = await list_alerts(tenant)
    assert len(rows) == 1


async def test_different_dedupe_key_creates_new_alert(ops_enabled):
    tenant = tenant_id()
    await record_alert(tenant, "P2", "queue_backlog", "depth 100", dedupe_key="queue:default")
    other = await record_alert(tenant, "P3", "worker_stale", "w-2 stale", dedupe_key="worker:w-2")
    assert other["compressed"] is False
    rows = await list_alerts(tenant)
    assert len(rows) == 2


async def test_compression_escalates_severity_never_downgrades(ops_enabled):
    tenant = tenant_id()
    await record_alert(tenant, "P2", "run_failed", "x", dedupe_key="run:1")
    escalated = await record_alert(tenant, "P0", "run_failed", "x", dedupe_key="run:1")
    assert escalated["severity"] == "P0"
    still_p0 = await record_alert(tenant, "P3", "run_failed", "x", dedupe_key="run:1")
    assert still_p0["severity"] == "P0"


async def test_invalid_severity_and_missing_dedupe_rejected(ops_enabled):
    tenant = tenant_id()
    with pytest.raises(BadRequestError):
        await record_alert(tenant, "SEV1", "kind", "msg", dedupe_key="k")
    with pytest.raises(BadRequestError):
        await record_alert(tenant, "P1", "kind", "msg", dedupe_key="")


async def test_alert_message_is_sanitized_and_bounded(ops_enabled):
    tenant = tenant_id()
    alert = await record_alert(tenant, "P1", "kind", "e" * 5000, dedupe_key="big")
    assert len(alert["message"]) <= 2000


async def test_notification_routing_fails_open(ops_enabled, monkeypatch):
    async def _explode(self, notification):
        raise RuntimeError("channel gateway down")

    monkeypatch.setattr(
        "services.notification_intelligence.delivery_router.DeliveryRouter.route", _explode
    )
    tenant = tenant_id()
    alert = await record_alert(tenant, "P0", "graph_down", "neptune unreachable", dedupe_key="graph")
    # The alert record survives even though routing failed.
    assert alert["notification"]["routed"] is False
    assert "routing_unavailable" in alert["notification"]["reason"]
    rows = await list_alerts(tenant)
    assert len(rows) == 1


async def test_no_channels_is_not_false_success(ops_enabled):
    """M8-B1: an alert with no configured channels is NOT 'routed'.

    A bare/unconfigured router would report routed=True with zero channels —
    a silent no-op delivery. The honest outcome is routed=False with an
    explicit reason, while the alert record itself stays durable.
    """
    tenant = tenant_id()
    alert = await record_alert(tenant, "P1", "run_failed", "x", dedupe_key="run:channels")
    assert alert["notification"]["routed"] is False
    assert alert["notification"]["reason"] == "no_channels_configured"
    assert alert["notification"]["channels"] == []
    # The alert record is still persisted — routing is best-effort, never
    # the durable signal.
    rows = await list_alerts(tenant)
    assert len(rows) == 1


async def test_notification_routing_throttled_per_dedupe_key(ops_enabled):
    tenant = tenant_id()
    first = await record_alert(tenant, "P1", "run_failed", "x", dedupe_key="run:throttle")
    # No channels configured in the test harness → honest non-routed outcome
    # (the old zero-channel false success is gone).
    assert first["notification"]["routed"] is False
    assert first["notification"]["reason"] == "no_channels_configured"
    # Resolve so the next record creates a NEW alert row with the same dedupe
    # key — routing state must still throttle inside the window.
    await resolve_alert(tenant, first["alert_id"])
    second = await record_alert(tenant, "P1", "run_failed", "x again", dedupe_key="run:throttle")
    assert second["compressed"] is False
    assert second["notification"] == {"routed": False, "reason": "throttled"}


async def test_alert_tenant_isolation(ops_enabled):
    tenant_a = tenant_id()
    await record_alert(tenant_a, "P1", "kind", "msg", dedupe_key="iso")
    assert await list_alerts(tenant_id()) == []


async def test_alert_routes_and_flag_gating(ops_enabled):
    request = FakeRequest(tenant_id())
    posted = await post_ops_alert(
        AlertSubmission(severity="P2", kind="ingest_backlog", message="q deep", dedupe_key="ingest"),
        request,
    )
    assert posted["data"]["severity"] == "P2"
    listed = await get_ops_alerts(request)
    assert listed["data"]["total"] == 1
    by_severity = await get_ops_alerts(request, severity="P0")
    assert by_severity["data"]["total"] == 0


async def test_alert_routes_gated_off_by_default():
    request = FakeRequest(tenant_id())
    with pytest.raises(BadRequestError):
        await get_ops_alerts(request)
    with pytest.raises(BadRequestError):
        await post_ops_alert(
            AlertSubmission(severity="P2", kind="k", message="m", dedupe_key="d"), request
        )


async def test_alerts_sorted_by_severity_then_recency(ops_enabled):
    tenant = tenant_id()
    await record_alert(tenant, "P3", "low", "x", dedupe_key="a")
    await record_alert(tenant, "P0", "critical", "x", dedupe_key="b")
    await record_alert(tenant, "P2", "mid", "x", dedupe_key="c")
    rows = await list_alerts(tenant)
    assert [r["severity"] for r in rows] == ["P0", "P2", "P3"]


async def test_run_complete_briefing_type_supported(ops_enabled):
    briefing = await generate_briefing(tenant_id(), "run_complete")
    assert briefing["type"] == "run_complete"
    assert briefing["status"] == "generated"
    alert_brief = await generate_briefing(tenant_id(), "alert")
    assert alert_brief["type"] == "alert"


async def test_notification_state_records_marker(ops_enabled):
    tenant = tenant_id()
    await record_alert(tenant, "P1", "kind", "msg", dedupe_key="marker")
    state = await ops_alerts._notification_state.get(f"{tenant}:marker")
    assert state is not None
    assert state["tenant_id"] == tenant
    assert state["last_routed_at"]
