"""Client-sync route handler over the in-memory feed."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.client_sync_repo import get_client_sync_repository, reset_client_sync_memory
from shared.common.common import NotFoundError
from services.client_sync import routes as sync_routes


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
