"""Kyber workforce sessions: token handling, expiry layers, rotation, step-up.

These tests assert the properties that make a Kyber session a credential rather
than a cookie: the raw handle exists once, the idle window *slides* (the defect
in the older tenant session service), the absolute ceiling holds against
continuous activity, and every event that changes what the session is worth —
role change, device revocation, principal suspension, replay from another
machine — ends or rotates it.

No test sleeps. Every service takes an injectable clock and the tests advance it
explicitly, so an expiry test costs microseconds and cannot flake.
"""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.common.common import ForbiddenError, UnauthorizedError  # noqa: E402
from shared.temporal.clock import FixedClock  # noqa: E402

from services.kyber.access.dependencies import (  # noqa: E402
    AccessProviders,
    reset_providers,
    resolve_access_context,
    set_providers,
)
from services.kyber.access.scopes import access_scope_service  # noqa: E402
from services.kyber.sessions import cookies, validation  # noqa: E402
from services.kyber.sessions.service import hash_token, session_service  # noqa: E402
from services.kyber.sessions.step_up import step_up_service  # noqa: E402

ORIGIN = "http://localhost:3000"
AUTHORITY_METHODS = ["google_oidc", "webauthn", "device_proof"]


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakePrincipal:
    def __init__(
        self,
        operator_id: str,
        *,
        templates: list[str],
        active: bool = True,
        environments: Optional[list[str]] = None,
    ) -> None:
        self.operator_id = operator_id
        self.email = f"{operator_id}@olympus.test"
        self.display_name = operator_id
        self.employment_status = "active" if active else "suspended"
        self.kyber_enabled = active
        self.allowed_environments = environments or []
        self.templates = templates

    @property
    def is_active(self) -> bool:
        return self.employment_status == "active" and self.kyber_enabled


class FakePrincipals:
    def __init__(self) -> None:
        self.by_id: dict[str, FakePrincipal] = {}
        self.denied: set[tuple[str, str]] = set()

    def add(self, principal: FakePrincipal) -> FakePrincipal:
        self.by_id[principal.operator_id] = principal
        return principal

    async def get_by_operator_id(self, operator_id: str) -> Optional[FakePrincipal]:
        return self.by_id.get(operator_id)

    async def role_template_ids(self, operator_id: str, *, environment: Any = None) -> list[str]:
        principal = self.by_id.get(operator_id)
        return list(principal.templates) if principal else []

    async def effective_capabilities(self, operator_id: str, *, environment: Any = None):
        from services.kyber.access.roles import capabilities_for

        principal = self.by_id.get(operator_id)
        if principal is None:
            return frozenset()
        caps = set(capabilities_for(principal.templates))
        caps -= {c for (op, c) in self.denied if op == operator_id}
        return frozenset(caps)

    async def active_capability_grants(self, operator_id: str, *, environment: Any = None):
        return [
            SimpleNamespace(capability_id=cap, effect="deny")
            for (op, cap) in self.denied
            if op == operator_id
        ]


class FakeDevice:
    def __init__(self, device_id: str, operator_id: str) -> None:
        self.device_id = device_id
        self.operator_id = operator_id
        self.approval_state = "approved"
        self.risk_state = "ok"


class FakeDevices:
    def __init__(self) -> None:
        self.by_id: dict[str, FakeDevice] = {}
        self.revoked: set[str] = set()
        self.grants: dict[str, str] = {}

    def add(self, device: FakeDevice, *, grant: Optional[str] = None) -> FakeDevice:
        self.by_id[device.device_id] = device
        if grant:
            self.grants[grant] = device.device_id
        return device

    async def get_device(self, device_id: str) -> Optional[FakeDevice]:
        return self.by_id.get(device_id)

    async def resolve_by_grant(self, grant_token: str) -> Optional[FakeDevice]:
        device_id = self.grants.get(grant_token)
        return self.by_id.get(device_id) if device_id else None

    async def is_usable(self, device_id: Optional[str]) -> tuple[bool, Optional[str]]:
        if not device_id or device_id not in self.by_id:
            return False, "unknown device"
        if device_id in self.revoked:
            return False, "device revoked"
        return True, None

    async def touch(self, device_id: str) -> None:
        return None


