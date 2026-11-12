"""Authorization and tenant isolation of the semantic HTTP surface.

These drive the real routers over HTTP with a real ``TenantContext`` (the object
the auth middleware actually attaches), not hand-built stand-ins that carry
attributes the real context lacks. The earlier handler guards read
``is_suspended`` / ``is_admin``, which ``TenantContext`` does not have, so a
suspended tenant was never refused and a genuine Kyber operator was always
refused; stand-ins with those attributes hid both.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from config.settings import Environment, settings
from governance.security.route_registry import classify
from intelligence.semantic_intelligence import routes as semantic_routes
from intelligence.semantic_intelligence import service as service_mod
from intelligence.semantic_intelligence.engine import get_store, set_store
from intelligence.semantic_intelligence.service import SemanticIntelligenceService
from intelligence.semantic_intelligence.store import DurableSemanticSentimentStore
from repositories.repos import reset_in_memory_stores
from shared.auth.auth import Permissions, Role, TenantContext
from shared.common.common import AetherError

TENANT_A = "tenant_authz_alpha"
TENANT_B = "tenant_authz_bravo"

BODY = {
    "source_event_id": "evt_authz_1",
    "actor_ref": "profile_authz",
    "primary_subject_ref": "prod_authz",
    "content": "I recommend this product, it is excellent",
    "campaign_id": "camp_authz",
    "purposes": ["analytics"],
}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    # Local development (the default for tests) tolerates a missing tenant; the
    # tests that matter for production move the routes out of it explicitly.
    monkeypatch.setattr(semantic_routes.settings, "env", Environment.LOCAL)
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


def _tenant(tenant_id=TENANT_A, permissions=(Permissions.READ, Permissions.WRITE), **kw):
    return TenantContext(
        tenant_id=tenant_id, user_id=f"user-{tenant_id}", role=Role.VIEWER,
        permissions=list(permissions), **kw,
    )


def _client(tenant=None, *, kyber: bool = False) -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _aether_error(request, exc):
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    if tenant is not None:

        @app.middleware("http")
        async def _inject(request, call_next):
            request.state.tenant = tenant
            return await call_next(request)

    app.include_router(semantic_routes.router)
    app.include_router(semantic_routes.campaign_router)
    app.include_router(semantic_routes.graph_router)
    app.include_router(semantic_routes.population_router)
    if kyber:
        app.include_router(semantic_routes.kyber_router)
    return TestClient(app, raise_server_exceptions=False)


# ── Which tenant a request acts as ───────────────────────────────────────────

def test_authenticated_tenant_wins_over_a_spoofed_header():
    created = _client(_tenant(TENANT_A)).post(
        "/v1/semantic/observations", json=BODY, headers={"x-tenant-id": TENANT_B},
    )
    assert created.status_code == 200, created.text
    obs_id = created.json()["data"]["semantic_observation"]["observation_id"] \
        if "observation_id" in created.json()["data"]["semantic_observation"] \
        else created.json()["data"]["semantic_observation"]["id"]

    # It landed under the authenticated tenant, not the one the header named.
    assert _client(_tenant(TENANT_B)).get(f"/v1/semantic/observations/{obs_id}").status_code == 404
    assert _client(_tenant(TENANT_A)).get(f"/v1/semantic/observations/{obs_id}").status_code == 200


def test_outside_local_development_an_unauthenticated_request_is_refused(monkeypatch):
    monkeypatch.setattr(semantic_routes.settings, "env", Environment.STAGING)
    client = _client(None)
    for method, path in (
        ("get", "/v1/semantic/observations"),
        ("post", "/v1/semantic/observations"),
        ("get", "/v1/semantic/narratives"),
        ("get", "/v1/campaigns/camp_x/semantic-impact"),
    ):
        response = getattr(client, method)(
            path, headers={"x-tenant-id": TENANT_A},
            **({"json": BODY} if method == "post" else {}),
        )
        assert response.status_code == 401, (path, response.status_code, response.text)


def test_local_development_may_still_name_a_tenant_by_header():
    created = _client(None).post(
        "/v1/semantic/observations", json=BODY, headers={"x-tenant-id": "tenant_dev_header"},
    )
    assert created.status_code == 200
    listed = _client(None).get("/v1/semantic/observations", headers={"x-tenant-id": "tenant_dev_header"})
    assert listed.json()["data"]["count"] == 1


# ── What a credential may do ─────────────────────────────────────────────────

def test_read_only_credential_cannot_write():
    reader = _client(_tenant(permissions=(Permissions.READ,)))
    assert reader.get("/v1/semantic/observations").status_code == 200
    assert reader.post("/v1/semantic/observations", json=BODY).status_code == 403
    assert reader.post("/v1/semantic/reprocess").status_code == 403
    assert reader.post("/v1/semantic/reprocess/job_x/cancel").status_code == 403


def test_write_only_credential_cannot_read():
    writer = _client(_tenant(permissions=(Permissions.WRITE,)))
    assert writer.post("/v1/semantic/observations", json=BODY).status_code == 200
    for path in (
        "/v1/semantic/observations",
        "/v1/semantic/entities/prod_authz",
        "/v1/semantic/narratives",
        "/v1/campaigns/camp_authz/semantic-impact",
    ):
        assert writer.get(path).status_code == 403, path
    assert writer.post("/v1/graph/semantic-overlay", json={"subject_ref": "prod_authz"}).status_code == 403
    assert writer.post("/v1/population/semantic-compare", json={"subjects": ["x"]}).status_code == 403


@pytest.mark.parametrize(
    "state", ["tenant_status", "organization_status", "membership_status", "credential_status"],
)
def test_a_tenant_that_is_not_serving_is_refused_on_read_and_write(state):
    inactive = _client(_tenant(**{state: "suspended"}))
    assert inactive.get("/v1/semantic/observations").status_code == 403
    assert inactive.post("/v1/semantic/observations", json=BODY).status_code == 403


# ── Tenant isolation, endpoint by endpoint ───────────────────────────────────

def _seed_tenant_a() -> tuple[str, str]:
    """Tenant A's observation id and its replay job id."""
    a = _client(_tenant(TENANT_A))
    created = a.post("/v1/semantic/observations", json=BODY)
    assert created.status_code == 200, created.text
    observation = created.json()["data"]["semantic_observation"]
    obs_id = observation.get("observation_id") or observation["id"]
    job = a.post("/v1/semantic/reprocess", params={"dry_run": "true"})
    assert job.status_code == 200, job.text
    data = job.json()["data"]
    return obs_id, data.get("job_id") or data["id"]


