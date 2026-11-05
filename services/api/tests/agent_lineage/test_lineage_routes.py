"""HTTP surface: auth, tenant from context not path, disabled-by-flag, bad input."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from actions.agent_lineage import routes as R
from actions.agent_lineage import service as svc
from actions.agent_lineage import synthetic as S
from actions.agent_lineage.engine import LineageEngine
from actions.agent_lineage.repository import InMemoryLineageRepository
from shared.common.common import AetherError, ForbiddenError

T = S.TENANT


class _Tenant:
    def __init__(self, tenant_id, permissions):
        self.tenant_id = tenant_id
        self.permissions = permissions
        self.user_id = "user-1"

    def has_permission(self, perm):
        return perm in self.permissions

    def require_permission(self, perm):
        if perm not in self.permissions:
            raise ForbiddenError(f"missing {perm}")


def _app(tenant):
    app = FastAPI()
    app.include_router(R.router)
    app.include_router(R.kyber_router)

    @app.middleware("http")
    async def _attach(request: Request, call_next):
        request.state.tenant = tenant
        return await call_next(request)

    @app.exception_handler(AetherError)
    async def _errors(_request, exc):
        return JSONResponse(status_code=exc.code.value, content={"error": str(exc)})

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def flags(monkeypatch):
    state = SimpleNamespace(external_agent_telemetry=SimpleNamespace(registry_enabled=True, kyber_enabled=True))
    monkeypatch.setattr(R, "settings", state)
    return state


@pytest.fixture
def populated(flags):
    repo = InMemoryLineageRepository()
    fixture = S.build_fixture(100)

    async def seed():
        engine = LineageEngine(T)
        S.load(engine, fixture)
        await repo.apply(engine.resolve())

    import asyncio

    asyncio.run(seed())
    svc.set_service(svc.AgentLineageService(repo))
    yield repo
    svc.set_service(None)


def test_routes_are_off_unless_the_registry_flag_is_on(populated, flags):
    flags.external_agent_telemetry.registry_enabled = False
    client = _app(_Tenant(T, {"agent:manage"}))
    assert client.get(f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}/summary").status_code == 404


def test_reads_require_agent_manage(populated):
    client = _app(_Tenant(T, set()))
    assert client.get(f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}/summary").status_code == 403


def test_every_read_route_answers_with_a_disclosure(populated):
    client = _app(_Tenant(T, {"agent:manage"}))
    base = f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}"
    for path in ("summary", "agents", "clusters", "tree", "restatements"):
        body = client.get(f"{base}/{path}").json()
        assert body["data"]["disclosure"]["projection_version"], path
    assert client.get(f"{base}/risk").json()["data"]["scale_is_context"] is True
    orch = "/v1/agent-lineage/agents/legit-orch"
    assert client.get(orch).json()["data"]["node"]["root_agent_id"] == "legit-orch"
    assert client.get(f"{orch}/counts").json()["data"]["direct_child_count"] >= 1
    assert client.get(f"{orch}/descendants").json()["data"]["items"]
    assert client.get(f"{orch}/ancestors").json()["data"]["items"] == []


def test_tenant_comes_from_context_never_the_path(populated):
    other = _app(_Tenant("tenant-other", {"agent:manage"}))
    body = other.get(f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}/summary").json()["data"]
    assert body["direct_agents"] is None and body["disclosure"]["completeness"] == "unknown"
    assert other.get(f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}/agents").json()["data"]["items"] == []


def test_bad_input_is_a_client_error(populated):
    client = _app(_Tenant(T, {"agent:manage"}))
    base = f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}/agents"
    assert client.get(f"{base}?cursor=garbage").status_code == 400
    assert client.get(f"{base}?relationship=sideways").status_code == 400
    assert client.get(f"{base}?page_size=100000").status_code == 422


def test_kyber_needs_admin_and_its_flag(populated, flags):
    path = f"/v1/admin/kyber/agent-lineage/tenants/{T}/principals/{S.MALICIOUS_HUMAN}/investigation"
    assert _app(_Tenant(T, {"agent:manage"})).get(path).status_code in (401, 403)
    admin = _app(_Tenant("operator", {"admin"}))
    body = admin.get(path).json()["data"]
    assert body["linkage"]["verified_links"] >= 1
    flags.external_agent_telemetry.kyber_enabled = False
    assert admin.get(path).status_code == 404


def test_a_declaration_cannot_certify_itself_as_proof(populated):
    client = _app(_Tenant(T, {"agent:manage"}))
    response = client.post("/v1/agent-lineage/bindings", json={
        "kind": "agent", "principal_entity_id": "human:h9", "agent_entity_id": "a9",
        "evidence_class": "VERIFIED_AUTHORITY",
    })
    assert response.status_code == 201
    assert response.json()["data"]["evidence_class"] == "TENANT_DECLARED"
    bad = client.post("/v1/agent-lineage/bindings", json={"kind": "agent", "principal_entity_id": "human:h9"})
    assert bad.status_code == 400
