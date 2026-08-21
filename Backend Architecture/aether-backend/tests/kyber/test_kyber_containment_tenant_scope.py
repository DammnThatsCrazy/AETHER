"""Containment tenant-scope isolation — /v1/kyber/ops/containment.

The activate/deactivate containment routes take a body whose ``scope``/``target``
names the reach of the switch, but until this fix never asserted that reach
against the caller's durable tenant access scope. An operator holding
``kyber.command.pause`` scoped to tenant A could pause tenant B's ingestion
(``scope=tenant``, ``target=tenant_B``), or flip a fleet-wide ``global`` switch
that the class-5 ``kyber.command.kill_switch`` capability otherwise gates.

These tests drive the real HTTP surface: a live workforce session with an active
tenant access scope for ``tenant_A``, the pause capability, and (unless a test
adds it) no ``kill_switch``. They prove the cross-tenant request is refused with
``scope_tenant_mismatch``, every fleet scope is refused without ``kill_switch``,
the in-scope request still succeeds, and holding ``kill_switch`` is what unblocks
a fleet switch — for both activate and deactivate.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from shared.common.common import AetherError, utc_now

from services.kyber.access import dependencies as access_dependencies
from services.kyber.access.contracts import (
    AccessScope,
    StepUpGrant,
    WorkforcePrincipal,
    WorkforceSession,
)
from services.kyber.access.disclosure import DisclosureLevel
from services.kyber.access.scopes import access_scope_service
from services.kyber.ops.routes import router as ops_router
from services.kyber.sessions.cookies import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from services.kyber.sessions.service import hash_token, session_service
from services.kyber.sessions.step_up import step_up_service

OPERATOR = "op_containment"
DEVICE = "dev_containment"
TENANT_A = "tenant_A"
TENANT_B = "tenant_B"
RAW_TOKEN = "kses_containment_scope_test"
CSRF_TOKEN = "csrf_containment_scope_test"
SELF = "kyber.workforce.self.read"
PAUSE = "kyber.command.pause"
KILL_SWITCH = "kyber.command.kill_switch"
CONTROL = "pause_tenant_ingestion"
_REASON = "containment tenant-scope test under review"

#: Scopes that reach beyond one tenant; each must be gated by ``kill_switch``.
FLEET_SCOPES = ["global", "environment", "region", "model", "worker", "feature"]

_PAUSE_HOLDER = frozenset({SELF, PAUSE})
_KILL_SWITCH_HOLDER = frozenset({SELF, PAUSE, KILL_SWITCH})

ACTIVATE = "/v1/kyber/ops/containment/activate"
DEACTIVATE = "/v1/kyber/ops/containment/deactivate"


def _future_iso(hours: int = 1) -> str:
    return (utc_now() + timedelta(hours=hours)).isoformat()


# ── Fake provider plane ───────────────────────────────────────────────────────


class _FakePrincipals:
    """A principal who holds exactly the supplied capabilities."""

    def __init__(self, capabilities) -> None:
        self._capabilities = tuple(capabilities)

    async def get_by_operator_id(self, operator_id):
        return WorkforcePrincipal(
            operator_id=operator_id,
            email="operator@olympus.test",
            employment_status="active",
            kyber_enabled=True,
        )

    async def role_template_ids(self, operator_id, environment):
        # cto_engineering_command: max_action_class 4 (high impact), D4 ceiling,
        # no environment restriction.
        return ["cto_engineering_command"]

    async def effective_capabilities(self, operator_id, environment):
        return list(self._capabilities)

    async def active_capability_grants(self, operator_id, environment):
        return []


class _FakeDevices:
    async def get_device(self, device_id):
        return SimpleNamespace(device_id=device_id)

    async def resolve_by_grant(self, grant_token):
        return None

    async def is_usable(self, device_id):
        return True, None

    async def touch(self, device_id):
        return None


class _FakeDirectory:
    async def directory_freshness(self, operator_id):
        return True, None


class _FakeProof:
    """Not exercised on this path; present so the provider set reads complete."""


async def _seed_operator(
    *, capabilities, scope_tenant: str = TENANT_A
) -> WorkforceSession:
    """A live session with a durable scope and fresh step-up for one tenant."""
    session = WorkforceSession(
        session_id="kses_containment_scope_test",
        token_hash=hash_token(RAW_TOKEN),
        operator_id=OPERATOR,
        device_id=DEVICE,
        status="active",
        authentication_strength="device_bound",
        environment="local",
        presence_expires_at=_future_iso(24),
        authority_expires_at=_future_iso(8),
        idle_expires_at=_future_iso(1),
    )
    await session_service._repo.insert(session.session_id, session.model_dump())

    # A general (capability-unscoped) elevation satisfies the pause capability's
    # fresh-step-up requirement, exactly as a live WebAuthn assertion would.
    grant = StepUpGrant(
        session_id=session.session_id,
        operator_id=OPERATOR,
        device_id=DEVICE,
        capability_id=None,
        reason="test step-up",
        created_at=utc_now().isoformat(),
        expires_at=_future_iso(1),
    )
    await step_up_service._repo.insert(grant.grant_id, grant.model_dump())

    # Disclosure must reach D4 so the route's requested disclosure is satisfied;
    # the conftest default (D3) would trip ``disclosure_exceeded`` instead of the
    # scope assertion under test.
    scope = AccessScope(
        operator_id=OPERATOR,
        session_id=session.session_id,
        device_id=DEVICE,
        environment="local",
        tenant_id=scope_tenant,
        purpose="incident_response",
        reason="containment tenant-scope test",
        disclosure_level=int(DisclosureLevel.D4_EVENT_EVIDENCE),
        status="active",
        entered_at=utc_now().isoformat(),
        expires_at=_future_iso(1),
    )
    await access_scope_service._repo.insert(scope.scope_id, scope.model_dump())

    access_dependencies.set_providers(
        access_dependencies.AccessProviders(
            principals=_FakePrincipals(capabilities),
            devices=_FakeDevices(),
            directory=_FakeDirectory(),
            proof=_FakeProof(),
        )
    )
    return session


# ── HTTP surface ──────────────────────────────────────────────────────────────


def _client() -> TestClient:
    app = FastAPI()

    @app.exception_handler(AetherError)
    async def _handle(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    app.include_router(ops_router)
    return TestClient(app, raise_server_exceptions=False)


def _post(
    client: TestClient,
    path: str,
    *,
    scope: str,
    target: Optional[str],
    tenant_header: str = TENANT_A,
):
    headers = {
        "Origin": "http://localhost:3000",
        "Sec-Fetch-Site": "same-origin",
        "X-Kyber-CSRF": CSRF_TOKEN,
    }
    if tenant_header is not None:
        headers["X-Kyber-Tenant"] = tenant_header
    return client.post(
        path,
        json={
            "scope": scope,
            "target": target,
            "control": CONTROL,
            "reason": _REASON,
        },
        headers=headers,
        cookies={SESSION_COOKIE_NAME: RAW_TOKEN, CSRF_COOKIE_NAME: CSRF_TOKEN},
    )


def _denial_reason(resp) -> str:
    """The ``denial_reason`` the error body carried, or empty."""
    for error in resp.json().get("errors") or []:
        reason = error.get("denial_reason")
        if reason:
            return reason
    return ""


# ── The defect: cross-tenant and fleet bypass ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [ACTIVATE, DEACTIVATE])
async def test_cross_tenant_switch_is_refused_with_scope_tenant_mismatch(path: str) -> None:
    """(a) A pause holder scoped to tenant_A cannot name tenant_B's ingestion.

    The body names ``tenant_B`` while the durable scope grants ``tenant_A``; the
    route must refuse with ``scope_tenant_mismatch`` rather than pause tenant_B.
    """
    await _seed_operator(capabilities=_PAUSE_HOLDER)
    resp = _post(
        _client(), path, scope="tenant", target=TENANT_B, tenant_header=TENANT_A
    )
    assert resp.status_code == 403, resp.text
    assert _denial_reason(resp) == "scope_tenant_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [ACTIVATE, DEACTIVATE])
@pytest.mark.parametrize("scope", FLEET_SCOPES)
async def test_fleet_scope_is_refused_without_kill_switch(
    path: str, scope: str
) -> None:
    """(b) A pause holder cannot flip a fleet-wide switch; ``kill_switch`` gates it.

    Every non-tenant fleet scope reaches beyond the single tenant the pause
    capability is scoped to, so without ``kyber.command.kill_switch`` the route
    must refuse.
    """
    await _seed_operator(capabilities=_PAUSE_HOLDER)
    resp = _post(_client(), path, scope=scope, target=None, tenant_header=TENANT_A)
    assert resp.status_code == 403, resp.text
    assert _denial_reason(resp) == "scope_missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [ACTIVATE, DEACTIVATE])
async def test_in_scope_tenant_switch_still_succeeds(path: str) -> None:
    """(c) Pausing (or releasing) the tenant the scope was granted for works."""
    await _seed_operator(capabilities=_PAUSE_HOLDER)
    resp = _post(_client(), path, scope="tenant", target=TENANT_A, tenant_header=TENANT_A)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    switch = data.get("switch")
    if switch is not None:
        # Activate always returns the (new or idempotent) switch.
        assert switch["scope"] == "tenant"
        assert switch["target"] == TENANT_A
    else:
        # Deactivate with nothing active reports ``released: false``, still 200.
        assert data["released"] is False


@pytest.mark.asyncio
async def test_fleet_switch_allowed_when_kill_switch_held() -> None:
    """The UNLESS branch: a ``kill_switch`` holder may flip a global switch."""
    await _seed_operator(capabilities=_KILL_SWITCH_HOLDER)
    resp = _post(
        _client(), ACTIVATE, scope="global", target=None, tenant_header=TENANT_A
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["switch"]["scope"] == "global"


@pytest.mark.asyncio
async def test_tenant_scope_dependency_is_required() -> None:
    """A tenant target with no resolved access scope is refused at the edge.

    ``tenant_scope="required"`` means the route refuses a tenant switch even
    before the handler runs when the caller holds no scope for the tenant it
    names — the same fail-closed shape the command plane uses.
    """
    await _seed_operator(capabilities=_PAUSE_HOLDER)
    resp = _post(
        _client(), ACTIVATE, scope="tenant", target=TENANT_A, tenant_header=None
    )
    # No tenant header -> no requested tenant -> the evaluator denies
    # ``scope_missing``.
    assert resp.status_code == 403, resp.text
    assert _denial_reason(resp) == "scope_missing"
