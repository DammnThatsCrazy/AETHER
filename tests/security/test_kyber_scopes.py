"""Kyber tenant access scopes and the backend authorization sequence.

The scope tests assert the five properties the previous in-process tenant-entry
dictionary did not have: durability, session **and** device binding, exactly one
tenant, expiry, and a full audit trail on open/exit/expiry/revoke.

The authorization tests walk ``require_kyber_access`` step by step. The theme
throughout is that a client-supplied identifier never grants authority: a tenant
id in the path is compared against the open scope and, when it disagrees, the
request is denied rather than silently re-scoped.

No test sleeps; every service takes an injectable clock.
"""
from __future__ import annotations

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
from shared.common.common import BadRequestError, ForbiddenError, UnauthorizedError  # noqa: E402
from shared.temporal.clock import FixedClock  # noqa: E402

from services.kyber.access.dependencies import (  # noqa: E402
    AccessProviders,
    KyberAccessDecisionRepository,
    current_kyber_context,
    require_kyber_access,
    reset_providers,
    resolve_access_context,
    set_providers,
)
from services.kyber.access.disclosure import DisclosureLevel  # noqa: E402
from services.kyber.access.scopes import (  # noqa: E402
    MAX_SCOPE_MINUTES,
    MIN_SCOPE_MINUTES,
    access_scope_service,
)
from services.kyber.sessions import cookies  # noqa: E402
from services.kyber.sessions.service import session_service  # noqa: E402
from services.kyber.sessions.step_up import step_up_service  # noqa: E402

ORIGIN = "http://localhost:3000"
AUTHORITY_METHODS = ["google_oidc", "webauthn", "device_proof"]
REASON = "investigating an ingestion backlog reported by tenant alpha"


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
    """Stands in for Worker A's ``principal_service``.

    ``leaky`` simulates an ``effective_capabilities`` implementation that
    forgets to subtract a deny grant, so the independent deny check in the
    authorization sequence can be exercised on its own.
    """

    def __init__(self) -> None:
        self.by_id: dict[str, FakePrincipal] = {}
        self.denied: set[tuple[str, str]] = set()
        self.leaky = False

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
        if not self.leaky:
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
        self.grants[grant or f"grant_{device.device_id}"] = device.device_id
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
        self._n = 0

    async def issue_challenge(self, *, device_id: str) -> tuple[str, str]:
        self._n += 1
        return f"chal_{self._n}", "Y2hhbGxlbmdl"

    async def verify_proof(self, *, device_id: str, challenge_id: str, signature_b64: str) -> bool:
        return self.accept


class FakeRequest:
    """A duck-typed stand-in for a Starlette request."""

    def __init__(
        self,
        *,
        method: str = "GET",
        path: str = "/v1/kyber/tenants/{tenant_id}/mirror",
        token: Optional[str] = None,
        tenant_id: Optional[str] = None,
        device_grant: Optional[str] = None,
        csrf: Optional[str] = None,
    ) -> None:
        self.method = method
        self.url = SimpleNamespace(path=path)
        self.state = SimpleNamespace()
        self.path_params: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.client = SimpleNamespace(host="10.0.0.9")
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {
            "User-Agent": "kyber-tests/1.0",
            "Origin": ORIGIN,
            "Sec-Fetch-Site": "same-origin",
        }
        if token:
            self.cookies[cookies.SESSION_COOKIE_NAME] = token
        if csrf:
            self.cookies[cookies.CSRF_COOKIE_NAME] = csrf
            self.headers[cookies.CSRF_HEADER_NAME] = csrf
        if tenant_id:
            self.path_params["tenant_id"] = tenant_id
        if device_grant:
            self.cookies["__Host-kyber_device"] = device_grant


# ── Harness ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def harness(monkeypatch):
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
    device_id: str = "dev_laptop",
    environment: str = "local",
    environments: Optional[list[str]] = None,
):
    principals: FakePrincipals = harness.providers.principals
    devices: FakeDevices = harness.providers.devices
    if operator_id not in principals.by_id:
        principals.add(
            FakePrincipal(
                operator_id,
                templates=templates or ["founding_engineer"],
                environments=environments,
            )
        )
    if device_id not in devices.by_id:
        devices.add(FakeDevice(device_id, operator_id))
    return await session_service.create_session(
        operator_id=operator_id,
        google_subject=f"g-{operator_id}",
        device_id=device_id,
        environment=environment,
        authentication_methods=AUTHORITY_METHODS,
    )


