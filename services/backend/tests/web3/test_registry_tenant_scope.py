"""Web3 and cross-domain registries: writes work, and every row belongs to its tenant.

Before this, every POST in ``/v1/web3`` and ``/v1/crossdomain`` raised
``AttributeError`` (the registries called ``self.upsert``, which no base class
defined), and the reads returned every tenant's rows.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from repositories.repos import TenantOwnedRepository, reset_in_memory_stores
from services.crossdomain import routes as cd_routes
from services.web3 import registries as web3_registries
from services.web3 import routes as web3_routes
from shared.auth.auth import Role, TenantContext
from shared.decorators import register_error_handlers


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _client(tenant_id: str, role: Role = Role.ADMIN) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(web3_routes.router)
    app.include_router(cd_routes.router)

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = TenantContext(tenant_id=tenant_id, role=role, permissions=[])
        request.state.tenant_id = tenant_id
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False)


# ── the repository contract ────────────────────────────────────────────────


class _Demo(TenantOwnedRepository):
    def __init__(self) -> None:
        super().__init__("tenant_owned_demo")


@pytest.mark.asyncio
async def test_unbound_reads_raise_instead_of_returning_everything():
    repo = _Demo()
    await repo.upsert("a", {"v": 1}, "t1")
    with pytest.raises(RuntimeError):
        await repo.find_many()
    with pytest.raises(RuntimeError):
        await repo.find_by_id("a")
    with pytest.raises(RuntimeError):
        await repo.count()


@pytest.mark.asyncio
async def test_a_tenant_only_sees_its_own_rows():
    repo = _Demo()
    await repo.upsert("a", {"v": 1}, "t1")
    await repo.upsert("b", {"v": 2}, "t2")
    assert [r["id"] for r in await repo.for_tenant("t1").find_many()] == ["a"]
    assert await repo.for_tenant("t1").find_by_id("b") is None
    assert await repo.for_tenant("t2").count() == 1


@pytest.mark.asyncio
async def test_another_tenant_cannot_overwrite_a_row_it_does_not_own():
    from shared.common.common import ConflictError

    repo = _Demo()
    await repo.upsert("a", {"v": 1}, "t1")
    with pytest.raises(ConflictError):
        await repo.upsert("a", {"v": 99}, "t2")
    assert (await repo.for_tenant("t1").find_by_id("a"))["v"] == 1


@pytest.mark.asyncio
async def test_re_registering_keeps_created_at_and_updates_fields():
    repo = _Demo()
    first = await repo.upsert("a", {"v": 1}, "t1")
    second = await repo.upsert("a", {"v": 2}, "t1")
    assert second["v"] == 2
    assert second["created_at"] == first["created_at"]


@pytest.mark.asyncio
async def test_shared_tenant_rows_are_readable_by_every_tenant_but_not_overwritable():
    from shared.common.common import ConflictError

    chains = web3_registries.ChainRegistry()
    await chains.register({"chain_id": "ethereum", "status": "active"})  # platform seed
    await chains.for_tenant("t1").register({"chain_id": "private-net", "status": "active"})

    seen = {c["chain_id"] for c in await chains.for_tenant("t1").find_many()}
    assert seen == {"ethereum", "private-net"}
    assert {c["chain_id"] for c in await chains.for_tenant("t2").find_many()} == {"ethereum"}
    with pytest.raises(ConflictError):
        await chains.for_tenant("t1").register({"chain_id": "ethereum", "status": "retired"})


# ── web3 routes ────────────────────────────────────────────────────────────


def test_web3_registration_works_and_is_private_to_the_tenant():
    a, b = _client("t1"), _client("t2")
    assert a.post("/v1/web3/contracts", json={
        "chain_id": "base", "address": "0xABC", "protocol_id": "p1",
    }).status_code == 200
    assert a.post("/v1/web3/tokens", json={"token_id": "tok", "symbol": "TOK"}).status_code == 200

    assert a.get("/v1/web3/tokens").json()["count"] == 1
    assert b.get("/v1/web3/tokens").json()["count"] == 0
    assert b.get("/v1/web3/contracts/base/0xabc").json().get("error") or \
        "contract" not in b.get("/v1/web3/contracts/base/0xabc").json()


def test_web3_cannot_take_over_another_tenants_id():
    a, b = _client("t1"), _client("t2")
    assert a.post("/v1/web3/tokens", json={"token_id": "tok", "symbol": "MINE"}).status_code == 200
    taken = b.post("/v1/web3/tokens", json={"token_id": "tok", "symbol": "THEIRS"})
    assert taken.status_code == 409
    assert a.get("/v1/web3/tokens").json()["tokens"][0]["symbol"] == "MINE"


def test_web3_observations_and_migrations_are_written_for_the_caller():
    a, b = _client("t1"), _client("t2")
    resp = a.post("/v1/web3/classify/observation", json={
        "observation_type": "contract_call", "chain_id": "base",
        "contract_address": "0xDEF", "from_address": "0xW",
    })
    assert resp.status_code == 200
    # Classification registered the contract for t1 only.
    assert a.get("/v1/web3/contracts/unclassified").json()["count"] >= 1
    assert b.get("/v1/web3/contracts/unclassified").json()["count"] == 0


# ── cross-domain routes ────────────────────────────────────────────────────


def test_crossdomain_financial_data_is_private_to_the_tenant():
    a, b = _client("t1"), _client("t2")
    assert a.post("/v1/crossdomain/accounts", json={
        "account_id": "acct-1", "owner_entity_id": "ent-1", "institution_id": "inst-1",
    }).status_code == 200
    assert a.post("/v1/crossdomain/balances", json={
        "account_id": "acct-1", "as_of": "2026-01-01", "total": 100,
    }).status_code == 200
    assert a.post("/v1/crossdomain/positions", json={
        "account_id": "acct-1", "instrument_id": "i-1", "as_of": "2026-01-01",
    }).status_code in (200, 404, 405)

    assert a.get("/v1/crossdomain/accounts").json()["count"] == 1
    assert b.get("/v1/crossdomain/accounts").json()["count"] == 0
    assert "account" not in b.get("/v1/crossdomain/accounts/acct-1").json()
    assert b.get("/v1/crossdomain/balances/acct-1/latest").json().get("balance") in (None, {})
    assert b.get("/v1/crossdomain/coverage/status").json()["coverage"]["accounts"] == 0


def test_crossdomain_fusion_and_links_do_not_cross_tenants():
    a, b = _client("t1"), _client("t2")
    assert a.post("/v1/crossdomain/links", json={
        "source_entity_id": "ent-1", "target_entity_id": "ent-2",
        "link_signal": "email", "confidence": 0.9,
    }).status_code == 200
    assert a.get("/v1/crossdomain/links/ent-1").json()["count"] == 1
    assert b.get("/v1/crossdomain/links/ent-1").json()["count"] == 0
    assert b.get("/v1/crossdomain/links/high-confidence").json()["count"] == 0


def test_high_confidence_links_route_is_not_shadowed_by_the_entity_route():
    a = _client("t1")
    a.post("/v1/crossdomain/links", json={
        "source_entity_id": "e1", "target_entity_id": "e2", "link_signal": "email", "confidence": 0.95,
    })
    a.post("/v1/crossdomain/links", json={
        "source_entity_id": "e3", "target_entity_id": "e4", "link_signal": "phone", "confidence": 0.2,
    })
    body = a.get("/v1/crossdomain/links/high-confidence").json()
    assert body["min_confidence"] == 0.7 and body["count"] == 1


_SECRET = "t1-secret-marker"


def _seed_crossdomain(c: TestClient) -> None:
    posts = {
        "/v1/crossdomain/institutions": {"institution_id": "inst-1", "canonical_name": _SECRET},
        "/v1/crossdomain/accounts": {"account_id": "acct-1", "owner_entity_id": "ent-1", "institution_id": "inst-1", "nickname": _SECRET},
        "/v1/crossdomain/instruments": {"instrument_id": "ins-1", "symbol": "ABC", "name": _SECRET, "issuer_id": "iss-1"},
        "/v1/crossdomain/positions": {"account_id": "acct-1", "instrument_id": "ins-1", "as_of": "2026-01-01", "note": _SECRET},
        "/v1/crossdomain/orders": {"order_id": "ord-1", "account_id": "acct-1", "note": _SECRET},
        "/v1/crossdomain/executions": {"execution_id": "ex-1", "order_id": "ord-1", "account_id": "acct-1", "note": _SECRET},
        "/v1/crossdomain/balances": {"account_id": "acct-1", "as_of": "2026-01-01", "note": _SECRET},
        "/v1/crossdomain/cash-movements": {"movement_id": "m-1", "account_id": "acct-1", "note": _SECRET},
        "/v1/crossdomain/compliance/actions": {"action_id": "c-1", "entity_id": "ent-1", "note": _SECRET},
        "/v1/crossdomain/events": {"entity_id": "ent-1", "instrument_id": "ins-1", "note": _SECRET},
        "/v1/crossdomain/links": {"source_entity_id": "ent-1", "target_entity_id": "ent-2", "link_signal": "email", "confidence": 0.9, "note": _SECRET},
    }
    for path, body in posts.items():
        assert c.post(path, json=body).status_code == 200, path


_CROSSDOMAIN_READS = [
    "/v1/crossdomain/institutions", "/v1/crossdomain/institutions?q=t1",
    "/v1/crossdomain/institutions/inst-1",
    "/v1/crossdomain/accounts", "/v1/crossdomain/accounts?owner=ent-1",
    "/v1/crossdomain/accounts/acct-1", "/v1/crossdomain/accounts/acct-1/positions",
    "/v1/crossdomain/instruments", "/v1/crossdomain/instruments?q=ABC",
    "/v1/crossdomain/instruments/ins-1", "/v1/crossdomain/instruments/symbol/ABC",
    "/v1/crossdomain/positions/instrument/ins-1",
    "/v1/crossdomain/orders/acct-1",
    "/v1/crossdomain/executions/order/ord-1", "/v1/crossdomain/executions/account/acct-1",
    "/v1/crossdomain/balances/acct-1/latest", "/v1/crossdomain/cash-movements/acct-1",
    "/v1/crossdomain/compliance/actions/ent-1",
    "/v1/crossdomain/events/entity/ent-1", "/v1/crossdomain/events/instrument/ins-1",
    "/v1/crossdomain/links/ent-1", "/v1/crossdomain/links/high-confidence",
    "/v1/crossdomain/fusion/exposure/ent-1", "/v1/crossdomain/fusion/profile/ent-1",
    "/v1/crossdomain/coverage/status", "/v1/crossdomain/coverage/health",
]


@pytest.mark.parametrize("path", _CROSSDOMAIN_READS)
def test_no_crossdomain_read_returns_another_tenants_data(path):
    owner, other = _client("t1"), _client("t2")
    _seed_crossdomain(owner)
    # The owner can read it (the seed is real, not an empty-table pass)...
    if "coverage" not in path:
        assert _SECRET in owner.get(path).text or "fusion" in path or "?q=t1" in path, path
    # ...and nobody else can.
    resp = other.get(path)
    assert resp.status_code == 200, path
    assert _SECRET not in resp.text, path


# ── Reads need the read permission ─────────────────────────────────────────


def _client_with(permissions: list[str]) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(web3_routes.router)
    app.include_router(cd_routes.router)

    @app.middleware("http")
    async def tenant(request, call_next):
        request.state.tenant = TenantContext(tenant_id="t1", role=Role.VIEWER, permissions=permissions)
        request.state.tenant_id = "t1"
        return await call_next(request)

    return TestClient(app, raise_server_exceptions=False)


def _get_paths() -> list[str]:
    paths = []
    for router in (web3_routes.router, cd_routes.router):
        for route in router.routes:
            if "GET" in getattr(route, "methods", set()):
                paths.append(route.path)
    return paths


def test_every_get_route_in_both_routers_is_permission_checked():
    # A credential with write but not read is refused on every GET; with read it is not.
    writer, reader = _client_with(["write"]), _client_with(["read"])
    for template in _get_paths():
        path = template
        for part in ("{chain_id}", "{address}", "{protocol_id}", "{account_id}", "{institution_id}",
                     "{instrument_id}", "{symbol}", "{order_id}", "{entity_id}", "{domain:path}", "{domain}"):
            path = path.replace(part, "x")
        assert writer.get(path).status_code == 403, template
        assert reader.get(path).status_code != 403, template
