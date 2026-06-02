from __future__ import annotations

from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from services.reliability import routes as rl
from services.reliability.service import (
    compute_slo_status,
    incident_service,
    pipeline_service,
    queue_service,
    runbook_service,
    service_registry,
    slo_service,
)
from services.reliability.tenant_impact import (
    _audit_exports,
    _dispatches,
    _recommendations,
    tenant_impact,
)


class Tenant:
    def __init__(self, tenant_id="tenant-a", permissions=None, user_id="user-1"):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.permissions = set(permissions or {"read", "write", "admin"})

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise PermissionError(f"missing permission {permission}")


def req(tenant_id="tenant-a", permissions=None):
    return SimpleNamespace(state=SimpleNamespace(tenant=Tenant(tenant_id, permissions)))


def unwrap(resp):
    return resp["data"]


@pytest.fixture(autouse=True)
def clean():
    reset_in_memory_stores()


# ── Service health ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_health_create_and_update():
    services = await service_registry.list()
    assert len(services) == 18
    assert all(s["status"] == "unknown" for s in services)

    await service_registry.heartbeat("ingestion", latency_ms=42.0, error_rate=0.01)
    await service_registry.set_status("ingestion", "healthy")
    await service_registry.record_successful_job("ingestion")
    rec = await service_registry.get("ingestion")
    assert rec["status"] == "healthy"
    assert rec["latency_ms"] == 42.0
    assert rec["last_heartbeat_at"] is not None
    assert rec["last_successful_job_at"] is not None


@pytest.mark.asyncio
async def test_service_incident_linkage():
    await service_registry.link_incident("recommendations", "inc-1")
    rec = await service_registry.get("recommendations")
    assert "inc-1" in rec["open_incident_ids"]
    await service_registry.unlink_incident("recommendations", "inc-1")
    rec = await service_registry.get("recommendations")
    assert "inc-1" not in rec["open_incident_ids"]


# ── Pipeline + queue health ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_health_aggregation():
    pipelines = await pipeline_service.list()
    assert len(pipelines) == 12
    updated = await pipeline_service.report("sdk_to_event_store", {
        "status": "degraded", "throughput_per_minute": 120.0, "error_rate": 0.07,
        "retry_count": 5, "dead_letter_count": 2, "affected_tenant_count": 3,
    })
    assert updated["status"] == "degraded"
    assert updated["dead_letter_count"] == 2


@pytest.mark.asyncio
async def test_queue_health_records():
    queues = await queue_service.list()
    assert len(queues) == 7
    updated = await queue_service.report("action_dispatch", {
        "status": "degraded", "depth": 500, "oldest_message_age_seconds": 900.0,
        "worker_count": 4, "active_worker_count": 2, "dead_letter_count": 10,
    })
    assert updated["depth"] == 500
    assert updated["active_worker_count"] == 2


# ── Runbooks ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runbook_definitions():
    runbooks = await runbook_service.list()
    assert len(runbooks) == 13
    keys = {r["runbook_id"] for r in runbooks}
    assert "rb_sdk_ingestion_degraded" in keys
    assert "rb_security_audit_event_failure" in keys
    created = await runbook_service.create({"title": "Custom", "incident_type": "custom"})
    assert created["runbook_id"].startswith("rb_")
    patched = await runbook_service.update(created["runbook_id"], {"severity_hint": "sev1"})
    assert patched["severity_hint"] == "sev1"


# ── SLOs ───────────────────────────────────────────────────────────────────

def test_slo_status_calculation():
    # lower-is-better latency, well under ceiling → meeting
    status, budget = compute_slo_status(500.0, 100.0, "ingestion_latency_ms_p95")
    assert status == "meeting" and budget and budget > 0.5
    # latency over ceiling → breached
    status, budget = compute_slo_status(500.0, 600.0, "ingestion_latency_ms_p95")
    assert status == "breached"
    # availability ratio just above target → at_risk (thin budget)
    status, budget = compute_slo_status(0.999, 0.9991, "availability_ratio")
    assert status == "at_risk"
    # unknown when no current value
    status, budget = compute_slo_status(0.999, None, "availability_ratio")
    assert status == "unknown" and budget is None


@pytest.mark.asyncio
async def test_slo_list_and_update():
    slos = await slo_service.list()
    assert len(slos) == 9
    await slo_service.set_current_value("slo_sdk_ingestion_latency", 120.0)
    slos = await slo_service.list()
    target = next(s for s in slos if s["slo_id"] == "slo_sdk_ingestion_latency")
    assert target["status"] == "meeting"


# ── Incidents ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_incident_create_update_resolve():
    inc = await incident_service.create({
        "title": "Ingestion degraded", "severity": "sev2",
        "affected_services": ["ingestion"], "affected_tenants": ["tenant-a"],
    }, actor="op-1")
    iid = inc["incident_id"]
    # service linkage applied
    svc = await service_registry.get("ingestion")
    assert iid in svc["open_incident_ids"]

    await incident_service.assign_owner(iid, "owner-9", actor="op-1")
    await incident_service.add_mitigation_step(iid, "scaled workers", actor="op-1")
    await incident_service.mark_postmortem_pending(iid, actor="op-1")
    resolved = await incident_service.resolve(iid, actor="op-1")
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    assert "scaled workers" in resolved["mitigation_steps"]

    # linkage removed on resolve
    svc = await service_registry.get("ingestion")
    assert iid not in svc["open_incident_ids"]

    trail = await incident_service.audit_trail(iid)
    assert any(e["action"] == "created" for e in trail)
    assert len(trail) >= 4