async def open_scope(session, *, tenant_id="tenant_alpha", level=3, ttl=60, device_id=None):
    return await access_scope_service.open_scope(
        operator_id=session.operator_id,
        session_id=session.session_id,
        device_id=device_id or session.device_id,
        environment=session.environment,
        tenant_id=tenant_id,
        purpose="incident_response",
        reason=REASON,
        disclosure_level=level,
        ttl_minutes=ttl,
    )


async def denial_reason(coro) -> str:
    """Run an authorization call expected to fail; return its denial reason."""
    try:
        await coro
    except (ForbiddenError, UnauthorizedError) as exc:
        return exc.details.get("denial_reason")
    raise AssertionError("expected the request to be denied")


async def decision_count() -> int:
    return await KyberAccessDecisionRepository().count()


# ── Scope lifecycle ──────────────────────────────────────────────────────────


async def test_scope_is_durable_and_bound_to_session_and_device(harness):
    session, _raw = await open_session(harness)
    scope = await open_scope(session)

    assert scope.session_id == session.session_id
    assert scope.device_id == session.device_id
    assert scope.tenant_id == "tenant_alpha"
    assert scope.status == "active"

    # Durable: a fresh service instance over the same store still sees it.
    from services.kyber.access.scopes import AccessScopeService

    reloaded = await AccessScopeService(clock=harness.clock).current_scope(session.session_id)
    assert reloaded is not None and reloaded.scope_id == scope.scope_id


async def test_opening_a_second_scope_closes_the_first(harness):
    session, _raw = await open_session(harness)
    first = await open_scope(session, tenant_id="tenant_alpha")
    second = await open_scope(session, tenant_id="tenant_beta")

    closed = await access_scope_service.get(first.scope_id)
    assert closed is not None and closed.status == "exited"
    assert closed.exited_at is not None

    current = await access_scope_service.current_scope(session.session_id)
    assert current is not None and current.scope_id == second.scope_id

    # Exactly one active scope per session, always.
    active = await access_scope_service.list_scopes(
        operator_id=session.operator_id, active_only=True
    )
    assert [s.scope_id for s in active] == [second.scope_id]


async def test_reason_must_be_substantive_and_purpose_must_be_known(harness):
    session, _raw = await open_session(harness)

    with pytest.raises(BadRequestError):
        await access_scope_service.open_scope(
            operator_id=session.operator_id,
            session_id=session.session_id,
            device_id=session.device_id,
            environment="local",
            tenant_id="tenant_alpha",
            purpose="incident_response",
            reason="looking",  # under the 10-character floor
        )

    with pytest.raises(BadRequestError):
        await access_scope_service.open_scope(
            operator_id=session.operator_id,
            session_id=session.session_id,
            device_id=session.device_id,
            environment="local",
            tenant_id="tenant_alpha",
            purpose="just_curious",
            reason=REASON,
        )


async def test_ttl_is_clamped_to_the_permitted_window(harness):
    session, _raw = await open_session(harness)

    long_scope = await open_scope(session, ttl=10_000)
    assert long_scope.metadata["ttl_minutes"] == MAX_SCOPE_MINUTES

    short_scope = await open_scope(session, ttl=0)
    assert short_scope.metadata["ttl_minutes"] == MIN_SCOPE_MINUTES


async def test_scope_expires_and_exit_is_idempotent(harness):
    session, _raw = await open_session(harness)
    scope = await open_scope(session, ttl=5)

    harness.clock.advance(6 * 60)
    assert await access_scope_service.current_scope(session.session_id) is None
    expired = await access_scope_service.get(scope.scope_id)
    assert expired is not None and expired.status == "expired"

    # Exiting an already-closed scope neither errors nor reopens it.
    again = await access_scope_service.exit_scope(scope.scope_id, actor_id=session.operator_id)
    assert again is not None and again.status == "expired"


async def test_resolve_for_tenant_reports_missing_expired_and_mismatch(harness):
    session, _raw = await open_session(harness)

    scope, reason = await access_scope_service.resolve_for_tenant(
        session.session_id, "tenant_alpha"
    )
    assert scope is None and reason == "scope_missing"

    opened = await open_scope(session, tenant_id="tenant_alpha", ttl=5)
    scope, reason = await access_scope_service.resolve_for_tenant(
        session.session_id, "tenant_alpha"
    )
    assert reason is None and scope is not None and scope.scope_id == opened.scope_id

    # A different tenant is a denial, never a silent re-scope.
    scope, reason = await access_scope_service.resolve_for_tenant(session.session_id, "tenant_beta")
    assert scope is None and reason == "scope_tenant_mismatch"
    still_alpha = await access_scope_service.current_scope(session.session_id)
    assert still_alpha is not None and still_alpha.tenant_id == "tenant_alpha"

    harness.clock.advance(6 * 60)
    scope, reason = await access_scope_service.resolve_for_tenant(
        session.session_id, "tenant_alpha"
    )
    assert scope is None and reason == "scope_expired"


