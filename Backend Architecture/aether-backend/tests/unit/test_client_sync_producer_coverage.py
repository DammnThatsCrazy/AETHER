"""Producer coverage for the client-sync feed (M5a).

Proves each of the nine change types is emitted from its owning mutation. For
tenant-plane producers we drive the REAL mutation (in-memory repositories) and
assert ``enqueue_sync_change`` was awaited with the right ``change_type`` and
resource identity. The operator-plane (Kyber) handlers require an access context
resolved by FastAPI DI, so those tests mock the service/correlator the route
calls and the ``_authorize_command`` gate — the emitter wiring is what is under
test, and it is asserted identically.

Mirrors the existing ``continuation_changed`` producer test
(tests/unit/test_continuation_sync_integration.py): the emitter is the single
producer entrypoint, best-effort and flag-gated; a feed append must never break
the mutation.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from repositories.repos import reset_in_memory_stores
from shared.exploration.models import (
    ExplorationContextV1,
    ExplorationScope,
    TemporalSelection,
)
from services.auth.sessions.service import SessionService
from services.intelligence.comparison import routes as comparison_routes
from services.kyber.ops import routes as ops_routes
from services.kyber.sessions import routes as kyber_sessions_routes
from services.me import routes as me_routes
from services.mobile import routes as mobile_routes
from services.mobile import service as mobile_service
from services.notification_intelligence.inbox import create_inbox_notification
from services.notification_intelligence.models import NotificationSeverity, UpdateConfigRequest
from services.notification_intelligence import routes as notif_routes
from services.noesis.conversations import NoesisConversationStore
from services.noesis.models import NoesisQueryRequest, NoesisResponse
from services.exploration import routes as exploration_routes


def _run(coro):
    return asyncio.run(coro)


class _Tenant:
    tenant_id = "tenant-a"
    user_id = "user-1"

    def require_permission(self, permission):  # noqa: ARG002
        return None

    def has_permission(self, permission):  # noqa: ARG002
        return False


def _req():
    return SimpleNamespace(
        state=SimpleNamespace(tenant=_Tenant()),
        cookies={},
        headers={},
    )


def _emit(monkeypatch, module) -> AsyncMock:
    emitter = AsyncMock()
    monkeypatch.setattr(module, "enqueue_sync_change", emitter)
    return emitter


@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── notification_changed ────────────────────────────────────────────────────

def test_inbox_mark_read_emits_notification_changed(monkeypatch):
    nid = _run(create_inbox_notification(
        "tenant-a", category="jobs", severity=NotificationSeverity.INFO,
        title="Job finished", body="ok",
    ))["id"]
    emit = _emit(monkeypatch, notif_routes)
    _run(notif_routes.inbox_mark_read(nid, _req()))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "notification_changed"
    assert kw["resource_kind"] == "notification_inbox"
    assert kw["resource_id"] == nid
    assert kw["scope_key"] == "t:tenant-a"
    # M8-B4: emitted under the ACTUAL user principal so the DSR client-sync
    # erasure (delete_by_principal on user_id) clears it.
    assert kw["principal_id"] == "user-1"


def test_inbox_archive_emits_notification_changed(monkeypatch):
    nid = _run(create_inbox_notification(
        "tenant-a", category="jobs", severity=NotificationSeverity.INFO,
        title="Job finished", body="ok",
    ))["id"]
    emit = _emit(monkeypatch, notif_routes)
    _run(notif_routes.inbox_archive(nid, _req()))
    emit.assert_awaited_once()
    assert emit.await_args.kwargs["change_type"] == "notification_changed"
    assert emit.await_args.kwargs["resource_id"] == nid


def test_inbox_read_all_emits_notification_changed(monkeypatch):
    _run(create_inbox_notification(
        "tenant-a", category="jobs", severity=NotificationSeverity.INFO,
        title="Job finished", body="ok",
    ))
    emit = _emit(monkeypatch, notif_routes)
    _run(notif_routes.inbox_read_all(_req()))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "notification_changed"
    assert kw["resource_kind"] == "notification_inbox"
    assert kw.get("resource_id") is None  # batch — no single resource


# ── saved_view_changed ──────────────────────────────────────────────────────

def _view_payload(view_id: str) -> SimpleNamespace:
    return exploration_routes.ViewUpsertRequest(
        view_id=view_id,
        name="My view",
        context=ExplorationContextV1(
            scope=ExplorationScope(tenant_id="tenant-a", surface="graph"),
            temporal=TemporalSelection(mode="as_of", field="observed_at", timezone="UTC"),
        ),
    )


def test_upsert_view_emits_saved_view_changed(monkeypatch):
    monkeypatch.setattr(exploration_routes, "_require_enabled", lambda: None)
    emit = _emit(monkeypatch, exploration_routes)
    _run(exploration_routes.upsert_view(_req(), _view_payload("view-1")))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "saved_view_changed"
    assert kw["resource_kind"] == "saved_view"
    assert kw["resource_id"] == "view-1"
    assert kw["scope_key"] == "t:tenant-a"


def test_delete_view_emits_saved_view_changed(monkeypatch):
    monkeypatch.setattr(exploration_routes, "_require_enabled", lambda: None)
    _run(exploration_routes.upsert_view(_req(), _view_payload("view-1")))
    emit = _emit(monkeypatch, exploration_routes)
    _run(exploration_routes.delete_view(_req(), view_id="view-1"))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "saved_view_changed"
    assert kw["resource_kind"] == "saved_view"
    assert kw["resource_id"] == "view-1"


# ── conversation_changed ────────────────────────────────────────────────────

def test_record_turn_emits_conversation_changed(monkeypatch):
    store = NoesisConversationStore()
    req = NoesisQueryRequest(message="hello", surface="aether", conversation_id="conv-1")
    resp = NoesisResponse(answer="hi", mode="deterministic", intent="greeting", confidence=0.9)
    emit = _emit(monkeypatch, __import__("services.noesis.conversations", fromlist=["enqueue_sync_change"]))
    cid = _run(store.record_turn(req, resp, "tenant-a", principal_id="user-1"))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "conversation_changed"
    assert kw["resource_kind"] == "conversation"
    assert kw["resource_id"] == cid
    assert kw["scope_key"] == "t:tenant-a"
    # M8-B4: the sync event is emitted under the ACTUAL user principal so the
    # DSR client-sync erasure (delete_by_principal on user_id) clears it — a
    # tenant-id principal would survive the user's erasure.
    assert kw["principal_id"] == "user-1"


def test_record_turn_falls_back_to_tenant_principal(monkeypatch):
    store = NoesisConversationStore()
    req = NoesisQueryRequest(message="hello", surface="aether", conversation_id="conv-2")
    resp = NoesisResponse(answer="hi", mode="deterministic", intent="greeting", confidence=0.9)
    emit = _emit(monkeypatch, __import__("services.noesis.conversations", fromlist=["enqueue_sync_change"]))
    cid = _run(store.record_turn(req, resp, "tenant-a"))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["resource_id"] == cid
    # No user principal known → tenant-id principal (backward compatible).
    assert kw["principal_id"] == "tenant-a"


# ── watchlist_changed ───────────────────────────────────────────────────────

def test_upsert_watchlist_emits_watchlist_changed(monkeypatch):
    monkeypatch.setattr(comparison_routes, "_require_enabled", lambda: None)
    emit = _emit(monkeypatch, comparison_routes)
    _run(comparison_routes.upsert_watchlist(
        _req(), comparison_routes.WatchlistUpsertRequest(watchlist_id="wl-1", name="WL")
    ))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "watchlist_changed"
    assert kw["resource_kind"] == "watchlist"
    assert kw["resource_id"] == "wl-1"


def test_delete_watchlist_emits_watchlist_changed(monkeypatch):
    monkeypatch.setattr(comparison_routes, "_require_enabled", lambda: None)
    _run(comparison_routes.upsert_watchlist(
        _req(), comparison_routes.WatchlistUpsertRequest(watchlist_id="wl-1", name="WL")
    ))
    emit = _emit(monkeypatch, comparison_routes)
    _run(comparison_routes.delete_watchlist(_req(), watchlist_id="wl-1"))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "watchlist_changed"
    assert kw["resource_id"] == "wl-1"


# ── preference_changed ──────────────────────────────────────────────────────

def test_update_tenant_config_emits_preference_changed(monkeypatch):
    emit = _emit(monkeypatch, notif_routes)
    _run(notif_routes.update_config(
        UpdateConfigRequest(rate_limit_per_minute=5), _req(), tenantId="tenant-a"
    ))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "preference_changed"
    assert kw["resource_kind"] == "notification_config"
    assert kw["resource_id"] == "tenant-a"
    assert kw["scope_key"] == "t:tenant-a"


# ── incident_changed (Kyber operator plane) ─────────────────────────────────

class _FakeIncidentCorrelator:
    async def update_incident(self, *args, **kwargs):  # noqa: ARG002
        return SimpleNamespace(model_dump=lambda: {"incident_id": "inc-1"})

    async def resolve_incident(self, *args, **kwargs):  # noqa: ARG002
        return SimpleNamespace(model_dump=lambda: {"incident_id": "inc-1"})

    def resume_card(self, incident):  # noqa: ARG002
        return {}


def _ops_ctx():
    return SimpleNamespace(operator_id="op-1")


def test_update_incident_emits_incident_changed(monkeypatch):
    monkeypatch.setattr(ops_routes, "incident_correlator", _FakeIncidentCorrelator())
    emit = _emit(monkeypatch, ops_routes)
    _run(ops_routes.update_incident(
        _req(), ops_routes.UpdateIncidentRequest(status="open"), incident_id="inc-1", context=_ops_ctx()
    ))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "incident_changed"
    assert kw["resource_kind"] == "incident"
    assert kw["resource_id"] == "inc-1"
    assert kw["scope_key"] == "o:op-1"
    assert kw["principal_id"] == "op-1"


def test_resolve_incident_emits_incident_changed(monkeypatch):
    monkeypatch.setattr(ops_routes, "incident_correlator", _FakeIncidentCorrelator())
    emit = _emit(monkeypatch, ops_routes)
    _run(ops_routes.resolve_incident(
        _req(), ops_routes.ResolveIncidentRequest(root_cause="rc"), incident_id="inc-1", context=_ops_ctx()
    ))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "incident_changed"
    assert kw["resource_id"] == "inc-1"


# ── command_receipt_changed (Kyber operator plane) ──────────────────────────

class _FakeExceptionService:
    async def acknowledge(self, *args, **kwargs):  # noqa: ARG002
        return SimpleNamespace(model_dump=lambda: {"exception_id": "exc-1"})

    async def resolve(self, *args, **kwargs):  # noqa: ARG002
        return SimpleNamespace(model_dump=lambda: {"exception_id": "exc-1"})

    async def suppress(self, *args, **kwargs):  # noqa: ARG002
        return SimpleNamespace(model_dump=lambda: {"exception_id": "exc-1"})


class _FakeCommandService:
    async def require(self, command_id):  # noqa: ARG002
        return SimpleNamespace(command_type="activate_kill_switch", tenant_ids=[], metadata={})

    async def approve(self, *args, **kwargs):  # noqa: ARG002
        return SimpleNamespace(model_dump=lambda: {}, metadata={})

    async def execute(self, *args, **kwargs):  # noqa: ARG002
        return {}

    async def verify(self, *args, **kwargs):  # noqa: ARG002
        return {}


@pytest.mark.parametrize("handler,service_method", [
    ("acknowledge_exception", "acknowledge"),
    ("resolve_exception", "resolve"),
    ("suppress_exception", "suppress"),
])
def test_exception_receipt_emits_command_receipt_changed(monkeypatch, handler, service_method):
    monkeypatch.setattr(ops_routes, "exception_service", _FakeExceptionService())
    emit = _emit(monkeypatch, ops_routes)
    if handler == "resolve_exception":
        coro = getattr(ops_routes, handler)(
            _req(), ops_routes.ResolveExceptionRequest(note="fixed"), exception_id="exc-1", context=_ops_ctx()
        )
    elif handler == "suppress_exception":
        coro = getattr(ops_routes, handler)(
            _req(), ops_routes.SuppressExceptionRequest(reason="fixed"), exception_id="exc-1", context=_ops_ctx()
        )
    else:
        coro = getattr(ops_routes, handler)(_req(), exception_id="exc-1", context=_ops_ctx())
    _run(coro)
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "command_receipt_changed"
    assert kw["resource_kind"] == "command_receipt"
    assert kw["resource_id"] == "exc-1"
    assert kw["scope_key"] == "o:op-1"


@pytest.mark.parametrize("handler,service_method", [
    ("approve_command", "approve"),
    ("execute_command", "execute"),
    ("verify_command", "verify"),
])
def test_command_transition_emits_command_receipt_changed(monkeypatch, handler, service_method):
    monkeypatch.setattr(ops_routes, "command_service", _FakeCommandService())
    monkeypatch.setattr(
        ops_routes, "_authorize_command",
        AsyncMock(return_value=(SimpleNamespace(operator_id="op-1"), SimpleNamespace())),
    )
    emit = _emit(monkeypatch, ops_routes)
    _run(getattr(ops_routes, handler)(_req(), command_id="cmd-1", context=_ops_ctx()))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "command_receipt_changed"
    assert kw["resource_kind"] == "command_receipt"
    assert kw["resource_id"] == "cmd-1"
    assert kw["scope_key"] == "o:op-1"


# ── session_revoked ─────────────────────────────────────────────────────────

def test_revoke_my_session_emits_session_revoked(monkeypatch):
    issued = _run(SessionService().create_session("tenant-a", "user-a"))
    emit = _emit(monkeypatch, me_routes)
    _run(me_routes.revoke_my_session(issued.session_id, _req()))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "session_revoked"
    assert kw["resource_id"] == issued.session_id
    assert kw["scope_key"] == "t:tenant-a"


def test_revoke_other_sessions_emits_session_revoked(monkeypatch):
    svc = SessionService()
    issued = _run(svc.create_session("tenant-a", "user-a"))
    _run(svc.create_session("tenant-a", "user-a"))
    req = _req()
    req.cookies = {"aether_session": issued.token}
    emit = _emit(monkeypatch, me_routes)
    _run(me_routes.revoke_my_other_sessions(req))
    emit.assert_awaited_once()
    assert emit.await_args.kwargs["change_type"] == "session_revoked"
    assert emit.await_args.kwargs["scope_key"] == "t:tenant-a"


class _FakeKyberSession:
    operator_id = "op-1"


def test_kyber_revoke_session_emits_session_revoked(monkeypatch):
    monkeypatch.setattr(kyber_sessions_routes.session_service, "get", AsyncMock(return_value=_FakeKyberSession()))
    monkeypatch.setattr(kyber_sessions_routes.session_service, "revoke", AsyncMock(return_value=None))
    monkeypatch.setattr(kyber_sessions_routes.step_up_service, "revoke_for_session", AsyncMock(return_value=None))
    emit = _emit(monkeypatch, kyber_sessions_routes)
    ctx = SimpleNamespace(operator_id="op-1", has_capability=lambda _c: False)
    _run(kyber_sessions_routes.revoke_session(_req(), session_id="sess-1", context=ctx))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "session_revoked"
    assert kw["resource_id"] == "sess-1"
    assert kw["scope_key"] == "o:op-1"
    assert kw["principal_id"] == "op-1"


# ── installation_revoked ────────────────────────────────────────────────────

def test_revoke_installation_emits_installation_revoked(monkeypatch):
    monkeypatch.setattr(mobile_routes, "_require_enabled", lambda: None)
    registered = _run(mobile_service.register(
        scope="t:tenant-a",
        principal_id="user-1",
        installation_id="inst-1",
        platform="ios",
        bundle_id="com.aether.app",
        environment="production",
        device_name="iPhone 15",
        push_token=None,
        push_provider=None,
    ))
    iid = registered["installation"]["id"]
    emit = _emit(monkeypatch, mobile_routes)
    _run(mobile_routes.revoke_installation(_req(), installation_id=iid))
    emit.assert_awaited_once()
    kw = emit.await_args.kwargs
    assert kw["change_type"] == "installation_revoked"
    assert kw["resource_kind"] == "installation"
    assert kw["resource_id"] == iid
    assert kw["scope_key"] == "t:tenant-a"
    assert kw["principal_id"] == "user-1"