@pytest.mark.asyncio
async def test_terminal_incident_not_linked_on_create():
    # A backfilled resolved incident must not mark its services as "open".
    inc = await incident_service.create({
        "title": "Backfill", "severity": "sev3", "status": "resolved",
        "affected_services": ["outcomes"],
    })
    svc = await service_registry.get("outcomes")
    assert inc["incident_id"] not in (svc["open_incident_ids"] or [])
    # And it must not count toward current tenant impact.
    await incident_service.create({
        "title": "Old", "severity": "sev3", "status": "closed",
        "affected_services": ["outcomes"], "affected_tenants": ["tenant-z"],
    })
    summary = await tenant_impact.internal_summary()
    assert summary["impacted_tenant_count"] == 0
    assert summary["historically_impacted_tenant_count"] == 1


@pytest.mark.asyncio
async def test_incident_tenant_isolation():
    await incident_service.create({
        "title": "Tenant A only", "severity": "sev3",
        "affected_services": ["recommendations"], "affected_tenants": ["tenant-a"],
    })
    a = await tenant_impact.tenant_incidents_safe("tenant-a")
    b = await tenant_impact.tenant_incidents_safe("tenant-b")
    assert len(a["active"]) == 1
    assert len(b["active"]) == 0 and len(b["resolved"]) == 0


# ── Tenant impact + tenant-safe visibility ─────────────────────────────────

@pytest.mark.asyncio
async def test_tenant_impact_analysis():
    await _recommendations.insert("rec-1", {"recommendation_id": "rec-1", "tenant_id": "tenant-a", "created_at": "2026-06-01T00:00:00Z"})
    await _dispatches.insert("d-1", {"dispatch_id": "d-1", "tenant_id": "tenant-a", "status": "failed"})
    await _audit_exports.insert("ae-1", {"export_id": "ae-1", "tenant_id": "tenant-a", "status": "failed"})
    detail = await tenant_impact.compute("tenant-a")
    assert detail["failed_dispatches"] == 1
    assert detail["failed_audit_exports"] == 1
    assert detail["recommendations_total"] == 1


@pytest.mark.asyncio
async def test_tenant_facing_status_visibility_and_no_infra_leakage():
    await incident_service.create({
        "title": "Dispatch issues", "severity": "sev2",
        "affected_services": ["dispatches"], "affected_tenants": ["tenant-a"],
        "internal_notes": "secret runbook detail", "root_cause": "bad deploy",
        "customer_impact": "Some actions delayed",
    })
    # tenant status route
    resp = unwrap(await rl.tenant_status(req("tenant-a")))
    assert resp["tenant_id"] == "tenant-a"
    assert resp["active_incidents"] == 1

    incidents = unwrap(await rl.tenant_status_incidents(req("tenant-a")))
    active = incidents["active"]
    assert len(active) == 1
    leaked_keys = {"internal_notes", "root_cause", "affected_tenants", "affected_services", "owner_id", "runbook_id"}
    for inc in active:
        assert not (leaked_keys & set(inc.keys())), f"leaked infra keys: {set(inc.keys()) & leaked_keys}"
        assert inc["customer_impact"] == "Some actions delayed"

    # freshness + integrations routes must not expose queues/pipelines/other tenants
    fresh = unwrap(await rl.tenant_status_data_freshness(req("tenant-a")))
    integ = unwrap(await rl.tenant_status_integrations(req("tenant-a")))
    for payload in (fresh, integ):
        text = str(payload)
        assert "queue" not in text.lower()
        assert "tenant-b" not in text


# ── Kyber admin permissions ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kyber_admin_route_permissions():
    # non-admin tenant is rejected
    with pytest.raises(PermissionError):
        await rl.reliability_overview(req("tenant-a", permissions={"read"}))
    # admin allowed
    resp = unwrap(await rl.reliability_overview(req("tenant-a")))
    assert "overall_status" in resp
    assert resp["service_health_summary"]["total"] == 18


@pytest.mark.asyncio
async def test_kyber_incident_routes_roundtrip():
    from services.reliability.routes import IncidentCreate, IncidentPatch
    created = unwrap(await rl.create_incident(IncidentCreate(title="X", severity="sev1", affected_services=["ingestion"]), req()))
    iid = created["incident_id"]
    got = unwrap(await rl.get_incident(iid, req()))
    assert got["incident_id"] == iid
    assert "audit_trail" in got
    patched = unwrap(await rl.patch_incident(iid, IncidentPatch(status="investigating"), req()))
    assert patched["status"] == "investigating"


# ── Postmortem lifecycle ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_postmortem_lifecycle():
    from services.reliability.routes import PostmortemCreate, PostmortemPatch
    pm = unwrap(await rl.create_postmortem(PostmortemCreate(
        incident_id="inc-x", summary="s", root_cause="rc", customer_impact="ci",
    ), req()))
    assert pm["status"] == "draft"
    reviewed = unwrap(await rl.patch_postmortem(pm["postmortem_id"], PostmortemPatch(status="reviewed"), req()))
    assert reviewed["status"] == "reviewed"
    closed = unwrap(await rl.patch_postmortem(pm["postmortem_id"], PostmortemPatch(status="closed"), req()))
    assert closed["status"] == "closed"
    items = unwrap(await rl.list_postmortems(req()))["items"]
    assert len(items) == 1