async def test_scope_revocation_by_session_and_by_operator(harness):
    session, _raw = await open_session(harness)
    await open_scope(session)
    assert await access_scope_service.revoke_for_session(
        session.session_id, reason="session_revoked"
    ) == 1
    assert await access_scope_service.current_scope(session.session_id) is None

    await open_scope(session)
    assert await access_scope_service.revoke_for_operator(
        session.operator_id, reason="suspended"
    ) == 1
    assert await access_scope_service.current_scope(session.session_id) is None


# ── Authorization: tenant scoping ────────────────────────────────────────────


async def test_tenant_route_without_a_scope_is_denied(harness):
    session, raw = await open_session(harness, templates=["product_manager"])
    request = FakeRequest(token=raw, tenant_id="tenant_alpha")

    reason = await denial_reason(
        resolve_access_context(request, "kyber.tenant.mirror.read", tenant_scope="required")
    )
    assert reason == "scope_missing"


async def test_expired_scope_is_denied(harness):
    session, raw = await open_session(harness, templates=["product_manager"])
    await open_scope(session, ttl=5)
    harness.clock.advance(6 * 60)

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_alpha"),
            "kyber.tenant.mirror.read",
            tenant_scope="required",
        )
    )
    assert reason == "scope_expired"


async def test_a_path_tenant_that_differs_from_the_scope_tenant_is_denied(harness):
    """A client-supplied tenant id never grants authority."""
    session, raw = await open_session(harness, templates=["product_manager"])
    await open_scope(session, tenant_id="tenant_alpha")

    allowed = await resolve_access_context(
        FakeRequest(token=raw, tenant_id="tenant_alpha"),
        "kyber.tenant.mirror.read",
        tenant_scope="required",
    )
    assert allowed.scope is not None and allowed.scope.tenant_id == "tenant_alpha"

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_beta"),
            "kyber.tenant.mirror.read",
            tenant_scope="required",
        )
    )
    assert reason == "scope_tenant_mismatch"

    # The scope was not widened or moved by the attempt.
    current = await access_scope_service.current_scope(session.session_id)
    assert current is not None and current.tenant_id == "tenant_alpha"


async def test_scope_opened_on_another_device_does_not_authorize_this_session(harness):
    session, raw = await open_session(harness, templates=["product_manager"])
    harness.providers.devices.add(FakeDevice("dev_other", session.operator_id))
    await open_scope(session, tenant_id="tenant_alpha", device_id="dev_other")

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_alpha"),
            "kyber.tenant.mirror.read",
            tenant_scope="required",
        )
    )
    assert reason == "device_mismatch"


# ── Authorization: capabilities, roles, environment ──────────────────────────


async def test_observer_cannot_reach_tenant_detail(harness):
    session, raw = await open_session(harness, operator_id="op_observer", templates=["observer"])
    await open_scope(session, tenant_id="tenant_alpha")

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_alpha"),
            "kyber.tenant.mirror.read",
            tenant_scope="required",
        )
    )
    assert reason == "capability_missing"

    # Fleet aggregates remain reachable — the boundary is tenant detail.
    context = await resolve_access_context(
        FakeRequest(token=raw), "kyber.graph.fleet.read"
    )
    assert context.granted_disclosure == DisclosureLevel.D1_FLEET_AGGREGATE


async def test_a_product_role_cannot_execute_a_command_capability(harness):
    session, raw = await open_session(harness, operator_id="op_pm", templates=["product_manager"])
    await open_scope(session, tenant_id="tenant_alpha")

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(method="GET", token=raw, tenant_id="tenant_alpha"),
            "kyber.command.retry",
            tenant_scope="required",
        )
    )
    assert reason == "capability_missing"


async def test_an_engineer_cannot_manage_the_workforce(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), "kyber.workforce.manage")
    )
    assert reason == "capability_missing"


async def test_a_deny_grant_beats_an_allowing_role_template(harness):
    session, raw = await open_session(harness, operator_id="op_founder", templates=["founder_operator"])
    principals: FakePrincipals = harness.providers.principals

    # The template allows it today.
    context = await resolve_access_context(FakeRequest(token=raw), "kyber.incident.read")
    assert context.has_capability("kyber.incident.read")

    # A deny grant lands. Even if the capability union forgets to subtract it,
    # the independent deny read must still refuse.
    principals.denied.add(("op_founder", "kyber.incident.read"))
    principals.leaky = True
    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), "kyber.incident.read")
    )
    assert reason == "capability_missing"


