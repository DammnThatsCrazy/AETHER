"""Access Kit audit-versus-usage reconciliation (W4)."""
from __future__ import annotations

from billing.billing.access_reconciliation import reconcile_access_interactions

START, END = "2026-11-01T00:00:00+00:00", "2026-11-02T00:00:00+00:00"
WITHIN = "2026-11-01T12:00:00+00:00"


class _Audit:
    def __init__(self, rows): self.rows = rows
    async def list_for_tenant(self, tenant_id, limit=0): return self.rows


class _Meter:
    def __init__(self, rows, truncated=False): self.rows, self.truncated = rows, truncated
    async def list_for_tenant_period(self, tenant_id, start, end, limit=0): return self.rows, self.truncated


def _audit(request_id, capability="entities.list", tenant="t", created=WITHIN, event="access.interaction"):
    return {"event_type": event, "tenant_id": tenant, "created_at": created,
            "resource_id": capability, "metadata": {"request_id": request_id, "capability_id": capability}}


def _usage(request_id, tenant="t", billable=False):
    return {"source_type": "access_kit", "event_type": "access_interaction", "source_id": request_id,
            "tenant_id": tenant, "occurred_at": WITHIN, "billable": billable}


async def test_matching_rows_are_consistent():
    report = await reconcile_access_interactions(
        "t", START, END, audit_repo=_Audit([_audit("r1"), _audit("r2")]),
        metering_repo=_Meter([_usage("r1"), _usage("r2")]),
    )
    assert report["matched"] == 2 and report["consistent"] is True


async def test_gaps_are_reported_on_both_sides():
    report = await reconcile_access_interactions(
        "t", START, END, audit_repo=_Audit([_audit("r1"), _audit("r2")]),
        metering_repo=_Meter([_usage("r1"), _usage("r9")]),
    )
    assert report["audit_without_usage"] == ["r2"]
    assert report["usage_without_audit"] == ["r9"]
    assert report["consistent"] is False


async def test_usage_summary_reads_are_not_expected_to_be_metered():
    report = await reconcile_access_interactions(
        "t", START, END, audit_repo=_Audit([_audit("r1", capability="billing.usage.summary.read")]),
        metering_repo=_Meter([]),
    )
    assert report["audited_meterable"] == 0 and report["consistent"] is True


async def test_other_tenants_other_events_and_out_of_window_rows_are_ignored():
    rows = [_audit("a", tenant="other"), _audit("b", event="auth.login"),
            _audit("c", created="2026-10-01T00:00:00+00:00")]
    report = await reconcile_access_interactions(
        "t", START, END, audit_repo=_Audit(rows), metering_repo=_Meter([_usage("x", tenant="other")]),
    )
    assert report["audited_meterable"] == 0 and report["metered"] == 0


async def test_truncation_and_billable_events_are_disclosed():
    report = await reconcile_access_interactions(
        "t", START, END, audit_repo=_Audit([]), metering_repo=_Meter([_usage("r1", billable=True)], truncated=True),
    )
    assert report["truncated"] is True
    assert report["billable_events_seen"] == 1


async def test_reconciliation_route_requires_admin_and_is_tenant_scoped(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from starlette.requests import Request

    from billing.billing import access_reconciliation, routes
    from shared.common.common import ForbiddenError

    seen = {}

    async def fake(tenant_id, start, end, **_):
        seen["args"] = (tenant_id, start, end)
        return {"tenant_id": tenant_id, "consistent": True}

    monkeypatch.setattr(access_reconciliation, "reconcile_access_interactions", fake)

    def request_for(permissions, role=None):
        request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
        tenant = SimpleNamespace(tenant_id="t-1", permissions=permissions)

        def require_permission(name):
            if name not in permissions:
                raise ForbiddenError(f"Missing permission: {name}")

        tenant.require_permission = require_permission
        request.state.tenant = tenant
        return request

    with pytest.raises(ForbiddenError):
        await routes.get_access_kit_reconciliation(request_for(["read"]), START, END)
    body = await routes.get_access_kit_reconciliation(request_for(["read", "admin"]), START, END)
    assert seen["args"] == ("t-1", START, END)
    assert body["data"]["consistent"] is True


async def test_daily_cycle_reconciles_yesterday_for_every_tenant_and_isolates_failures():
    from datetime import datetime, timezone

    from billing.billing.access_reconciliation import previous_utc_day, run_access_reconciliation_cycle

    now = datetime(2026, 11, 8, 2, 10, tzinfo=timezone.utc)
    start, end = previous_utc_day(now)
    assert start.startswith("2026-11-07T00:00:00") and end.startswith("2026-11-08T00:00:00")

    class Audit:
        async def list_for_tenant(self, tenant_id, limit=0):
            if tenant_id == "boom":
                raise RuntimeError("store down")
            if tenant_id == "gap":
                return [_audit("r1", tenant="gap", created="2026-11-07T12:00:00+00:00")]
            return []

    summary = await run_access_reconciliation_cycle(
        now, tenant_ids=["ok", "gap", "boom"], audit_repo=Audit(), metering_repo=_Meter([]),
    )
    assert summary["tenants"] == 3
    assert (summary["consistent"], summary["inconsistent"], summary["failed"]) == (1, 1, 1)


def test_cycle_is_registered_as_a_supervised_maintenance_worker():
    from types import SimpleNamespace

    from workers.runtime.roles import ROLE_TO_SPEC_NAMES as ROLE_WORKERS
    from workers.runtime.specs import build_worker_specs

    names = {s.name for s in build_worker_specs(registry=SimpleNamespace(), settings=SimpleNamespace())}
    assert "access_reconciliation" in names
    assert "access_reconciliation" in ROLE_WORKERS["maintenance"]


def test_next_run_is_within_a_day():
    from datetime import datetime, timezone

    from billing.billing.access_reconciliation import _seconds_until_next_run

    assert 0 < _seconds_until_next_run(datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)) == 70 * 60
    assert _seconds_until_next_run(datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)) == 23 * 3600 + 10 * 60
