"""Kyber operator continuation routes — /v1/kyber/continuations.

Drives the real operator handler → shared ContinuationService → in-memory
repository path (local mode), supplying the ``KyberAccessContext`` the operator
auth dependency would produce. Verifies operator-scope binding (``o:{operator}``),
server-forced identity, ownership 404s, handoff token minting, the flag-off 404
gate, and that ``enqueue_sync_change`` is emitted with the operator scope. The
HTTP-surface test mounts the router and proves the Kyber workforce guard denies
an unauthenticated request at the edge.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from config.settings import ContinuationConfig
from repositories.continuation_repo import reset_continuation_memory
from shared.common.common import AetherError, NotFoundError
from services.continuation import service as continuation_service
from services.continuation import operator_routes
from services.continuation.operator_routes import operator_router
from services.continuation.routes import (
    ContinuationInput,
    ContinuationUpdate,
    HandoffRequest,
)
from services.kyber.access.contracts import WorkforcePrincipal, WorkforceSession
from services.kyber.access.dependencies import KyberAccessContext


def _run(coro):
    return asyncio.run(coro)


def _ctx(operator_id: str = "op-1") -> KyberAccessContext:
    """The real ``KyberAccessContext`` a workforce session would authorize.

    Mirrors ``tests/kyber/conftest.py.build_scoped_context``: a live, device-bound
    session plus an active principal — the shape ``require_kyber_access`` hands a
    handler after a successful evaluation.
    """
    session = WorkforceSession(
        token_hash=f"hash_{operator_id}",
        operator_id=operator_id,
        device_id="dev_test",
        status="active",
        authentication_strength="device_bound",
        environment="local",
    )
    principal = WorkforcePrincipal(
        operator_id=operator_id,
        email="operator@olympus.test",
        employment_status="active",
        kyber_enabled=True,
    )
    return KyberAccessContext(
        session=session,
        principal=principal,
        environment=session.environment,
    )


def _input(**over) -> ContinuationInput:
    base = dict(source_client="desktop", surface="graph", summary={"title": "Resume graph"})
    base.update(over)
    return ContinuationInput(**base)


def _seed_foreign(scope_operator: str, continuation_id: str, principal: str) -> None:
    """Seed a row inside ``scope_operator``'s scope but owned by ``principal``.

    Reaches through the shared service so the row lands in the same store the
    handlers read — the only way a foreign principal_id can exist inside an
    operator scope is if the caller lied about ownership, which this isolates.
    """
    ctx = operator_routes._build_context(_input(id=continuation_id), principal)
    _run(
        continuation_service.create(
            scope=continuation_service.operator_scope(scope_operator),
            principal_id=principal,
            app_kind="kyber",
            tenant_id=None,
            body=ctx,
            idempotency_key=None,
        )
    )


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    reset_continuation_memory()
    monkeypatch.setattr(
        operator_routes.settings, "continuation", ContinuationConfig(enabled=True)
    )
    yield
    reset_continuation_memory()


# ── Registration + auth surface ──────────────────────────────────────────────

def test_operator_router_registers_expected_routes():
    paths = {(r.path, tuple(sorted(r.methods))) for r in operator_router.routes}
    assert ("/v1/kyber/continuations", ("POST",)) in paths
    assert ("/v1/kyber/continuations/recent", ("GET",)) in paths
    assert ("/v1/kyber/continuations/{continuation_id}", ("GET",)) in paths
    assert ("/v1/kyber/continuations/{continuation_id}", ("PATCH",)) in paths
    assert ("/v1/kyber/continuations/{continuation_id}/handoff", ("POST",)) in paths
    assert ("/v1/kyber/continuations/{continuation_id}", ("DELETE",)) in paths


def _client() -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(operator_router)
    return TestClient(app, raise_server_exceptions=False)


def test_operator_continuations_deny_unauthenticated_requests() -> None:
    """No Kyber workforce session -> the kyber guard denies (never tenant auth)."""
    client = _client()
    create_body = {
        "source_client": "desktop",
        "surface": "graph",
        "summary": {"title": "Resume"},
    }
    patch_body = dict(create_body, expected_state_revision=0)
    for method, path, json in [
        ("get", "/v1/kyber/continuations/recent", None),
        ("get", "/v1/kyber/continuations/kc_missing", None),
        ("post", "/v1/kyber/continuations", create_body),
        ("patch", "/v1/kyber/continuations/kc_missing", patch_body),
        ("post", "/v1/kyber/continuations/kc_missing/handoff", {"mode": "explicit"}),
        ("delete", "/v1/kyber/continuations/kc_missing", None),
    ]:
        kwargs = {"json": json} if json is not None else {}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code in (401, 403), f"{method} {path} -> {resp.status_code}"


# ── Create / read ────────────────────────────────────────────────────────────

def test_create_is_scoped_to_operator():
    resp = _run(operator_routes.create_operator_continuation(
        payload=_input(), context=_ctx("op-1")
    ))
    data = resp.data
    assert data["id"].startswith("cont_")
    assert data["principal_id"] == "op-1"
    assert data["tenant_id"] is None
    assert data["app_kind"] == "kyber"
    assert data["state_revision"] == 0


def test_create_is_idempotent():
    a = _run(operator_routes.create_operator_continuation(
        payload=_input(), idempotency_key="opk1", context=_ctx("op-1")
    )).data
    b = _run(operator_routes.create_operator_continuation(
        payload=_input(), idempotency_key="opk1", context=_ctx("op-1")
    )).data
    assert b["id"] == a["id"]
    assert b["replayed"] is True


def test_recent_and_get_scoped_to_operator():
    created = _run(operator_routes.create_operator_continuation(
        payload=_input(id="c1"), context=_ctx("op-1")
    )).data
    got = _run(operator_routes.get_operator_continuation(
        continuation_id="c1", context=_ctx("op-1")
    )).data
    assert got["id"] == created["id"]
    recent = _run(operator_routes.recent_operator_continuations(
        limit=25, context=_ctx("op-1")
    )).data
    assert any(c["id"] == "c1" for c in recent["continuations"])


def test_operator_scope_isolates_other_operators():
    _run(operator_routes.create_operator_continuation(
        payload=_input(id="c1"), context=_ctx("op-1")
    ))
    # Row absent from op-2's scope reads as a 404, never as a cross-scope leak.
    with pytest.raises(NotFoundError):
        _run(operator_routes.get_operator_continuation(
            continuation_id="c1", context=_ctx("op-2")
        ))


def test_get_absent_is_404():
    with pytest.raises(NotFoundError):
        _run(operator_routes.get_operator_continuation(
            continuation_id="nope", context=_ctx("op-1")
        ))


# ── Update / delete / handoff ownership ──────────────────────────────────────

def test_update_own_bumps_revision():
    _run(operator_routes.create_operator_continuation(
        payload=_input(id="c1"), context=_ctx("op-1")
    ))
    upd = ContinuationUpdate(
        source_client="mobile_ios", surface="graph",
        summary={"title": "On phone"}, expected_state_revision=0,
    )
    out = _run(operator_routes.update_operator_continuation(
        payload=upd, continuation_id="c1", context=_ctx("op-1")
    )).data
    assert out["state_revision"] == 1


def test_update_foreign_continuation_is_404():
    _seed_foreign("op-a", "c1", "op-b")
    upd = ContinuationUpdate(
        source_client="desktop", surface="graph",
        summary={"title": "Hijack"}, expected_state_revision=0,
    )
    with pytest.raises(NotFoundError):
        _run(operator_routes.update_operator_continuation(
            payload=upd, continuation_id="c1", context=_ctx("op-a")
        ))


def test_delete_own_and_absent_is_404():
    _run(operator_routes.create_operator_continuation(
        payload=_input(id="c1"), context=_ctx("op-1")
    ))
    out = _run(operator_routes.delete_operator_continuation(
        continuation_id="c1", context=_ctx("op-1")
    )).data
    assert out["deleted"] is True
    with pytest.raises(NotFoundError):
        _run(operator_routes.delete_operator_continuation(
            continuation_id="c1", context=_ctx("op-1")
        ))


def test_delete_foreign_continuation_is_404():
    _seed_foreign("op-a", "c1", "op-b")
    with pytest.raises(NotFoundError):
        _run(operator_routes.delete_operator_continuation(
            continuation_id="c1", context=_ctx("op-a")
        ))


def test_handoff_mints_deep_link_token():
    _run(operator_routes.create_operator_continuation(
        payload=_input(id="c1"), context=_ctx("op-1")
    ))
    sel = _run(operator_routes.handoff_operator_continuation(
        payload=HandoffRequest(mode="explicit", resource_ids=["a", "b"]),
        continuation_id="c1",
        context=_ctx("op-1"),
    )).data
    assert sel["token"].startswith("sel_")
    assert sel["mode"] == "explicit"
    assert sel["continuation_id"] == "c1"


def test_handoff_foreign_continuation_is_404():
    _seed_foreign("op-a", "c1", "op-b")
    with pytest.raises(NotFoundError):
        _run(operator_routes.handoff_operator_continuation(
            payload=HandoffRequest(mode="query", saved_view_id="sv1"),
            continuation_id="c1",
            context=_ctx("op-a"),
        ))


# ── Flag gate + sync emission ────────────────────────────────────────────────

def test_flag_off_404(monkeypatch):
    monkeypatch.setattr(
        operator_routes.settings, "continuation", ContinuationConfig(enabled=False)
    )
    with pytest.raises(NotFoundError):
        _run(operator_routes.create_operator_continuation(
            payload=_input(), context=_ctx("op-1")
        ))


def test_create_emits_sync_change_with_operator_scope(monkeypatch):
    captured: dict = {}

    async def _fake(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(operator_routes, "enqueue_sync_change", _fake)
    created = _run(operator_routes.create_operator_continuation(
        payload=_input(id="c1"), context=_ctx("op-1")
    )).data
    assert captured["scope_key"] == "o:op-1"
    assert captured["principal_id"] == "op-1"
    assert captured["change_type"] == "continuation_changed"
    assert captured["resource_kind"] == "continuation"
    assert captured["resource_id"] == created["id"]
    assert captured["revision"] == "0"