async def test_action_class_ceiling_is_enforced(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), None, action_class=4)
    )
    assert reason == "action_class_exceeded"


async def test_environment_restriction_is_enforced_per_template(harness):
    _session, raw = await open_session(
        harness,
        operator_id="op_designer",
        templates=["designer"],  # local + staging only
        environment="production",
    )

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), "kyber.graph.fleet.read")
    )
    assert reason == "environment_not_allowed"


async def test_stale_directory_withdraws_privileged_authority(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])
    harness.providers.directory.stale.add("op_engineer")

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), "kyber.graph.fleet.read")
    )
    assert reason == "directory_stale"


async def test_revoked_device_denies_and_reports_revocation(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])
    harness.providers.devices.revoked.add("dev_laptop")

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), "kyber.graph.fleet.read")
    )
    assert reason == "device_revoked"


async def test_a_device_grant_for_another_machine_is_a_mismatch(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])
    harness.providers.devices.add(FakeDevice("dev_attacker", "op_engineer"))

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, device_grant="grant_dev_attacker"),
            "kyber.graph.fleet.read",
        )
    )
    assert reason == "device_mismatch"


async def test_inactive_principal_is_denied(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])
    harness.providers.principals.by_id["op_engineer"].employment_status = "suspended"

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token=raw), "kyber.graph.fleet.read")
    )
    assert reason == "principal_inactive"


# ── Authorization: disclosure and step-up ────────────────────────────────────


async def test_disclosure_is_the_minimum_across_every_constraint(harness):
    session, raw = await open_session(
        harness, operator_id="op_founder", templates=["founder_operator"]
    )
    # Role ceiling D5, capability ceiling D3, scope ceiling D2 → granted D2.
    await open_scope(session, tenant_id="tenant_alpha", level=2)

    context = await resolve_access_context(
        FakeRequest(token=raw, tenant_id="tenant_alpha"),
        "kyber.tenant.mirror.read",
        tenant_scope="required",
    )
    assert context.granted_disclosure == DisclosureLevel.D2_TENANT_MASKED
    assert context.masks_identifiers() is True

    # Asking for more than the minimum allows is a denial, not a downgrade.
    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_alpha"),
            "kyber.tenant.mirror.read",
            disclosure=DisclosureLevel.D3_TENANT_VISIBLE,
            tenant_scope="required",
        )
    )
    assert reason == "disclosure_exceeded"


async def test_raw_evidence_requires_a_live_step_up(harness):
    session, raw = await open_session(
        harness, operator_id="op_founder", templates=["founder_operator"]
    )
    await open_scope(session, tenant_id="tenant_alpha", level=5)

    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_alpha"),
            "kyber.tenant.raw.read",
            tenant_scope="required",
        )
    )
    assert reason == "step_up_required"

    challenge_id, _ = await step_up_service.issue_challenge(device_id="dev_laptop")
    await step_up_service.grant(
        session_id=session.session_id,
        operator_id="op_founder",
        device_id="dev_laptop",
        capability_id="kyber.tenant.raw.read",
        reason="unmasking one record for a data request",
        challenge_id=challenge_id,
        signature_b64="c2ln",
    )

    context = await resolve_access_context(
        FakeRequest(token=raw, tenant_id="tenant_alpha"),
        "kyber.tenant.raw.read",
        tenant_scope="required",
    )
    assert context.granted_disclosure == DisclosureLevel.D5_RAW_EVIDENCE
    assert context.stepped_up is True

    # And it lapses.
    harness.clock.advance(16 * 60)  # founder_operator: step_up_minutes = 15
    reason = await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_alpha"),
            "kyber.tenant.raw.read",
            tenant_scope="required",
        )
    )
    assert reason == "step_up_required"


# ── Evidence and fail-closed behaviour ───────────────────────────────────────


async def test_every_sensitive_request_writes_an_access_decision(harness):
    session, raw = await open_session(harness, operator_id="op_pm", templates=["product_manager"])
    await open_scope(session, tenant_id="tenant_alpha")

    before = await decision_count()

    context = await resolve_access_context(
        FakeRequest(token=raw, tenant_id="tenant_alpha"),
        "kyber.tenant.mirror.read",
        tenant_scope="required",
    )
    assert context.decision is not None
    assert await decision_count() == before + 1

    await denial_reason(
        resolve_access_context(
            FakeRequest(token=raw, tenant_id="tenant_beta"),
            "kyber.tenant.mirror.read",
            tenant_scope="required",
        )
    )
    assert await decision_count() == before + 2

    rows = await KyberAccessDecisionRepository().find_many({"allowed": False}, limit=10)
    denied = [r for r in rows if r.get("denial_reason") == "scope_tenant_mismatch"]
    assert denied, "the denial must be durable evidence, not just a log line"
    assert denied[0]["operator_id"] == "op_pm"
    assert denied[0]["session_id"] == session.session_id
    assert denied[0]["tenant_id"] == "tenant_beta"


