"""Kyber mobile action-adapter tests — /v1/kyber/mobile/actions (M6a).

Exercises the READ-ONLY action-availability digest: router registration, the
tier mapping from the owning exception queue + open command list, step-up
freshness propagation, the bounded/redacted snake_case availability records, and
operator identity from the resolved ``KyberAccessContext`` (never the request).
The HTTP-surface test mounts the router and proves the Kyber workforce guard
denies an unauthenticated request at the edge.

Fakes are injected by monkeypatching the owning-service singletons (the
established test seam): ``exception_service.queue``,
``command_service.list_commands`` and ``step_up_service.require_fresh`` /
``active_grant``. No DB is touched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from shared.common.common import AetherError
from services.kyber.access.contracts import StepUpGrant, WorkforcePrincipal, WorkforceSession
from services.kyber.access.dependencies import KyberAccessContext
from services.kyber.ops import mobile_actions
from services.kyber.ops.contracts import OperationalException
from services.kyber.ops.commands import command_service
from services.kyber.ops.exceptions import exception_service
from services.kyber.sessions.step_up import step_up_service

_ITEM_KEYS = frozenset(
    {
        "kind", "id", "title", "severity", "status", "action_class",
        "available_action", "capability_id", "requires_step_up",
        "priority_score", "signal_count", "last_seen_at",
    }
)


def _run(coro):
    return asyncio.run(coro)


def _ctx(operator_id: str = "op-1") -> KyberAccessContext:
    """The real ``KyberAccessContext`` a workforce session would authorize.

    Mirrors ``tests/kyber/conftest.py.build_scoped_context`` and
    ``tests/unit/test_kyber_continuations.py._ctx``: a live, device-bound session
    plus an active principal — the shape ``require_kyber_access`` hands a handler
    after a successful evaluation.
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


# ── Fake owning-service data ─────────────────────────────────────────────────

def _exc(
    exception_id: str,
    *,
    severity: str = "high",
    bucket: str = "watch",
    status: str = "open",
    priority: float = 0.5,
    signal: int = 1,
) -> dict:
    return OperationalException(
        exception_id=exception_id,
        title=f"exception {exception_id}",
        severity=severity,
        bucket=bucket,
        status=status,
        priority_score=priority,
        signal_count=signal,
        last_seen_at="2026-08-07T00:00:00+00:00",
    ).model_dump()


def _cmd(
    command_id: str,
    *,
    command_type: str,
    status: str,
    action_class: int,
    blast_radius: dict | None = None,
) -> dict:
    return {
        "command_id": command_id,
        "command_type": command_type,
        "status": status,
        "action_class": action_class,
        "requested_by": "op-1",
        "reason": "fix it",
        "idempotency_key": f"ik_{command_id}",
        "created_at": "2026-08-07T00:00:00+00:00",
        "updated_at": "2026-08-07T00:00:00+00:00",
        "blast_radius": blast_radius,
    }


def _queue(buckets: dict | None = None) -> dict:
    buckets = buckets or {}
    return {
        "order": [b for b in ("critical_now", "needs_action", "watch", "informational") if b in buckets],
        "buckets": buckets,
        "counts": {name: len(items) for name, items in buckets.items()},
        "total": sum(len(items) for items in buckets.values()),
        "status_filter": "open",
        "generated_at": "2026-08-07T00:00:00+00:00",
    }


def _seed(
    monkeypatch,
    *,
    buckets: dict | None = None,
    commands: list[dict] | None = None,
    fresh: bool = False,
    grant: StepUpGrant | None = None,
) -> None:
    """Inject fakes for the owning services the digest composes."""
    monkeypatch.setattr(exception_service, "queue", AsyncMock(return_value=_queue(buckets)))
    monkeypatch.setattr(command_service, "list_commands", AsyncMock(return_value=commands or []))
    monkeypatch.setattr(
        step_up_service,
        "require_fresh",
        AsyncMock(return_value=(fresh, None if fresh else "step_up_required")),
    )
    monkeypatch.setattr(step_up_service, "active_grant", AsyncMock(return_value=grant))


def _all_items(data: dict) -> list[dict]:
    return [item for items in data["tiers"].values() for item in items]


# ── Registration + auth surface ──────────────────────────────────────────────

