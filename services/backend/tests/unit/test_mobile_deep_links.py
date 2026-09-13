"""Deep-link resolution over the in-memory installation + continuation repos.

Exercises the fail-closed ordered checks in ``services.mobile.service.resolve_deep_link``:
unknown / unowned / revoked installation, cross-scope / cross-plane / expired
continuation all collapse to the same unresolvable result (no existence leak); a
restricted continuation requires a stepped-up session; a resolvable owned
continuation returns a bounded, reference-only projection.
"""
from __future__ import annotations

import asyncio

import pytest

from repositories.continuation_repo import reset_continuation_memory
from repositories.installation_repo import reset_installation_memory
from services.mobile import routes as mobile_routes
from services.mobile import service as mobile_service
from services.mobile.routes import DeepLinkResolveRequest, RegistrationRequest
from services.continuation import service as continuation_service
from shared.continuation.models import ContinuationContext, ContinuationSummary

from types import SimpleNamespace


def _run(coro):
    return asyncio.run(coro)


TENANT = "tenant-a"
PRINCIPAL = "user-1"
SCOPE = mobile_service.tenant_scope(TENANT)


class _Tenant:
    tenant_id = TENANT
    user_id = PRINCIPAL
    _perms: tuple[str, ...] = ()

    def require_permission(self, permission):
        return None

    def has_permission(self, permission):
        return permission in self._perms


class _ElevatedTenant(_Tenant):
    _perms = ("step_up",)


def _req(tenant=None):
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant or _Tenant()))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_installation_memory()
    reset_continuation_memory()
    monkeypatch.setattr(mobile_routes, "_require_enabled", lambda: None)
    yield
    reset_installation_memory()
    reset_continuation_memory()


async def _install(installation_id="dev-1", principal=PRINCIPAL):
    return await mobile_service.register(
        scope=SCOPE, principal_id=principal, installation_id=installation_id,
        platform="ios", bundle_id="com.aether.app", environment="production",
        device_name=None, push_token=None, push_provider=None,
    )


async def _seed_continuation(
    *, scope=SCOPE, app_kind="aether", sensitivity="standard", expires_at=None,
    principal=PRINCIPAL, cont_id="cont-1",
):
    body = ContinuationContext(
        id=cont_id, principal_id=principal, app_kind=app_kind,
        source_client="mobile_ios", surface="graph",
        summary=ContinuationSummary(title="Resume graph"),
        sensitivity=sensitivity, expires_at=expires_at,
        updated_at="2026-01-01T00:00:00+00:00",
    )
    row = await continuation_service.create(
        scope=scope, principal_id=principal, app_kind=app_kind,
        tenant_id=TENANT, body=body,
    )
    return row["id"] if isinstance(row, dict) and "id" in row else cont_id


# ── happy path ───────────────────────────────────────────────────────────────

def test_resolves_owned_continuation():
    _run(_install())
    cid = _run(_seed_continuation())
    out = _run(
        mobile_service.resolve_deep_link(
            scope=SCOPE, principal_id=PRINCIPAL, installation_id="dev-1", continuation_id=cid
        )
    )
    assert out["resolved"] is True
    proj = out["continuation"]
    assert proj["id"] == cid
    assert proj["app_kind"] == "aether"
    assert proj["surface"] == "graph"
    assert proj["summary"]["title"] == "Resume graph"


def test_route_returns_projection():
    _run(_install())
    cid = _run(_seed_continuation())
    resp = _run(
        mobile_routes.resolve_deep_link(
            _req(), DeepLinkResolveRequest(installation_id="dev-1", continuation_id=cid)
        )
    )
    assert resp.data["resolved"] is True


# ── fail-closed: every leak-prone failure looks identical ────────────────────

def _unresolvable(**over):
    base = dict(scope=SCOPE, principal_id=PRINCIPAL, installation_id="dev-1", continuation_id="cont-1")
    base.update(over)
    return _run(mobile_service.resolve_deep_link(**base))


def test_unknown_installation_unresolvable():
    _run(_seed_continuation())
    out = _unresolvable(installation_id="nope")
    assert out == {"resolved": False, "reason": "unresolvable"}


def test_unowned_installation_unresolvable():
    _run(_install(principal="someone-else"))
    _run(_seed_continuation())
    out = _unresolvable()
    assert out["resolved"] is False and out["reason"] == "unresolvable"


def test_revoked_installation_unresolvable():
    _run(_install())
    _run(mobile_service.revoke(SCOPE, "dev-1"))
    _run(_seed_continuation())
    out = _unresolvable()
    assert out["resolved"] is False and out["reason"] == "unresolvable"


def test_missing_continuation_unresolvable():
    _run(_install())
    out = _unresolvable(continuation_id="ghost")
    assert out["resolved"] is False and out["reason"] == "unresolvable"


def test_cross_scope_continuation_unresolvable():
    _run(_install())
    # Continuation seeded into another tenant's scope must not resolve here.
    _run(_seed_continuation(scope="t:other-tenant", cont_id="cont-x"))
    out = _unresolvable(continuation_id="cont-x")
    assert out["resolved"] is False and out["reason"] == "unresolvable"


def test_cross_plane_continuation_unresolvable():
    _run(_install())
    _run(_seed_continuation(app_kind="kyber", cont_id="cont-k"))
    out = _unresolvable(continuation_id="cont-k")
    assert out["resolved"] is False and out["reason"] == "unresolvable"


def test_expired_continuation_unresolvable():
    _run(_install())
    _run(_seed_continuation(expires_at="2000-01-01T00:00:00+00:00", cont_id="cont-e"))
    out = _unresolvable(continuation_id="cont-e")
    assert out["resolved"] is False and out["reason"] == "unresolvable"


# ── step-up ──────────────────────────────────────────────────────────────────

def test_restricted_requires_step_up():
    _run(_install())
    cid = _run(_seed_continuation(sensitivity="restricted", cont_id="cont-r"))
    out = _run(
        mobile_service.resolve_deep_link(
            scope=SCOPE, principal_id=PRINCIPAL, installation_id="dev-1",
            continuation_id=cid, elevated=False,
        )
    )
    assert out["resolved"] is False
    assert out["requires_step_up"] is True


def test_restricted_resolves_when_elevated():
    _run(_install())
    cid = _run(_seed_continuation(sensitivity="restricted", cont_id="cont-r2"))
    out = _run(
        mobile_service.resolve_deep_link(
            scope=SCOPE, principal_id=PRINCIPAL, installation_id="dev-1",
            continuation_id=cid, elevated=True,
        )
    )
    assert out["resolved"] is True


def test_route_passes_step_up_permission():
    _run(_install())
    cid = _run(_seed_continuation(sensitivity="restricted", cont_id="cont-r3"))
    resp = _run(
        mobile_routes.resolve_deep_link(
            _req(_ElevatedTenant()),
            DeepLinkResolveRequest(installation_id="dev-1", continuation_id=cid),
        )
    )
    assert resp.data["resolved"] is True
