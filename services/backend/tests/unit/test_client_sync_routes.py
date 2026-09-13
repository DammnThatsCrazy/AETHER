"""Client-sync route handler over the in-memory feed."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.client_sync_repo import get_client_sync_repository, reset_client_sync_memory
from shared.common.common import NotFoundError
from services.client_sync import routes as sync_routes
from services.client_sync import operator_routes as sync_operator_routes
from services.kyber.access.contracts import WorkforcePrincipal, WorkforceSession
from services.kyber.access.dependencies import KyberAccessContext


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"

    def require_permission(self, permission):
        return None


def _req():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    # ClientSyncConfig is a frozen dataclass — replace the whole config object.
    reset_client_sync_memory()
    monkeypatch.setattr(sync_routes.settings, "client_sync", SimpleNamespace(enabled=True))
    yield
    reset_client_sync_memory()


def test_disabled_is_404(monkeypatch):
    monkeypatch.setattr(sync_routes.settings, "client_sync", SimpleNamespace(enabled=False))
    with pytest.raises(NotFoundError):
        _run(sync_routes.client_sync(_req(), cursor=None, limit=200))


def test_returns_events_scoped_to_tenant():
    repo = get_client_sync_repository()
    _run(repo.enqueue(scope_key="t:tenant-a", principal_id="user-1",
                      change_type="continuation_changed", resource_id="c1"))
    _run(repo.enqueue(scope_key="t:tenant-b", principal_id="x",
                      change_type="continuation_changed", resource_id="other"))
    resp = _run(sync_routes.client_sync(_req(), cursor=None, limit=200)).data
    assert [e["resource_id"] for e in resp["events"]] == ["c1"]
    assert resp["reset"] is False


def test_cursor_resume_has_no_repeats():
    repo = get_client_sync_repository()
    _run(repo.enqueue(scope_key="t:tenant-a", principal_id="user-1",
                      change_type="continuation_changed", resource_id="c1"))
    first = _run(sync_routes.client_sync(_req(), cursor=None, limit=200)).data
    second = _run(sync_routes.client_sync(_req(), cursor=first["cursor"], limit=200)).data
    assert second["events"] == []


# ── Operator (Kyber) feed — /v1/kyber/client-sync ────────────────────────────


def _op_ctx(operator_id: str = "op-1") -> KyberAccessContext:
    """The real ``KyberAccessContext`` a workforce session would authorize."""
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
    return KyberAccessContext(session=session, principal=principal, environment=session.environment)


def test_operator_feed_scoped_to_authenticated_operator():
    repo = get_client_sync_repository()
    _run(repo.enqueue(scope_key="o:op-1", principal_id="op-1",
                      change_type="command_receipt_changed", resource_id="exc-1"))
    # op-2's events must never surface for op-1's cursor.
    _run(repo.enqueue(scope_key="o:op-2", principal_id="op-2",
                      change_type="command_receipt_changed", resource_id="exc-other"))
    resp = _run(sync_operator_routes.operator_client_sync(
        cursor=None, limit=200, context=_op_ctx("op-1")
    )).data
    assert [e["resource_id"] for e in resp["events"]] == ["exc-1"]
    assert resp["reset"] is False


def test_operator_feed_resume_has_no_repeats():
    repo = get_client_sync_repository()
    _run(repo.enqueue(scope_key="o:op-1", principal_id="op-1",
                      change_type="continuation_changed", resource_id="c1"))
    first = _run(sync_operator_routes.operator_client_sync(
        cursor=None, limit=200, context=_op_ctx("op-1")
    )).data
    second = _run(sync_operator_routes.operator_client_sync(
        cursor=first["cursor"], limit=200, context=_op_ctx("op-1")
    )).data
    assert second["events"] == []


def test_operator_feed_disabled_is_404(monkeypatch):
    monkeypatch.setattr(sync_operator_routes.settings, "client_sync", SimpleNamespace(enabled=False))
    with pytest.raises(NotFoundError):
        _run(sync_operator_routes.operator_client_sync(
            cursor=None, limit=200, context=_op_ctx("op-1")
        ))
