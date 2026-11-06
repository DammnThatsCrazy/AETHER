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


def test_a_binding_cannot_make_an_agent_its_own_principal(populated):
    client = _app(_Tenant(T, {"agent:manage"}))
    response = client.post("/v1/agent-lineage/bindings", json={
        "kind": "agent", "principal_entity_id": "same", "agent_entity_id": "same",
    })
    assert response.status_code == 400


def test_reconcile_enqueues_a_job_instead_of_running_in_the_request(populated, monkeypatch):
    calls = []

    class _Jobs:
        async def enqueue(self, tenant_id, job_type, payload, **_):
            calls.append((tenant_id, job_type, payload))
            return {"id": "job-1", "status": "queued"}

    monkeypatch.setattr("workers.jobs.service.get_jobs_service", lambda: _Jobs())
    response = _app(_Tenant(T, {"agent:manage"})).post("/v1/agent-lineage/reconcile?full=true")
    assert response.status_code == 202
    assert calls == [(T, "agent_lineage.reconcile", {"full": True})]


def test_export_goes_through_export_governance_and_needs_export_permission(populated, monkeypatch):
    audited, queued = [], []

    async def authorize(**kwargs):
        audited.append(kwargs)

    async def request_export(tenant_id, **kwargs):
        queued.append((tenant_id, kwargs["params"]))
        return {"job_id": "job-2", "status": "queued"}

    from governance.security.export_governance import audit_export_governance

    monkeypatch.setattr(audit_export_governance, "authorize_create", authorize)
    monkeypatch.setattr("ingestion.export.service.request_export", request_export)
    path = f"/v1/agent-lineage/principals/{S.LEGIT_HUMAN}/export"
    assert _app(_Tenant(T, {"agent:manage"})).post(path, json={}).status_code == 403
    assert audited == [] and queued == []
    response = _app(_Tenant(T, {"agent:manage", "export"})).post(path, json={"after": "a1"})
    assert response.status_code == 202
    assert audited[0]["export_type"] == "agent_lineage"
    assert queued[0][1]["after"] == "a1"


def test_adjudication_needs_admin_a_named_user_and_evidence(populated):
    path = "/v1/agent-lineage/agents/mal-1/adjudication"
    body = {"verdict": "confirmed_malicious", "reason": "fraud confirmed", "evidence_refs": ["case-1"]}
    assert _app(_Tenant(T, {"agent:manage"})).put(path, json=body).status_code == 403
    key = _Tenant(T, {"agent:manage", "admin"})
    key.user_id = None
    assert _app(key).put(path, json=body).status_code == 400
    admin = _app(_Tenant(T, {"agent:manage", "admin"}))
    assert admin.put(path, json={**body, "evidence_refs": []}).status_code == 422
    assert admin.put(path, json={**body, "verdict": "guilty"}).status_code == 422
    response = admin.put(path, json=body)
    assert response.status_code == 200
    assert response.json()["data"]["adjudicated_by"] == "user-1"


def test_registering_a_signing_key_needs_admin_a_user_and_one_key_per_agent(monkeypatch):
    import base64

    from actions.agent import deployment_routes as DR

    monkeypatch.setattr(DR, "_require_registry_enabled", lambda: None)
    rows = [{"id": "dep-held", "attestation_public_key": base64.b64encode(b"k" * 32).decode()}]

    class _Repo:
        async def list(self, tenant_id, agent_id=None, **_):
            return rows

    monkeypatch.setattr(DR, "_repo", lambda: _Repo())

    class _Request:
        def __init__(self, tenant):
            self.state = SimpleNamespace(tenant=tenant)

    import asyncio

    new_key = base64.b64encode(b"n" * 32).decode()
    with pytest.raises(ForbiddenError):
        asyncio.run(DR._authorize_attestation_key(_Request(_Tenant(T, {"agent:manage"})), "victim", new_key))
    keyless = _Tenant(T, {"agent:manage", "admin"})
    keyless.user_id = None
    from shared.common.common import BadRequestError, ConflictError

    with pytest.raises(BadRequestError):
        asyncio.run(DR._authorize_attestation_key(_Request(keyless), "victim", new_key))
    admin = _Tenant(T, {"agent:manage", "admin"})
    with pytest.raises(ConflictError):
        asyncio.run(DR._authorize_attestation_key(_Request(admin), "victim", new_key))
    asyncio.run(DR._authorize_attestation_key(_Request(admin), "victim", rows[0]["attestation_public_key"]))
    asyncio.run(DR._authorize_attestation_key(_Request(admin), "victim", new_key, "dep-held"))