class FakeDirectory:
    def __init__(self) -> None:
        self.stale: set[str] = set()

    async def directory_freshness(self, operator_id: str) -> tuple[bool, Optional[str]]:
        if operator_id in self.stale:
            return False, "last sync older than the freshness window"
        return True, None


class FakeProof:
    def __init__(self) -> None:
        self.accept = True
        self.issued: list[str] = []

    async def issue_challenge(self, *, device_id: str) -> tuple[str, str]:
        challenge_id = f"chal_{len(self.issued)}"
        self.issued.append(challenge_id)
        return challenge_id, "Y2hhbGxlbmdl"

    async def verify_proof(self, *, device_id: str, challenge_id: str, signature_b64: str) -> bool:
        return self.accept


class FakeRequest:
    """A duck-typed stand-in for a Starlette request."""

    def __init__(
        self,
        *,
        method: str = "GET",
        path: str = "/v1/kyber/platform/health",
        token: Optional[str] = None,
        csrf: Optional[str] = None,
        origin: Optional[str] = ORIGIN,
        tenant_id: Optional[str] = None,
        device_grant: Optional[str] = None,
    ) -> None:
        self.method = method
        self.url = SimpleNamespace(path=path)
        self.state = SimpleNamespace()
        self.path_params: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.client = SimpleNamespace(host="10.0.0.9")
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {"User-Agent": "kyber-tests/1.0"}
        if token:
            self.cookies[cookies.SESSION_COOKIE_NAME] = token
        if csrf:
            self.cookies[cookies.CSRF_COOKIE_NAME] = csrf
            self.headers[cookies.CSRF_HEADER_NAME] = csrf
        if origin:
            self.headers["Origin"] = origin
            self.headers["Sec-Fetch-Site"] = "same-origin"
        if tenant_id:
            self.path_params["tenant_id"] = tenant_id
        if device_grant:
            self.cookies["__Host-kyber_device"] = device_grant


class FakeResponse:
    """Captures cookie writes so attributes can be asserted."""

    def __init__(self) -> None:
        self.cookies: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []

    def set_cookie(self, name: str, value: str, **kwargs: Any) -> None:
        self.cookies[name] = {"value": value, **kwargs}

    def delete_cookie(self, name: str, **kwargs: Any) -> None:
        self.deleted.append(name)


# ── Harness ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def harness(monkeypatch):
    """Fresh stores, a frozen clock, and fake providers for every test."""
    reset_in_memory_stores()
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("KYBER_ALLOWED_ORIGINS", ORIGIN)

    clock = FixedClock(datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc))
    session_service.set_clock(clock)
    step_up_service.set_clock(clock)
    access_scope_service.set_clock(clock)

    providers = AccessProviders(
        principals=FakePrincipals(),
        devices=FakeDevices(),
        directory=FakeDirectory(),
        proof=FakeProof(),
    )
    set_providers(providers)

    yield SimpleNamespace(clock=clock, providers=providers)

    reset_providers()
    reset_in_memory_stores()


async def open_session(
    harness,
    *,
    operator_id: str = "op_engineer",
    templates: Optional[list[str]] = None,
    methods: Optional[list[str]] = None,
    device_id: str = "dev_laptop",
    environment: str = "local",
):
    """Register a principal + device and open a session. Returns (session, raw)."""
    principals: FakePrincipals = harness.providers.principals
    devices: FakeDevices = harness.providers.devices
    if operator_id not in principals.by_id:
        principals.add(
            FakePrincipal(operator_id, templates=templates or ["founding_engineer"])
        )
    if device_id not in devices.by_id:
        devices.add(FakeDevice(device_id, operator_id), grant=f"grant_{device_id}")
    return await session_service.create_session(
        operator_id=operator_id,
        google_subject=f"g-{operator_id}",
        device_id=device_id,
        environment=environment,
        authentication_methods=list(methods or AUTHORITY_METHODS),
        client_ip="10.0.0.9",
        user_agent="kyber-tests/1.0",
    )


