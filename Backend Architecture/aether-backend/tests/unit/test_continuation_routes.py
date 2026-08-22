"""Continuation route handlers over the in-memory repository.

Drives the real handler → service → repository path (local mode) with a stub
tenant context, bypassing only the feature-flag gate. Verifies wiring, scope
binding, server-forced identity, 404s, and the 409 on a stale revision.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.continuation_repo import reset_continuation_memory
from shared.common.common import ConflictError, NotFoundError
from services.continuation import routes as cont_routes
from services.continuation.routes import (
    ContinuationInput,
    ContinuationUpdate,
    HandoffRequest,
    router,
)


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"

    def require_permission(self, permission):  # ADMIN-equivalent: always allowed
        return None


def _req(tenant=None):
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant or _Tenant()))


def _input(**over):
    base = dict(source_client="desktop", surface="graph",
               summary={"title": "Resume graph"})
    base.update(over)
    return ContinuationInput(**base)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    reset_continuation_memory()
    monkeypatch.setattr(cont_routes, "_require_enabled", lambda: None)
    yield
    reset_continuation_memory()


def test_router_registers_expected_routes():
    paths = {(r.path, tuple(sorted(r.methods))) for r in router.routes}
    assert ("/v1/continuations", ("POST",)) in paths
    assert ("/v1/continuations/recent", ("GET",)) in paths
    assert ("/v1/continuations/{continuation_id}", ("GET",)) in paths
    assert ("/v1/continuations/{continuation_id}", ("PATCH",)) in paths
    assert ("/v1/continuations/{continuation_id}/handoff", ("POST",)) in paths
    assert ("/v1/continuations/{continuation_id}", ("DELETE",)) in paths


def test_create_mints_id_and_forces_identity():
    resp = _run(cont_routes.create_continuation(_req(), _input(), idempotency_key=None))
    data = resp.data
    assert data["id"].startswith("cont_")
    assert data["principal_id"] == "user-1"
    assert data["tenant_id"] == "tenant-a"
    assert data["app_kind"] == "aether"
    assert data["state_revision"] == 0


def test_create_is_idempotent():
    a = _run(cont_routes.create_continuation(_req(), _input(), idempotency_key="k1")).data
    b = _run(cont_routes.create_continuation(_req(), _input(), idempotency_key="k1")).data
    assert b["id"] == a["id"]
    assert b["replayed"] is True


def test_get_and_recent_scoped():
    created = _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None)).data
    got = _run(cont_routes.get_continuation(_req(), continuation_id="c1")).data
    assert got["id"] == created["id"]
    recent = _run(cont_routes.recent_continuations(_req(), limit=25)).data
    assert any(c["id"] == "c1" for c in recent["continuations"])


def test_get_absent_is_404():
    with pytest.raises(NotFoundError):
        _run(cont_routes.get_continuation(_req(), continuation_id="nope"))


def test_patch_bumps_revision_and_409_on_stale():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    upd = ContinuationUpdate(source_client="mobile_ios", surface="graph",
                             summary={"title": "On phone"}, expected_state_revision=0)
    out = _run(cont_routes.update_continuation(_req(), upd, continuation_id="c1")).data
    assert out["state_revision"] == 1
    stale = ContinuationUpdate(source_client="mobile_ios", surface="graph",
                               summary={"title": "again"}, expected_state_revision=0)
    with pytest.raises(ConflictError):
        _run(cont_routes.update_continuation(_req(), stale, continuation_id="c1"))


def test_handoff_mints_selection_token():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    req = HandoffRequest(mode="explicit", resource_ids=["a", "b"])
    sel = _run(cont_routes.handoff_continuation(_req(), req, continuation_id="c1")).data
    assert sel["token"].startswith("sel_")
    assert sel["mode"] == "explicit"
    assert sel["continuation_id"] == "c1"


def test_handoff_absent_is_404():
    req = HandoffRequest(mode="query", saved_view_id="sv1")
    with pytest.raises(NotFoundError):
        _run(cont_routes.handoff_continuation(_req(), req, continuation_id="nope"))


def test_delete():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    out = _run(cont_routes.delete_continuation(_req(), continuation_id="c1")).data
    assert out["deleted"] is True
    with pytest.raises(NotFoundError):
        _run(cont_routes.delete_continuation(_req(), continuation_id="c1"))


# ── Intra-tenant ownership isolation (A2 IDOR remediation) ────────────────────
#
# A second tenant user must never read / update / handoff / delete another
# principal's continuation. Absent and foreign rows read identically as 404 —
# no existence leak, no 403 (which would reveal the row exists).

class _OtherTenant(_Tenant):
    user_id = "user-2"


def _other_req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_OtherTenant()))


def test_foreign_principal_get_is_404():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    with pytest.raises(NotFoundError):
        _run(cont_routes.get_continuation(_other_req(), continuation_id="c1"))
    # The owner can still read it — the row was never touched by the probe.
    got = _run(cont_routes.get_continuation(_req(), continuation_id="c1")).data
    assert got["id"] == "c1"


def test_foreign_principal_patch_is_404():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    upd = ContinuationUpdate(source_client="mobile_ios", surface="graph",
                             summary={"title": "hijack"}, expected_state_revision=0)
    with pytest.raises(NotFoundError):
        _run(cont_routes.update_continuation(_other_req(), upd, continuation_id="c1"))
    # Server-forced identity: the stored principal is still user-1 and revision
    # is untouched — the foreign CAS could not have advanced or overwritten it.
    got = _run(cont_routes.get_continuation(_req(), continuation_id="c1")).data
    assert got["principal_id"] == "user-1"
    assert got["state_revision"] == 0
    assert got["summary"]["title"] == "Resume graph"


def test_foreign_principal_handoff_is_404():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    req = HandoffRequest(mode="explicit", resource_ids=["a"])
    with pytest.raises(NotFoundError):
        _run(cont_routes.handoff_continuation(_other_req(), req, continuation_id="c1"))


def test_foreign_principal_delete_is_404():
    _run(cont_routes.create_continuation(_req(), _input(id="c1"), idempotency_key=None))
    with pytest.raises(NotFoundError):
        _run(cont_routes.delete_continuation(_other_req(), continuation_id="c1"))
    # Owner's row survives the foreign delete attempt.
    got = _run(cont_routes.get_continuation(_req(), continuation_id="c1")).data
    assert got["id"] == "c1"
