"""The commerce sweeps must find their tenants on the durable store too.

They used to enumerate tenants with ``store.receipts.all_tenants``, which only the
in-memory collection has, so against Postgres every sweep silently did nothing.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("AETHER_ENV", "local")

from services.runtime import roles, specs  # noqa: E402
from services.x402.commerce_store import CommerceStore, TenantCollection, _RepoCollection  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _Row:
    def __init__(self, rid, tenant):
        self.receipt_id = rid
        self.tenant_id = tenant


def test_in_memory_store_lists_every_tenant_with_state():
    store = CommerceStore()
    assert isinstance(store.receipts, TenantCollection)
    _run(store.receipts.put("t1", _Row("r1", "t1")))
    _run(store.approvals.put("t2", type("A", (), {"approval_id": "a1"})()))
    assert _run(store.known_tenant_ids()) == ["t1", "t2"]


class _FakeRepo:
    def __init__(self, tenants):
        self._tenants = tenants

    async def distinct_tenant_ids(self, limit=10000):
        return list(self._tenants)


def test_durable_collections_report_tenants_from_the_table():
    store = CommerceStore()
    store.receipts = _RepoCollection(_FakeRepo(["t9"]), "receipt_id", object)
    store.approvals = _RepoCollection(_FakeRepo(["t3", "t9"]), "approval_id", object)
    store.entitlements = _RepoCollection(_FakeRepo([]), "entitlement_id", object)
    store.settlements = _RepoCollection(_FakeRepo(["t1"]), "settlement_id", object)
    assert _run(store.known_tenant_ids()) == ["t1", "t3", "t9"]


def _specs(commerce_enabled: bool):
    from types import SimpleNamespace

    settings = SimpleNamespace(
        intelligence_graph=SimpleNamespace(enable_commerce_control_plane=commerce_enabled)
    )
    return {s.name: s for s in specs.build_worker_specs(registry=SimpleNamespace(), settings=settings)}


def test_commerce_sweeps_are_gated_workers_with_a_role():
    claimed = set().union(*roles.ROLE_TO_SPEC_NAMES.values())
    for name in ("commerce_approval_sweeper", "commerce_entitlement_sweeper", "commerce_reconciliation"):
        assert name in claimed, name
        assert _specs(True)[name].enabled() is True
        assert _specs(False)[name].enabled() is False
        assert "commerce_settlement_sweeper" not in _specs(True)
    # x402_settlement_reconciliation already advances settlements; the sweeper that
    # would also auto-retry FAILED ones stays unregistered.
    assert "commerce_settlement_sweeper" not in claimed


def test_the_approval_sweeper_visits_each_known_tenant(monkeypatch):
    from services.commerce import workers
    from services.x402 import approvals, commerce_store

    store = CommerceStore()
    _run(store.approvals.put("t1", type("A", (), {"approval_id": "a1"})()))
    _run(store.approvals.put("t2", type("A", (), {"approval_id": "a2"})()))
    seen = []

    class _Svc:
        async def sweep_expired(self, tenant_id):
            seen.append(tenant_id)

    monkeypatch.setattr(commerce_store, "get_commerce_store", lambda: store)
    monkeypatch.setattr(approvals, "get_approval_service", lambda: _Svc())

    async def one_pass():
        loop = workers.build_approval_sweeper(interval_s=0.0)()
        task = asyncio.ensure_future(loop)
        await asyncio.sleep(0.05)
        task.cancel()

    _run(one_pass())
    assert {"t1", "t2"} <= set(seen)


def test_the_reconciliation_diagnostics_route_is_permission_gated_and_tenant_scoped(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from services.commerce import reconciliation
    from services.x402.commerce_routes import diagnostics_router
    from shared.auth.auth import Role, TenantContext
    from shared.decorators import register_error_handlers

    calls = []

    class _Reconciler:
        async def reconcile_commerce(self, tenant_id):
            calls.append(tenant_id)
            return {"tenant_id": tenant_id, "drift_count": 0, "drift": []}

    monkeypatch.setattr(reconciliation, "get_commerce_reconciler", lambda: _Reconciler())

    def client(permissions, tenant_id="t1"):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(diagnostics_router)

        @app.middleware("http")
        async def tenant(request, call_next):
            request.state.tenant = TenantContext(tenant_id=tenant_id, role=Role.VIEWER, permissions=permissions)
            return await call_next(request)

        return TestClient(app, raise_server_exceptions=False)

    assert client([]).get("/v1/diagnostics/commerce/reconciliation").status_code in (401, 403)
    assert calls == []
    ok = client(["x402:read"], tenant_id="t7").get("/v1/diagnostics/commerce/reconciliation")
    assert ok.status_code == 200 and ok.json()["data"]["tenant_id"] == "t7"
    assert calls == ["t7"]