async def raw_row(session_id: str) -> dict:
    from services.kyber.sessions.service import KyberSessionRepository

    row = await KyberSessionRepository().find_by_id(session_id)
    assert row is not None
    return row


# ── Token handling ───────────────────────────────────────────────────────────


async def test_raw_token_returned_once_and_only_its_digest_is_stored(harness):
    session, raw = await open_session(harness)

    assert raw.startswith("kses_")
    row = await raw_row(session.session_id)
    assert row["token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw not in repr(row)
    # No field on the persisted row carries the raw handle in any form.
    assert not any(isinstance(v, str) and raw in v for v in row.values())
    # Nor does the model handed back to the caller.
    assert raw not in session.model_dump_json()


async def test_unknown_token_is_no_session_and_hash_is_the_only_lookup_key(harness):
    session, raw = await open_session(harness)

    found, reason = await session_service.validate(raw)
    assert reason is None and found is not None

    missing, reason = await session_service.validate("kses_" + "0" * 48)
    assert missing is None and reason == "no_session"

    # Presenting the stored digest instead of the handle proves nothing.
    digest, reason = await session_service.validate(hash_token(raw))
    assert digest is None and reason == "no_session"


async def test_rotation_invalidates_the_previous_handle_immediately(harness):
    session, first = await open_session(harness)
    _rotated, second = await session_service.rotate(session.session_id, reason="privilege_change")

    assert second != first
    stale, reason = await session_service.validate(first)
    assert stale is None and reason == "no_session"

    live, reason = await session_service.validate(second)
    assert reason is None and live is not None and live.session_id == session.session_id


async def test_replay_from_a_different_device_is_denied(harness):
    session, raw = await open_session(harness)
    harness.providers.devices.add(FakeDevice("dev_attacker", "op_engineer"))

    stolen, reason = await session_service.validate(raw, device_id="dev_attacker")
    assert stolen is None and reason == "device_mismatch"

    ok, reason = await session_service.validate(raw, device_id="dev_laptop")
    assert reason is None and ok is not None


# ── Cookie transport ─────────────────────────────────────────────────────────


async def test_host_prefixed_cookie_carries_no_domain_and_is_httponly_strict(monkeypatch):
    response = FakeResponse()
    cookies.set_session_cookie(response, "kses_deadbeef", max_age=3600)

    written = response.cookies[cookies.SESSION_COOKIE_NAME]
    assert cookies.SESSION_COOKIE_NAME.startswith("__Host-")
    # The __Host- prefix is only honoured when Domain is absent entirely.
    assert "domain" not in written
    assert written["path"] == "/"
    assert written["httponly"] is True
    assert written["samesite"] == "strict"
    assert written["max_age"] == 3600


async def test_secure_is_only_relaxed_in_local_dev_and_test(monkeypatch):
    for env in ("local", "dev", "development", "test"):
        monkeypatch.setenv("AETHER_ENV", env)
        assert cookies.cookie_secure() is False

    for env in ("staging", "production", "prod", "", "LOCALHOST"):
        monkeypatch.setenv("AETHER_ENV", env)
        assert cookies.cookie_secure() is True, env

    monkeypatch.setenv("AETHER_ENV", "production")
    response = FakeResponse()
    cookies.set_session_cookie(response, "kses_deadbeef")
    assert response.cookies[cookies.SESSION_COOKIE_NAME]["secure"] is True


async def test_session_token_is_read_from_cookie_header_and_bearer(monkeypatch):
    request = FakeRequest(token="kses_abc")
    assert cookies.read_session_token(request) == "kses_abc"

    bearer = FakeRequest()
    bearer.headers["Authorization"] = "Bearer kses_xyz"
    assert cookies.read_session_token(bearer) == "kses_xyz"

    # A tenant API key must never be mistaken for a Kyber handle.
    foreign = FakeRequest()
    foreign.headers["Authorization"] = "Bearer sk_live_tenant_key"
    assert cookies.read_session_token(foreign) is None


# ── Expiry layers ────────────────────────────────────────────────────────────


async def test_idle_window_slides_on_use_then_expires(harness):
    """The defect in services/auth/sessions: idle must move, then close."""
    session, raw = await open_session(harness)  # founding_engineer: idle 120m
    original_idle = session.idle_expires_at

    harness.clock.advance(60 * 60)
    live, reason = await session_service.validate(raw)
    assert reason is None and live is not None
    assert live.idle_expires_at > original_idle  # it slid

    harness.clock.advance(60 * 60)
    live, reason = await session_service.validate(raw)
    assert reason is None, "an actively used session must not hit the idle cap"

    # Now go quiet for longer than the idle window.
    harness.clock.advance(121 * 60)
    dead, reason = await session_service.validate(raw)
    assert dead is None and reason == "session_expired"


async def test_absolute_ceiling_holds_against_continuous_activity(harness):
    session, raw = await open_session(harness)  # founding_engineer: absolute 720m

    for _ in range(11):  # 11 hours of steady use, well inside the idle window
        harness.clock.advance(60 * 60)
        live, reason = await session_service.validate(raw)
        assert reason is None, "activity must keep the idle window open"
        assert live is not None
        assert live.idle_expires_at <= (live.authority_expires_at or "")

    harness.clock.advance(60 * 60)  # t = 12h = the absolute ceiling
    dead, reason = await session_service.validate(raw)
    assert dead is None and reason == "session_expired"


async def test_presence_session_is_restricted_and_cannot_reach_an_authority_route(harness):
    session, raw = await open_session(harness, methods=["google_oidc"])

    assert session.status == "restricted"
    assert session.authentication_strength == "identity_only"

    found, reason = await session_service.validate(raw)
    assert found is not None and reason == "session_restricted"

    request = FakeRequest(token=raw)
    with pytest.raises(ForbiddenError) as excinfo:
        await resolve_access_context(request, "kyber.graph.fleet.read")
    assert excinfo.value.details["denial_reason"] == "session_restricted"

    # The same session still satisfies a presence-only route.
    context = await resolve_access_context(
        FakeRequest(token=raw), "kyber.workforce.self.read", presence_only=True
    )
    assert context.session.session_id == session.session_id


async def test_revoked_session_reports_revoked_not_expired(harness):
    session, raw = await open_session(harness)
    await session_service.revoke(session.session_id, reason="operator_logout")

    dead, reason = await session_service.validate(raw)
    assert dead is None and reason == "session_revoked"


# ── Lifecycle coupling ───────────────────────────────────────────────────────


async def test_role_change_terminates_sessions_bound_to_the_old_templates(harness):
    session, raw = await open_session(harness, templates=["founding_engineer"])

    unchanged = await session_service.reconcile_privileges(
        "op_engineer", new_template_ids=["founding_engineer"]
    )
    assert unchanged == 0

    revoked = await session_service.reconcile_privileges(
        "op_engineer", new_template_ids=["observer"], reason="role_change"
    )
    assert revoked == 1

    dead, reason = await session_service.validate(raw)
    assert dead is None and reason == "session_revoked"


async def test_device_revocation_terminates_every_session_on_that_device(harness):
    first_session, first = await open_session(harness)
    second_session, second = await session_service.create_session(
        operator_id="op_engineer",
        google_subject="g-op_engineer",
        device_id="dev_laptop",
        environment="local",
        authentication_methods=AUTHORITY_METHODS,
    )
    other_session, other = await open_session(
        harness, operator_id="op_other", device_id="dev_other"
    )

    revoked = await session_service.revoke_for_device("dev_laptop", reason="device_revoked")
    assert revoked == 2

    for token in (first, second):
        dead, reason = await session_service.validate(token)
        assert dead is None and reason == "session_revoked"

    survivor, reason = await session_service.validate(other)
    assert reason is None and survivor is not None


async def test_principal_suspension_terminates_sessions_and_closes_scopes(harness):
    session, raw = await open_session(harness)
    scope = await access_scope_service.open_scope(
        operator_id="op_engineer",
        session_id=session.session_id,
        device_id="dev_laptop",
        environment="local",
        tenant_id="tenant_alpha",
        purpose="incident_response",
        reason="investigating ingestion backlog for tenant alpha",
        disclosure_level=3,
        ttl_minutes=60,
    )

    revoked = await session_service.revoke_for_operator("op_engineer", reason="suspended")
    assert revoked == 1

    dead, reason = await session_service.validate(raw)
    assert dead is None and reason == "session_revoked"

    closed = await access_scope_service.get(scope.scope_id)
    assert closed is not None and closed.status == "revoked"
    assert await access_scope_service.current_scope(session.session_id) is None


# ── Step-up ──────────────────────────────────────────────────────────────────


async def test_step_up_requires_a_verified_assertion_and_expires(harness):
    session, raw = await open_session(harness)

    ok, reason = await step_up_service.require_fresh(session.session_id)
    assert ok is False and reason == "step_up_required"

    challenge_id, _challenge = await step_up_service.issue_challenge(device_id="dev_laptop")
    grant = await step_up_service.grant(
        session_id=session.session_id,
        operator_id="op_engineer",
        device_id="dev_laptop",
        capability_id="kyber.graph.evidence.read",
        reason="reading lineage for an incident",
        challenge_id=challenge_id,
        signature_b64="c2ln",
    )
    assert grant.expires_at > grant.created_at

    ok, reason = await step_up_service.require_fresh(
        session.session_id, capability_id="kyber.graph.evidence.read"
    )
    assert ok is True and reason is None

    # A grant narrowed to one capability does not satisfy another.
    ok, reason = await step_up_service.require_fresh(
        session.session_id, capability_id="kyber.command.pause"
    )
    assert ok is False and reason == "step_up_required"

    harness.clock.advance(11 * 60)  # founding_engineer: step_up_minutes = 10
    ok, reason = await step_up_service.require_fresh(
        session.session_id, capability_id="kyber.graph.evidence.read"
    )
    assert ok is False and reason == "step_up_required"


async def test_step_up_refuses_an_unverified_or_unprovable_assertion(harness):
    session, _raw = await open_session(harness)
    challenge_id, _ = await step_up_service.issue_challenge(device_id="dev_laptop")

    harness.providers.proof.accept = False
    with pytest.raises(UnauthorizedError):
        await step_up_service.grant(
            session_id=session.session_id,
            operator_id="op_engineer",
            device_id="dev_laptop",
            challenge_id=challenge_id,
            signature_b64="bad",
        )

    # A missing verifier is never a passing verifier.
    harness.providers.proof = None
    set_providers(harness.providers)
    with pytest.raises(UnauthorizedError):
        await step_up_service.grant(
            session_id=session.session_id,
            operator_id="op_engineer",
            device_id="dev_laptop",
            challenge_id=challenge_id,
            signature_b64="c2ln",
        )


async def test_step_up_grant_is_bound_to_the_session_device(harness):
    session, _raw = await open_session(harness)
    challenge_id, _ = await step_up_service.issue_challenge(device_id="dev_laptop")

    with pytest.raises(UnauthorizedError):
        await step_up_service.grant(
            session_id=session.session_id,
            operator_id="op_engineer",
            device_id="dev_somewhere_else",
            challenge_id=challenge_id,
            signature_b64="c2ln",
        )


async def test_step_up_rotation_replaces_the_handle(harness):
    session, first = await open_session(harness)
    challenge_id, _ = await step_up_service.issue_challenge(device_id="dev_laptop")

    _grant, second = await step_up_service.grant_and_rotate(
        session_id=session.session_id,
        operator_id="op_engineer",
        device_id="dev_laptop",
        challenge_id=challenge_id,
        signature_b64="c2ln",
    )

    assert second != first
    stale, reason = await session_service.validate(first)
    assert stale is None and reason == "no_session"

    live, reason = await session_service.validate(second)
    assert reason is None and live is not None
    assert live.authentication_strength == "stepped_up"


async def test_elevation_lapses_back_to_device_bound_without_ending_the_session(harness):
    session, raw = await open_session(harness)
    challenge_id, _ = await step_up_service.issue_challenge(device_id="dev_laptop")
    await step_up_service.grant(
        session_id=session.session_id,
        operator_id="op_engineer",
        device_id="dev_laptop",
        challenge_id=challenge_id,
        signature_b64="c2ln",
    )

    harness.clock.advance(11 * 60)
    live, reason = await session_service.validate(raw)
    assert reason is None and live is not None
    assert live.authentication_strength == "device_bound"


# ── Request-shape controls ───────────────────────────────────────────────────


async def test_csrf_mismatch_rejects_a_mutating_request(harness):
    session, raw = await open_session(harness)

    request = FakeRequest(method="POST", token=raw, csrf="csrf-good")
    assert validation.validate_mutating_request(request) is None

    request.headers[cookies.CSRF_HEADER_NAME] = "csrf-forged"
    assert validation.validate_mutating_request(request) == validation.CSRF_FAILURE

    del request.headers[cookies.CSRF_HEADER_NAME]
    assert validation.validate_mutating_request(request) == validation.CSRF_FAILURE

    with pytest.raises(ForbiddenError):
        await resolve_access_context(request, "kyber.incident.manage")


async def test_foreign_or_absent_origin_rejects_a_mutating_request(harness):
    session, raw = await open_session(harness)

    hostile = FakeRequest(
        method="POST", token=raw, csrf="csrf-good", origin="https://evil.example"
    )
    assert validation.validate_mutating_request(hostile) == validation.ORIGIN_FAILURE

    stripped = FakeRequest(method="POST", token=raw, csrf="csrf-good", origin=None)
    assert validation.validate_mutating_request(stripped) == validation.ORIGIN_MISSING_FAILURE

    # A prefix that merely starts with an allowed origin is not that origin.
    lookalike = FakeRequest(
        method="POST", token=raw, csrf="csrf-good", origin="http://localhost:3000.evil.example"
    )
    assert validation.validate_mutating_request(lookalike) == validation.ORIGIN_FAILURE

    # Safe methods are exempt: they cannot change state.
    assert validation.validate_mutating_request(FakeRequest(origin=None)) is None

    with pytest.raises(ForbiddenError):
        await resolve_access_context(hostile, "kyber.incident.manage")


async def test_cross_site_fetch_metadata_is_refused(harness):
    request = FakeRequest(method="POST", csrf="csrf-good")
    request.headers["Sec-Fetch-Site"] = "cross-site"
    assert validation.validate_mutating_request(request) == validation.FETCH_SITE_FAILURE

    request.headers["Sec-Fetch-Site"] = "same-site"  # a sibling subdomain is not us
    assert validation.validate_mutating_request(request) == validation.FETCH_SITE_FAILURE


async def test_privilege_change_demands_rotation(harness):
    assert validation.requires_rotation(
        previous_strength="identity_only", new_strength="device_bound"
    )
    assert validation.requires_rotation(
        previous_strength="device_bound",
        new_strength="device_bound",
        previous_template_ids=["observer"],
        new_template_ids=["founder_operator"],
    )
    assert not validation.requires_rotation(
        previous_strength="device_bound",
        new_strength="device_bound",
        previous_template_ids=["observer"],
        new_template_ids=["observer"],
    )
