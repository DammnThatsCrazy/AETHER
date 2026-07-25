"""Step-up is only a control if some route actually demands it.

``STEP_UP_REQUIRED_FROM`` is ``D4``, and ``require_kyber_access`` evaluates it
correctly — but a correct evaluator that no route ever reaches is enforcement
that cannot fire. These tests pin both halves:

* the *mechanism*, by walking a D4 authorization through the four states a
  step-up grant can be in — absent, live, expired, and bound to a different
  session — and asserting the first, third and fourth all deny with
  ``step_up_required`` while only the second proceeds; and
* the *reach*, by asserting that at least one route mounted under ``/kyber`` is
  declared at D4 or above in ``config/route_registry.yaml``. That last test is
  the ratchet: if a future edit walks every declaration back below D4, the gap
  fails CI instead of quietly reopening.

The grant-binding cases matter as much as the absent case. A step-up that a
captured handle could replay on another session, or that outlived its window,
would satisfy the check while proving nothing about who is at the keyboard.

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
import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
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
from services.kyber.access.disclosure import (  # noqa: E402
    STEP_UP_REQUIRED_FROM,
    DisclosureLevel,
)
from services.kyber.sessions import cookies  # noqa: E402
from services.kyber.sessions.service import session_service  # noqa: E402
from services.kyber.sessions.step_up import step_up_service  # noqa: E402

ORIGIN = "http://localhost:3000"
AUTHORITY_METHODS = ["google_oidc", "webauthn", "device_proof"]

#: The role used throughout: D4 ceiling, holds ``kyber.audit.read``, and a
#: 10-minute step-up window that the expiry case advances past.
AUDITOR = "security_auditor"
AUDIT_CAPABILITY = "kyber.audit.read"
AUDITOR_STEP_UP_MINUTES = 10

CONFIG = ROOT / "config" / "route_registry.yaml"


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakePrincipal:
    """A live, kyber-enabled workforce principal holding one role template."""

    def __init__(self, operator_id: str, *, templates: list[str]) -> None:
        self.operator_id = operator_id
        self.email = f"{operator_id}@olympus.test"
        self.display_name = operator_id
        self.employment_status = "active"
        self.kyber_enabled = True
        self.allowed_environments: list[str] = []
        self.templates = templates

    @property
    def is_active(self) -> bool:
        return self.employment_status == "active" and self.kyber_enabled


class FakePrincipals:
    """Stands in for ``services.kyber.identity.principals.principal_service``."""

    def __init__(self) -> None:
        self.by_id: dict[str, FakePrincipal] = {}

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
        return frozenset(capabilities_for(principal.templates)) if principal else frozenset()

    async def active_capability_grants(self, operator_id: str, *, environment: Any = None):
        return []


class FakeDevice:
    def __init__(self, device_id: str, operator_id: str) -> None:
        self.device_id = device_id
        self.operator_id = operator_id
        self.approval_state = "approved"
        self.risk_state = "ok"


class FakeDevices:
    """Stands in for the device approval plane; every device is approved."""

    def __init__(self) -> None:
        self.by_id: dict[str, FakeDevice] = {}

    def add(self, device: FakeDevice) -> FakeDevice:
        self.by_id[device.device_id] = device
        return device

    async def get_device(self, device_id: str) -> Optional[FakeDevice]:
        return self.by_id.get(device_id)

    async def resolve_by_grant(self, grant_token: str) -> Optional[FakeDevice]:
        return None

    async def is_usable(self, device_id: Optional[str]) -> tuple[bool, Optional[str]]:
        if not device_id or device_id not in self.by_id:
            return False, "unknown device"
        return True, None

    async def touch(self, device_id: str) -> None:
        return None


class FakeDirectory:
    async def directory_freshness(self, operator_id: str) -> tuple[bool, Optional[str]]:
        return True, None


class FakeProof:
    """A verifier that accepts, so step-up failure is never a proof artifact."""

    def __init__(self) -> None:
        self._n = 0

    async def issue_challenge(self, *, device_id: str) -> tuple[str, str]:
        self._n += 1
        return f"chal_{self._n}", "Y2hhbGxlbmdl"

    async def verify_proof(
        self, *, device_id: str, challenge_id: str, signature_b64: str
    ) -> bool:
        return True


class FakeRequest:
    """A duck-typed stand-in for a Starlette request on a D4 read route."""

    def __init__(self, *, token: str, path: str = "/v1/admin/kyber/security/audit-events") -> None:
        self.method = "GET"
        self.url = SimpleNamespace(path=path)
        self.state = SimpleNamespace()
        self.path_params: dict[str, str] = {}
        self.query_params: dict[str, str] = {}
        self.client = SimpleNamespace(host="10.0.0.9")
        self.cookies: dict[str, str] = {cookies.SESSION_COOKIE_NAME: token}
        self.headers: dict[str, str] = {
            "User-Agent": "kyber-tests/1.0",
            "Origin": ORIGIN,
            "Sec-Fetch-Site": "same-origin",
        }


# ── Harness ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def harness(monkeypatch):
    reset_in_memory_stores()
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("KYBER_ALLOWED_ORIGINS", ORIGIN)

    clock = FixedClock(datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc))
    session_service.set_clock(clock)
    step_up_service.set_clock(clock)

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
    operator_id: str = "op_auditor",
    device_id: str = "dev_laptop",
):
    """Create a live, device-bound workforce session for the auditor role."""
    principals: FakePrincipals = harness.providers.principals
    devices: FakeDevices = harness.providers.devices
    if operator_id not in principals.by_id:
        principals.add(FakePrincipal(operator_id, templates=[AUDITOR]))
    if device_id not in devices.by_id:
        devices.add(FakeDevice(device_id, operator_id))
    return await session_service.create_session(
        operator_id=operator_id,
        google_subject=f"g-{operator_id}",
        device_id=device_id,
        environment="local",
        authentication_methods=AUTHORITY_METHODS,
    )


async def grant_step_up(session, *, device_id: str = "dev_laptop"):
    """Take a live, general (non-capability-narrowed) elevation on a session."""
    challenge_id, _challenge = await step_up_service.issue_challenge(device_id=device_id)
    return await step_up_service.grant(
        session_id=session.session_id,
        operator_id=session.operator_id,
        device_id=device_id,
        reason="reading event-level audit evidence",
        challenge_id=challenge_id,
        signature_b64="c2ln",
    )


async def read_audit_evidence(token: str):
    """The authorization a D4-declared audit-evidence route performs."""
    return await resolve_access_context(
        FakeRequest(token=token),
        AUDIT_CAPABILITY,
        disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
    )


async def denial_reason(coro) -> Optional[str]:
    """Run an authorization expected to fail; return its denial reason."""
    try:
        await coro
    except (ForbiddenError, UnauthorizedError) as exc:
        return exc.details.get("denial_reason")
    raise AssertionError("expected the request to be denied")


# ── The mechanism ────────────────────────────────────────────────────────────


async def test_d4_route_without_a_step_up_grant_is_denied(harness):
    """The default state of a session is *not* stepped up."""
    session, raw = await open_session(harness)

    reason = await denial_reason(read_audit_evidence(raw))

    assert reason == "step_up_required"


async def test_d4_route_with_a_live_step_up_grant_proceeds(harness):
    """The same request, once the human at the keyboard has re-asserted."""
    session, raw = await open_session(harness)
    await grant_step_up(session)

    context = await read_audit_evidence(raw)

    assert context.stepped_up is True
    assert context.granted_disclosure == DisclosureLevel.D4_EVENT_EVIDENCE


async def test_an_expired_step_up_grant_does_not_satisfy_the_check(harness):
    """Elevation is absolute, not sliding: activity never extends it.

    ``security_auditor`` carries ``step_up_minutes = 10``; one minute past that
    the grant is as good as absent, and reads identically to the caller.
    """
    session, raw = await open_session(harness)
    await grant_step_up(session)
    assert (await read_audit_evidence(raw)).stepped_up is True

    harness.clock.advance((AUDITOR_STEP_UP_MINUTES + 1) * 60)

    reason = await denial_reason(read_audit_evidence(raw))
    assert reason == "step_up_required"


async def test_a_grant_bound_to_another_session_does_not_satisfy_the_check(harness):
    """Two live sessions for the same operator on the same device.

    Elevating one must not elevate the other. If it did, a handle captured
    before the step-up would ride an elevation it never proved.
    """
    first, first_raw = await open_session(harness)
    second, _second_raw = await open_session(harness)
    assert first.session_id != second.session_id

    await grant_step_up(second)

    reason = await denial_reason(read_audit_evidence(first_raw))
    assert reason == "step_up_required"

    # ...and the session that actually took the elevation still passes, so the
    # denial above is binding, not a broken grant.
    context = await resolve_access_context(
        FakeRequest(token=_second_raw), AUDIT_CAPABILITY,
        disclosure=DisclosureLevel.D4_EVENT_EVIDENCE,
    )
    assert context.stepped_up is True


# ── The reach ────────────────────────────────────────────────────────────────


def _declarations() -> list[dict]:
    with CONFIG.open("r", encoding="utf-8") as fh:
        catalog = yaml.safe_load(fh) or {}
    return list(catalog.get("kyber_routes") or [])


def test_at_least_one_mounted_kyber_route_is_declared_at_d4_or_above():
    """The ratchet. Without this, the gap this suite closes can silently reopen.

    A D4+ declaration is what records that a route reaches record-level
    evidence. Every declaration is checked against the mounted app, so this
    cannot be satisfied by declaring a path that does not exist.
    """
    import main
    from fastapi.routing import APIRoute

    def iter_api_routes(app):
        for route in app.routes:
            if isinstance(route, APIRoute):
                yield route
            original = getattr(route, "original_router", None)
            if original is not None:
                for inner in original.routes:
                    if isinstance(inner, APIRoute):
                        yield inner

    mounted: set[str] = set()
    for route in iter_api_routes(main.app):
        if "/kyber" not in route.path:
            continue
        for method in route.methods or ():
            mounted.add(f"{method.upper()} {route.path}")

    high = []
    for entry in _declarations():
        level = DisclosureLevel.parse(entry["disclosure"])
        if level >= STEP_UP_REQUIRED_FROM and str(entry["route"]) in mounted:
            high.append(entry["route"])

    assert high, (
        "no mounted Kyber route is declared at D4 or above in "
        "config/route_registry.yaml — STEP_UP_REQUIRED_FROM is D4, so step-up "
        "is enforcement that can never fire. Declare the routes that genuinely "
        "reach record-level evidence."
    )


def test_every_declaration_at_or_above_d4_names_a_capability_that_can_reach_it():
    """A D4+ declaration under a lower-ceilinged capability is a dead route.

    Effective disclosure is the MINIMUM across role, capability, scope and
    request, and asking for more than the ceiling allows is ``disclosure_
    exceeded`` — not a silent downgrade. So declaring D4 on a capability capped
    at D1 does not tighten the route, it bricks it. This catches that at the
    declaration, where it is a typo, rather than in production.
    """
    from services.kyber.access.capabilities import CAPABILITIES

    broken = []
    for entry in _declarations():
        level = DisclosureLevel.parse(entry["disclosure"])
        capability = CAPABILITIES.get(entry["capability"])
        if capability is None:
            continue
        if level > capability.max_disclosure:
            broken.append(
                f"{entry['route']} declares {level.name_token} but "
                f"{capability.capability_id} is capped at "
                f"{capability.max_disclosure.name_token}"
            )

    assert not broken, "unreachable Kyber route declarations:\n  " + "\n  ".join(broken)
