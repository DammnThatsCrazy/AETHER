"""Producer → feed integration: a continuation mutation appears on client-sync.

Exercises the real wiring (continuation route → enqueue_sync_change → client-sync
repo → feed read) with both flags enabled, in local/in-memory mode.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from repositories.client_sync_repo import reset_client_sync_memory
from repositories.continuation_repo import reset_continuation_memory
from services.client_sync import emitter as sync_emitter
from services.client_sync import routes as sync_routes
from services.continuation import routes as cont_routes
from services.continuation.routes import ContinuationInput


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
def _both_enabled(monkeypatch):
    reset_continuation_memory()
    reset_client_sync_memory()
    monkeypatch.setattr(cont_routes, "_require_enabled", lambda: None)
    monkeypatch.setattr(sync_emitter.settings, "client_sync", SimpleNamespace(enabled=True))
    monkeypatch.setattr(sync_routes.settings, "client_sync", SimpleNamespace(enabled=True))
    yield
    reset_continuation_memory()
    reset_client_sync_memory()


def test_create_emits_continuation_changed_to_feed():
    created = _run(cont_routes.create_continuation(
        _req(), ContinuationInput(id="c1", source_client="desktop", surface="graph",
                                  summary={"title": "Resume"}), idempotency_key=None
    )).data
    feed = _run(sync_routes.client_sync(_req(), cursor=None, limit=200)).data
    assert len(feed["events"]) == 1
    ev = feed["events"][0]
    assert ev["change_type"] == "continuation_changed"
    assert ev["resource_kind"] == "continuation"
    assert ev["resource_id"] == created["id"]


def test_update_emits_second_event():
    from services.continuation.routes import ContinuationUpdate
    _run(cont_routes.create_continuation(
        _req(), ContinuationInput(id="c1", source_client="desktop", surface="graph",
                                  summary={"title": "Resume"}), idempotency_key=None))
    _run(cont_routes.update_continuation(
        _req(), ContinuationUpdate(source_client="mobile_ios", surface="graph",
                                   summary={"title": "On phone"}, expected_state_revision=0),
        continuation_id="c1"))
    feed = _run(sync_routes.client_sync(_req(), cursor=None, limit=200)).data
    assert len(feed["events"]) == 2
    assert feed["events"][-1]["revision"] == "1"