def test_tenant_b_cannot_see_or_control_tenant_a_by_id():
    obs_id, job_id = _seed_tenant_a()
    b = _client(_tenant(TENANT_B))
    assert b.get(f"/v1/semantic/observations/{obs_id}").status_code == 404
    assert b.get(f"/v1/semantic/reprocess/{job_id}").status_code == 404
    for action in ("pause", "resume", "cancel"):
        assert b.post(f"/v1/semantic/reprocess/{job_id}/{action}").status_code == 404, action
    # ...and attempting it did not disturb A's job.
    a = _client(_tenant(TENANT_A))
    assert a.get(f"/v1/semantic/reprocess/{job_id}").status_code == 200


def test_no_listing_or_rollup_leaks_tenant_a_data_to_tenant_b():
    obs_id, _ = _seed_tenant_a()
    b = _client(_tenant(TENANT_B))
    listed = b.get("/v1/semantic/observations")
    assert listed.json()["data"]["count"] == 0

    leaks = []
    probes = [
        ("get", "/v1/semantic/observations?subject=prod_authz", None),
        ("get", "/v1/semantic/entities/prod_authz", None),
        ("get", "/v1/semantic/entities/prod_authz/sentiment", None),
        ("get", "/v1/semantic/entities/prod_authz/sentiment-state", None),
        ("get", "/v1/semantic/entities/prod_authz/episodes", None),
        ("get", "/v1/semantic/entities/prod_authz/timeline", None),
        ("get", "/v1/semantic/narratives", None),
        ("get", "/v1/semantic/cascades", None),
        ("get", "/v1/semantic/relationships/profile_authz/prod_authz", None),
        ("get", "/v1/campaigns/camp_authz/semantic-impact", None),
        ("get", "/v1/campaigns/camp_authz/sentiment", None),
        ("post", "/v1/graph/semantic-overlay", {"subject_ref": "prod_authz"}),
        ("post", "/v1/population/semantic-compare", {"subjects": ["prod_authz"]}),
    ]
    for method, path, body in probes:
        response = getattr(b, method)(path, **({"json": body} if body is not None else {}))
        text = json.dumps(response.json())
        # An empty or not-found answer is fine; carrying A's evidence is not.
        if obs_id in text or TENANT_A in text or BODY["source_event_id"] in text:
            leaks.append((path, response.status_code))
    assert not leaks, f"tenant A data visible to tenant B via: {leaks}"

    # The same probes as tenant A do see it (so the check above is not vacuous).
    a = _client(_tenant(TENANT_A))
    assert a.get("/v1/semantic/observations").json()["data"]["count"] == 1


# ── The operator surface ─────────────────────────────────────────────────────

def test_a_genuine_kyber_operator_can_use_the_operator_routes():
    """A real operator is a TenantContext carrying the configured operator grant;
    the handlers used to demand an ``is_admin`` attribute it does not have."""
    operator = _tenant(
        "olympus_op", permissions=(settings.security_governance.kyber_operator_permission,),
    )
    client = _client(operator, kyber=True)
    assert client.get("/v1/kyber/semantic/fleet-health").status_code == 200
    assert client.get("/v1/kyber/semantic/review-queue").status_code == 200


def test_operator_routes_refuse_customers_and_anonymous_callers():
    customer = _client(_tenant(TENANT_A, permissions=(Permissions.READ, Permissions.WRITE, Permissions.ADMIN)),
                       kyber=True)
    assert customer.get("/v1/kyber/semantic/fleet-health").status_code == 403
    assert customer.get("/v1/kyber/semantic/review-queue").status_code == 403
    assert customer.post(
        "/v1/kyber/semantic/review-queue/srq_x/resolve", json={"disposition": "approve"},
    ).status_code == 403
    assert _client(None, kyber=True).get("/v1/kyber/semantic/fleet-health").status_code == 401


def test_the_operator_router_is_gated_by_the_canonical_kyber_dependency():
    from governance.security.request_context import require_kyber_operator

    dependencies = [d.dependency for d in semantic_routes.kyber_router.dependencies]
    assert require_kyber_operator in dependencies


# ── Route policy classification ──────────────────────────────────────────────

def test_every_semantic_route_is_classified_by_the_route_policy():
    unclassified = []
    for router in (
        semantic_routes.router, semantic_routes.kyber_router, semantic_routes.campaign_router,
        semantic_routes.graph_router, semantic_routes.population_router,
    ):
        for route in router.routes:
            template = route.path.split("{", 1)[0].rstrip("/") or route.path
            if classify(template) is None:
                unclassified.append(route.path)
    assert not unclassified, f"semantic routes the route policy cannot classify: {unclassified}"
