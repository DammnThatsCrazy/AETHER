"""CI-gated tests for Data Quality / Drift / Intelligence Quality.

Mirrors the backend-suite coverage in
``Backend Architecture/aether-backend/tests/data_quality/`` but runs under the
root ``tests/`` testpath (which is what CI executes) using the standard
``backend_module_path`` import-isolation pattern shared by the other root unit
tests (see test_governance_routes.py).
"""
from __future__ import annotations

import importlib
import json
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
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def dq(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        audit_mod = importlib.import_module("services.security.audit_ledger")
        audit_mod._TENANT_TAIL.clear()
        audit_mod._TENANT_SEQ.clear()
        routes = importlib.import_module("services.data_quality.routes")
        service = importlib.import_module("services.data_quality.service")
        models = importlib.import_module("services.data_quality.models")
        sec_repos = importlib.import_module("services.security.repositories")
        yield SimpleNamespace(
            routes=routes,
            service=service,
            models=models,
            sec_repos=sec_repos,
            iq=service.intelligence_quality_service,
            drift=service.drift_service,
        )


OP_PERMS = ["kyber:operator", "admin"]


class Tenant:
    def __init__(self, tenant_id="tenant-a", permissions=None, user_id="user-1"):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.permissions = list(permissions if permissions is not None else ["read", "write", "admin"])

    def has_permission(self, permission):
        return permission in self.permissions

    def require_permission(self, permission):
        if permission not in self.permissions:
            raise PermissionError(f"missing permission {permission}")


def req(tenant_id="tenant-a", permissions=None):
    return SimpleNamespace(
        state=SimpleNamespace(tenant=Tenant(tenant_id, permissions)),
        client=None,
        headers={},
    )


def unwrap(resp):
    return resp["data"]


# ── scoring ──────────────────────────────────────────────────────────────────

async def test_score_normalized_and_complete(dq):
    score = await dq.iq.compute_score("tenant-a")
    for field in dq.models.QUALITY_DIMENSIONS:
        assert 0.0 <= score[field] <= 1.0
    assert 0.0 <= score["overall_intelligence_quality_score"] <= 1.0
    assert score["status"] in ("healthy", "watch", "degraded", "critical")


async def test_dimension_reports_have_metrics(dq):
    events = dq.iq.dimension_report("events", "tenant-a")
    assert "event_volume" in events and "quality_score" in events
    graph = dq.iq.dimension_report("graph", "tenant-a")
    assert "orphaned_vertices" in graph


# ── tenant routes ─────────────────────────────────────────────────────────────

async def test_tenant_overview(dq):
    data = unwrap(await dq.routes.data_quality_overview(req("tenant-a")))
    assert data["score"]["tenant_id"] == "tenant-a"
    assert len(data["dimensions"]) == len(dq.models.QUALITY_DIMENSIONS)
    assert data["open_drift_event_count"] == 0  # platform drift not surfaced to tenant


async def test_tenant_route_requires_read(dq):
    with pytest.raises(PermissionError):
        await dq.routes.data_quality_events(req("tenant-a", permissions=[]))


# ── Kyber operator gating ──────────────────────────────────────────────────────

async def test_kyber_denies_plain_tenant_admin(dq):
    from shared.common.common import ForbiddenError
    with pytest.raises(ForbiddenError):
        await dq.routes.intelligence_quality_overview(req("tenant-a", permissions=["admin", "read"]))


async def test_kyber_allows_operator(dq):
    data = unwrap(await dq.routes.intelligence_quality_overview(req("ops", permissions=OP_PERMS)))
    assert data["score"]["scope"] == "platform"


async def test_kyber_tenants_aggregate_only(dq):
    data = unwrap(await dq.routes.intelligence_quality_tenants(req("ops", permissions=OP_PERMS), tenant_ids=None))
    assert data["items"]
    for row in data["items"]:
        assert set(row.keys()) == {"tenant_id", "overall_intelligence_quality_score", "status", "calculated_at"}


# ── drift lifecycle ────────────────────────────────────────────────────────────

async def test_drift_seed_list_ack_resolve(dq):
    items = await dq.drift.list()
    assert len(items) >= 3
    op = req("ops", permissions=OP_PERMS)
    acked = unwrap(await dq.routes.intelligence_quality_acknowledge("drift_seed_reco_quality", op))
    assert acked["status"] == "acknowledged"
    resolved = unwrap(await dq.routes.intelligence_quality_resolve("drift_seed_reco_quality", op, dq.routes.DriftResolve(resolution_note="ok")))
    assert resolved["status"] == "resolved"


async def test_drift_mutation_requires_admin(dq):
    with pytest.raises(PermissionError):
        await dq.routes.intelligence_quality_acknowledge("drift_seed_reco_quality", req("ops", permissions=["kyber:operator"]))


# ── contamination escalation ────────────────────────────────────────────────────

async def test_critical_contamination_escalates(dq):
    repo = dq.sec_repos.SecurityAuditEventRepository()
    before = len(await repo.list_all(limit=1000))
    drift = await dq.drift.detect_contamination(
        tenant_id="tenant-a", severity="critical",
        reason="cross-tenant identifiers", supporting_metrics={"cross_tenant_identifiers": 7},
    )
    assert drift["escalated_audit_event_id"]
    after = await repo.list_all(limit=1000)
    assert len(after) == before + 1
    assert any(e.get("event_type") == "data_quality_contamination_detected" for e in after)


async def test_low_contamination_no_escalation(dq):
    repo = dq.sec_repos.SecurityAuditEventRepository()
    before = len(await repo.list_all(limit=1000))
    drift = await dq.drift.detect_contamination(
        tenant_id="tenant-a", severity="low",
        reason="single record", supporting_metrics={"records_missing_tenant_id": 1},
    )
    assert drift["escalated_audit_event_id"] is None
    assert len(await repo.list_all(limit=1000)) == before


async def test_contamination_audit_has_no_secrets(dq):
    await dq.drift.detect_contamination(
        tenant_id="tenant-a", severity="critical", reason="leak",
        supporting_metrics={"api_key": "sk_live_secret_value", "cross_tenant_identifiers": 2},
    )
    repo = dq.sec_repos.SecurityAuditEventRepository()
    blob = json.dumps(await repo.list_all(limit=1000))
    assert "sk_live_secret_value" not in blob