def test_mobile_actions_router_registers_expected_route():
    paths = {(r.path, tuple(sorted(r.methods))) for r in mobile_actions.mobile_actions_router.routes}
    assert ("/v1/kyber/mobile/actions", ("GET",)) in paths


def _client() -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(mobile_actions.mobile_actions_router)
    return TestClient(app, raise_server_exceptions=False)


def test_mobile_actions_deny_unauthenticated_requests():
    """No Kyber workforce session -> the kyber guard denies at the edge."""
    client = _client()
    resp = client.get("/v1/kyber/mobile/actions")
    assert resp.status_code in (401, 403), f"GET -> {resp.status_code}"


# ── Digest composition (direct handler calls, fakes injected) ────────────────

def test_tier_mapping_from_exception_buckets(monkeypatch):
    _seed(
        monkeypatch,
        buckets={
            "critical_now": [_exc("kex_c", severity="critical", bucket="critical_now", priority=0.9)],
            "needs_action": [_exc("kex_n", severity="high", bucket="needs_action", priority=0.6)],
            "watch": [_exc("kex_w", severity="medium", bucket="watch", priority=0.3)],
            "informational": [_exc("kex_i", severity="info", bucket="informational", priority=0.1)],
        },
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    assert [i["id"] for i in data["tiers"]["tier0"]] == ["kex_c"]
    assert [i["id"] for i in data["tiers"]["tier1"]] == ["kex_n"]
    assert [i["id"] for i in data["tiers"]["tier2"]] == ["kex_w"]
    assert [i["id"] for i in data["tiers"]["tier3"]] == ["kex_i"]
    assert all(item["kind"] == "exception" for item in _all_items(data))
    assert data["counts"] == {"tier0": 1, "tier1": 1, "tier2": 1, "tier3": 1}


def test_command_tiering(monkeypatch):
    _seed(
        monkeypatch,
        commands=[
            _cmd("kcm_hi", command_type="pause_connector", status="approved", action_class=4),
            _cmd("kcm_lo", command_type="retry_job", status="requested", action_class=2),
            _cmd("kcm_dry", command_type="replay_event_range", status="dry_run_complete", action_class=3),
            _cmd("kcm_unver", command_type="retry_job", status="executed_unverified", action_class=2),
        ],
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    # action_class >= 4 open command -> tier0; other open commands -> tier1.
    assert [i["id"] for i in data["tiers"]["tier0"]] == ["kcm_hi"]
    assert [i["id"] for i in data["tiers"]["tier1"]] == ["kcm_lo", "kcm_dry"]
    # executed_unverified is open but not surfaced by the digest tier rules.
    assert "kcm_unver" not in [i["id"] for i in _all_items(data)]


def test_requires_step_up_for_high_impact_when_not_fresh(monkeypatch):
    _seed(
        monkeypatch,
        buckets={"critical_now": [_exc("kex_c", severity="critical", bucket="critical_now")]},
        commands=[_cmd("kcm_hi", command_type="pause_connector", status="approved", action_class=4)],
        fresh=False,
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    assert data["step_up_required"] is True
    assert data["step_up"]["fresh"] is False
    by_id = {i["id"]: i for i in _all_items(data)}
    assert by_id["kcm_hi"]["requires_step_up"] is True
    # Exceptions authorise annotate/close work (class 1) — never step-up.
    assert by_id["kex_c"]["requires_step_up"] is False
    assert by_id["kex_c"]["action_class"] == 1


def test_requires_step_up_false_when_fresh_and_grant_reported(monkeypatch):
    grant = StepUpGrant(
        session_id="sess-1", operator_id="op-1", expires_at="2026-08-07T00:30:00+00:00"
    )
    _seed(
        monkeypatch,
        commands=[_cmd("kcm_hi", command_type="pause_connector", status="approved", action_class=4)],
        fresh=True,
        grant=grant,
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    assert data["step_up_required"] is False
    assert data["step_up"] == {
        "fresh": True,
        "grant_id": grant.grant_id,
        "expires_at": grant.expires_at,
    }
    by_id = {i["id"]: i for i in _all_items(data)}
    assert by_id["kcm_hi"]["requires_step_up"] is False


def test_step_up_fresh_but_no_active_grant_is_graceful(monkeypatch):
    """Fresh require_fresh with an absent grant -> grant_id None, not an error."""
    _seed(monkeypatch, fresh=True, grant=None)
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    assert data["step_up"] == {"fresh": True, "grant_id": None, "expires_at": None}
    assert data["step_up_required"] is False


def test_available_action_and_capability_labels_present(monkeypatch):
    _seed(
        monkeypatch,
        buckets={
            "critical_now": [_exc("kex_c", severity="critical", bucket="critical_now", status="open")],
            "needs_action": [_exc("kex_n", severity="high", bucket="needs_action", status="acknowledged")],
            "watch": [_exc("kex_w", severity="medium", bucket="watch", status="in_progress")],
            "informational": [_exc("kex_i", severity="info", bucket="informational", status="resolved")],
        },
        commands=[
            _cmd("kcm_hi", command_type="pause_connector", status="awaiting_approval", action_class=4),
            _cmd("kcm_lo", command_type="retry_job", status="approved", action_class=2),
        ],
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    by_id = {i["id"]: i for i in _all_items(data)}
    assert by_id["kex_c"]["available_action"] == "acknowledge"
    assert by_id["kex_c"]["capability_id"] == "kyber.incident.manage"
    assert by_id["kex_n"]["available_action"] == "resolve"
    assert by_id["kex_i"]["available_action"] == "suppress"
    assert by_id["kex_i"]["capability_id"] == "kyber.incident.close"
    # Registered command_type -> registry capability; labels present on commands.
    assert by_id["kcm_hi"]["available_action"] == "approve"
    assert by_id["kcm_hi"]["capability_id"] == "kyber.command.pause"
    assert by_id["kcm_lo"]["available_action"] == "execute"
    assert by_id["kcm_lo"]["capability_id"] == "kyber.command.retry"


def test_snake_case_output_keys(monkeypatch):
    _seed(
        monkeypatch,
        buckets={"critical_now": [_exc("kex_c", severity="critical", bucket="critical_now")]},
        commands=[_cmd("kcm_hi", command_type="pause_connector", status="approved", action_class=4)],
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    assert set(data["tiers"]) == {"tier0", "tier1", "tier2", "tier3"}
    assert set(data["counts"]) == {"tier0", "tier1", "tier2", "tier3"}
    for item in _all_items(data):
        assert set(item) == _ITEM_KEYS, f"unexpected keys on {item.get('kind')}: {set(item)}"
        assert "exception_id" not in item
        assert "command_id" not in item
        assert "priorityScore" not in item
    assert "generated_at" in data
    assert set(data["step_up"]) == {"fresh", "grant_id", "expires_at"}


def test_operator_identity_comes_from_context(monkeypatch):
    """The digest binds step-up to the context's session — never a request body."""
    fake_fresh = AsyncMock(return_value=(True, None))
    fake_grant = AsyncMock(return_value=None)
    monkeypatch.setattr(step_up_service, "require_fresh", fake_fresh)
    monkeypatch.setattr(step_up_service, "active_grant", fake_grant)
    monkeypatch.setattr(exception_service, "queue", AsyncMock(return_value=_queue()))
    monkeypatch.setattr(command_service, "list_commands", AsyncMock(return_value=[]))

    ctx = _ctx("op-9")
    data = _run(mobile_actions.action_availability(context=ctx))["data"]
    fake_fresh.assert_awaited_once_with(ctx.session.session_id)
    fake_grant.assert_awaited_once_with(ctx.session.session_id)
    assert data["step_up"]["fresh"] is True


def test_generated_at_present_and_iso(monkeypatch):
    _seed(
        monkeypatch,
        buckets={"critical_now": [_exc("kex_c", severity="critical", bucket="critical_now")]},
    )
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    generated = data["generated_at"]
    assert generated
    parsed = datetime.fromisoformat(generated)
    assert parsed.tzinfo is not None


def test_empty_queue_all_empty_with_step_up_present(monkeypatch):
    _seed(monkeypatch, fresh=False)
    data = _run(mobile_actions.action_availability(context=_ctx()))["data"]
    assert data["tiers"] == {"tier0": [], "tier1": [], "tier2": [], "tier3": []}
    assert data["counts"] == {"tier0": 0, "tier1": 0, "tier2": 0, "tier3": 0}
    assert data["step_up_required"] is True
    assert data["step_up"] == {"fresh": False, "grant_id": None, "expires_at": None}
    assert data["generated_at"]
