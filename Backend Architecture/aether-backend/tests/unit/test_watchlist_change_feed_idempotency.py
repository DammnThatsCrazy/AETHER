"""Watchlist mutations emit replay-safe tenant change-feed entries."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.client_sync_repo import get_client_sync_repository, reset_client_sync_memory
from services.client_sync import emitter as sync_emitter
from services.intelligence.comparison import routes as comparison_routes


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-a"

    def require_permission(self, _permission):
        return None


def _request():
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant()))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_client_sync_memory()
    monkeypatch.setattr(comparison_routes, "_require_enabled", lambda: None)
    monkeypatch.setattr(
        sync_emitter.settings,
        "client_sync",
        SimpleNamespace(enabled=True),
    )
    yield
    reset_client_sync_memory()


def test_replayed_identical_watchlist_upsert_is_one_feed_event():
    payload = comparison_routes.WatchlistUpsertRequest(
        watchlist_id="wl-1", name="Risk watches"
    )
    _run(comparison_routes.upsert_watchlist(_request(), payload))
    _run(comparison_routes.upsert_watchlist(_request(), payload))

    rows = _run(get_client_sync_repository().read_since("t:tenant-a", 0, 100))
    assert len(rows) == 1
    assert rows[0]["change_type"] == "watchlist_changed"
    assert rows[0]["resource_id"] == "wl-1"
    assert rows[0]["revision"]


def test_changed_watchlist_revision_and_tenant_scope_are_preserved():
    _run(comparison_routes.upsert_watchlist(
        _request(), comparison_routes.WatchlistUpsertRequest(watchlist_id="wl-1", name="A")
    ))
    _run(comparison_routes.upsert_watchlist(
        _request(), comparison_routes.WatchlistUpsertRequest(watchlist_id="wl-1", name="B")
    ))
    # The same natural watchlist id in another tenant must not share a feed
    # scope or source-event idempotency key.
    class _OtherTenant(_Tenant):
        tenant_id = "tenant-b"
        user_id = "user-b"

    other_request = SimpleNamespace(state=SimpleNamespace(tenant=_OtherTenant()))
    _run(comparison_routes.upsert_watchlist(
        other_request, comparison_routes.WatchlistUpsertRequest(watchlist_id="wl-1", name="A")
    ))

    a_rows = _run(get_client_sync_repository().read_since("t:tenant-a", 0, 100))
    b_rows = _run(get_client_sync_repository().read_since("t:tenant-b", 0, 100))
    assert len(a_rows) == 2
    assert len(b_rows) == 1
    assert a_rows[0]["revision"] != a_rows[1]["revision"]