async def test_a_missing_provider_denies_rather_than_allows(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])

    for attribute, expected in (
        ("devices", "device_unapproved"),
        ("directory", "directory_stale"),
        ("principals", "principal_unknown"),
    ):
        providers = AccessProviders(
            principals=harness.providers.principals,
            devices=harness.providers.devices,
            directory=harness.providers.directory,
            proof=harness.providers.proof,
        )
        setattr(providers, attribute, None)
        set_providers(providers)

        reason = await denial_reason(
            resolve_access_context(FakeRequest(token=raw), "kyber.graph.fleet.read")
        )
        assert reason == expected, attribute


async def test_no_session_is_denied_before_anything_else_is_consulted(harness):
    reason = await denial_reason(
        resolve_access_context(FakeRequest(), "kyber.graph.fleet.read")
    )
    assert reason == "no_session"

    reason = await denial_reason(
        resolve_access_context(FakeRequest(token="kses_" + "0" * 48), "kyber.graph.fleet.read")
    )
    assert reason == "no_session"


async def test_dependency_factory_stashes_the_context_on_request_state(harness):
    _session, raw = await open_session(harness, templates=["founding_engineer"])
    dependency = require_kyber_access("kyber.graph.fleet.read")
    request = FakeRequest(token=raw)

    assert current_kyber_context(request) is None
    context = await dependency(request)
    assert current_kyber_context(request) is context
    assert context.decision is not None and context.decision.allowed is True


# ── Cross-module contract: the policy-engine call must not drift ─────────────
#
# `_record_through_policy_engine` catches every exception and degrades to a
# direct audit entry. That is the right runtime behaviour — a Kyber decision
# must never be lost — but it means a signature mismatch is SILENT: the
# `kyber.access` rows simply stop reaching `security_policy_decisions` and
# `policy_decision_id` stops being linked onto the decision row. These two
# modules are written independently, so pin them to each other.

def test_policy_engine_call_signature_matches() -> None:
    """Every kwarg the dependency sends must exist on check_kyber_access."""
    import ast
    import inspect
    from pathlib import Path

    from services.kyber.access import dependencies as deps
    from services.security.policy_engine import PolicyEngine

    accepted = set(inspect.signature(PolicyEngine.check_kyber_access).parameters) - {"self"}

    source = Path(deps.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    sent: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # the call is `await check(...)` where `check` came from getattr()
        if isinstance(func, ast.Name) and func.id == "check":
            sent = {kw.arg for kw in node.keywords if kw.arg}
            break

    assert sent, "could not locate the check_kyber_access call in dependencies.py"
    unexpected = sent - accepted
    assert not unexpected, (
        f"dependencies.py sends kwargs check_kyber_access does not accept: "
        f"{sorted(unexpected)} — the call would raise TypeError and silently "
        f"fall back to an audit-only record"
    )

    required = {
        name
        for name, param in inspect.signature(PolicyEngine.check_kyber_access).parameters.items()
        if name != "self" and param.default is inspect.Parameter.empty
    }
    missing = required - sent
    assert not missing, (
        f"check_kyber_access requires kwargs the dependency never sends: {sorted(missing)}"
    )


async def test_policy_engine_records_a_linked_decision() -> None:
    """A real decision reaches security_policy_decisions and links back."""
    from services.kyber.access.contracts import KyberAccessDecision
    from services.kyber.access.dependencies import _record_through_policy_engine

    decision = KyberAccessDecision(
        operator_id="op_sig",
        session_id="kses_sig",
        device_id="dev_sig",
        capability_id="kyber.tenant.mirror.read",
        action="read",
        action_class=0,
        route_id="GET /v1/kyber/tenants/{tenant_id}/mirror",
        environment="local",
        tenant_id="tenant_sig",
        purpose="diagnostics",
        requested_disclosure=3,
        granted_disclosure=3,
        allowed=True,
    )

    policy_decision_id = await _record_through_policy_engine(decision)
    assert policy_decision_id, (
        "no policy decision id returned — the call fell back to audit-only, "
        "so kyber.access decisions are not reaching security_policy_decisions"
    )
