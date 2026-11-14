"""HTTP surface: tenant isolation, permissions, Kyber operator gate."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from config.settings import settings
from governance.security.route_registry import classify
from intelligence.pattern_discovery import routes as pd_routes
from intelligence.pattern_discovery.service import PatternDiscoveryService, set_service
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import Permissions, Role, TenantContext
from shared.common.common import AetherError

from .scenarios import T, FakeEventReader, FakeRiskStore, fraud_ring, normal_traffic


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    set_service(PatternDiscoveryService(event_reader=FakeEventReader(normal_traffic(2, 2) + fraud_ring(2)),
                                        risk_store=FakeRiskStore(),
                                        subject_resolver=_resolver))
    yield
    set_service(None)
    reset_in_memory_stores()


async def _resolver(tenant_id, key):
    return ("entity", key.split(":", 1)[1])


def _tenant(tenant_id=T, permissions=(Permissions.READ, Permissions.WRITE), **kw):
    return TenantContext(tenant_id=tenant_id, user_id=f"user-{tenant_id}", role=Role.VIEWER,
                         permissions=list(permissions), **kw)


def _client(tenant=None, *, kyber=False) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _err(request, exc):
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    if tenant is not None:
        @app.middleware("http")
        async def _inject(request, call_next):
            request.state.tenant = tenant
            return await call_next(request)

    app.include_router(pd_routes.router)
    if kyber:
        app.include_router(pd_routes.kyber_router)
    return TestClient(app, raise_server_exceptions=False)


def _operator():
    return _tenant("olympus_op", permissions=(settings.security_governance.kyber_operator_permission,))


def test_full_tenant_workflow_over_http():
    admin = _client(_tenant(permissions=(Permissions.READ, Permissions.WRITE, Permissions.ADMIN)))
    run = admin.post("/v1/intelligence/patterns/runs", json={})
    assert run.status_code == 200, run.text
    assert run.json()["data"]["patterns_detected"] >= 5
    queue = admin.get("/v1/intelligence/patterns", params={"queue": True}).json()["data"]
    pid = queue["items"][0]["pattern_id"]
    assert admin.get(f"/v1/intelligence/patterns/{pid}").json()["data"]["pattern_id"] == pid
    r = admin.post(f"/v1/intelligence/patterns/{pid}/review",
                   json={"verdict": "valid", "reason": "confirmed against the case file"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "confirmed_valid"
    p = admin.post(f"/v1/intelligence/patterns/{pid}/promote", json={"reason": "make it a standing signal"})
    assert p.status_code == 200 and p.json()["data"]["status"] == "promoted"
    ctx = admin.get("/v1/intelligence/patterns/entities/user:r0").json()["data"]
    assert ctx["entity"] == "user:r0" and ctx["advisory"] is True
    stats = admin.get("/v1/intelligence/patterns/stats").json()["data"]
    assert stats["by_status"]["promoted"] == 1
    assert admin.get("/v1/intelligence/patterns/runs").json()["data"]["count"] == 1


def test_lifecycle_errors_are_bad_requests():
    admin = _client(_tenant(permissions=(Permissions.READ, Permissions.WRITE, Permissions.ADMIN)))
    admin.post("/v1/intelligence/patterns/runs", json={})
    pid = admin.get("/v1/intelligence/patterns").json()["data"]["items"][0]["pattern_id"]
    assert admin.post(f"/v1/intelligence/patterns/{pid}/promote",
                      json={"reason": "promote without any review"}).status_code == 400
    assert admin.post(f"/v1/intelligence/patterns/{pid}/review",
                      json={"verdict": "duplicate", "reason": "same as another pattern",
                            "duplicate_of": "nope"}).status_code == 400
    assert admin.post("/v1/intelligence/patterns/missing/review",
                      json={"verdict": "benign", "reason": "pattern does not exist"}).status_code == 404
    assert admin.get("/v1/intelligence/patterns", params={"kind": "astrology"}).status_code == 400
    assert admin.post("/v1/intelligence/patterns/runs", json={"kinds": ["astrology"]}).status_code == 400
    assert admin.post("/v1/intelligence/patterns/runs", json={"surprise": 1}).status_code == 422


def test_permissions_are_enforced():
    reader = _client(_tenant(permissions=(Permissions.READ,)))
    assert reader.get("/v1/intelligence/patterns").status_code == 200
    assert reader.post("/v1/intelligence/patterns/extract", json={"payload": {"email": "a@b.co"}}).status_code == 200
    assert reader.post("/v1/intelligence/patterns/runs", json={}).status_code == 403
    writer = _client(_tenant())
    writer.post("/v1/intelligence/patterns/runs", json={})
    pid = writer.get("/v1/intelligence/patterns").json()["data"]["items"][0]["pattern_id"]
    writer.post(f"/v1/intelligence/patterns/{pid}/review", json={"verdict": "valid", "reason": "valid finding here"})
    assert writer.post(f"/v1/intelligence/patterns/{pid}/promote",
                       json={"reason": "writer may not promote"}).status_code == 403


def test_unauthenticated_and_suspended_callers_are_refused():
    assert _client(None).get("/v1/intelligence/patterns", headers={"x-tenant-id": T}).status_code == 401
    assert _client(_tenant(tenant_status="suspended")).get("/v1/intelligence/patterns").status_code == 403


def test_one_tenant_cannot_read_anothers_patterns():
    _client(_tenant()).post("/v1/intelligence/patterns/runs", json={})
    pid = _client(_tenant()).get("/v1/intelligence/patterns").json()["data"]["items"][0]["pattern_id"]
    other = _client(_tenant("tenant-other"))
    assert other.get(f"/v1/intelligence/patterns/{pid}").status_code == 404
    assert other.get("/v1/intelligence/patterns").json()["data"]["total"] == 0


def test_extract_preview_hashes_sensitive_values():
    data = _client(_tenant()).post("/v1/intelligence/patterns/extract", json={
        "payload": {"card": "4242424242424242", "device_id": "d-1"}, "text": "contact me at x@y.io",
    }).json()["data"]
    values = [a["value"] for a in data["attributes"]]
    assert "4242424242424242" not in values and "x@y.io" not in values


def test_kyber_operator_can_drive_the_queue_and_customers_cannot():
    op = _client(_operator(), kyber=True)
    run = op.post("/v1/kyber/patterns/runs", params={"tenant_id": T}, json={})
    assert run.status_code == 200, run.text
    queue = op.get("/v1/kyber/patterns/queue", params={"tenant_id": T}).json()["data"]
    assert queue["total"] >= 5
    pid = queue["items"][0]["pattern_id"]
    assert op.get(f"/v1/kyber/patterns/{pid}", params={"tenant_id": T}).status_code == 200
    rev = op.post(f"/v1/kyber/patterns/{pid}/review", params={"tenant_id": T},
                  json={"verdict": "malicious", "reason": "operator confirmed the ring"})
    assert rev.json()["data"]["review_history"][-1]["reviewer_id"].startswith("kyber:")
    assert op.post(f"/v1/kyber/patterns/{pid}/promote", params={"tenant_id": T},
                   json={"reason": "operator promotion to risk"}).status_code == 200
    assert op.get("/v1/kyber/patterns/stats", params={"tenant_id": T}).status_code == 200

    customer = _client(_tenant(permissions=(Permissions.READ, Permissions.WRITE, Permissions.ADMIN)), kyber=True)
    assert customer.get("/v1/kyber/patterns/queue", params={"tenant_id": T}).status_code == 403
    assert _client(None, kyber=True).get("/v1/kyber/patterns/queue", params={"tenant_id": T}).status_code == 401


def test_routes_are_classified_by_the_route_registry():
    from governance.security.request_context import require_kyber_operator

    assert require_kyber_operator in [d.dependency for d in pd_routes.kyber_router.dependencies]
    for route in pd_routes.router.routes:
        assert classify(route.path).domain != "unclassified", route.path
    for route in pd_routes.kyber_router.routes:
        policy = classify(route.path)
        assert policy.kyber_operator_required, route.path
