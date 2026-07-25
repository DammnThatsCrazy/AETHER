"""``emergency_root`` must be reachable only through an approved break-glass.

The template shipped with the workforce plane but nothing was wired to it: no
approval, no alert, and nothing stopping an ordinary role binding from handing
out standing D5, action-class-5 authority. These tests pin the four properties
that make it a break-glass identity rather than a very powerful role:

* a second actor is required, and a self-approval is refused *and* recorded —
  a blocked emergency approval is a security event, not a silent no-op;
* ordinary role binding refuses the template outright;
* an approved grant is visible through one canonical predicate, so nothing has
  to re-derive "is this operator elevated right now"; and
* the sitting is 15 minutes, taken from the template rather than restated here.

Every transition writes a critical audit event through the existing ledger.
The second-actor rule itself lives in ``break_glass_service.approve`` and is
deliberately not re-implemented in Kyber — these tests exercise it *through*
the Kyber surface, which is what proves the delegation is real.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.common.common import BadRequestError, ForbiddenError  # noqa: E402


def _errors() -> tuple[type[Exception], ...]:
    """Resolve the error classes against the CURRENT module cache.

    Several suites evict and re-import the backend packages under a modified
    ``sys.path`` (see the ``backend_on_path`` helpers). After such an eviction
    ``shared.common.common`` is a fresh module object, so the classes bound at
    import time here are no longer the classes being raised —
    ``pytest.raises(BadRequestError)`` then lets the real refusal escape and the
    test fails for a reason that has nothing to do with the behaviour under
    test. Binding at call time makes these assertions order-independent.
    """
    import importlib

    common = importlib.import_module("shared.common.common")
    return (common.BadRequestError, BadRequestError)


def _errors_forbidden() -> tuple[type[Exception], ...]:
    """Same rationale as :func:`_errors`, for ForbiddenError."""
    import importlib

    common = importlib.import_module("shared.common.common")
    return (common.ForbiddenError, ForbiddenError)

from services.kyber.access.emergency import (  # noqa: E402
    EMERGENCY_SCOPE,
    EMERGENCY_TEMPLATE_ID,
    PLATFORM_EMERGENCY_TENANT,
    assert_not_emergency_template,
    emergency_access_service,
)
from services.kyber.access.roles import ROLE_TEMPLATES  # noqa: E402
from services.security.repositories import (  # noqa: E402
    SecurityAuditEventRepository,
)

REQUESTER = "op_oncall"
APPROVER = "op_founder"
REASON = "primary ingestion path down; every operator role is locked out"


@pytest.fixture(autouse=True)
def clean_stores():
    """Emergency state is durable, so it must not leak between tests."""
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def audit_events(event_type: str) -> list[dict]:
    """Every recorded ledger event of one type."""
    rows = await SecurityAuditEventRepository().find_many({}, limit=500)
    return [r for r in rows if r.get("event_type") == event_type]


async def open_request(*, operator_id: str = REQUESTER) -> dict:
    return await emergency_access_service.request_emergency_access(
        operator_id=operator_id,
        reason=REASON,
        ticket_reference="INC-4417",
    )


# ── Second-actor approval ────────────────────────────────────────────────────


async def test_self_approval_is_refused_and_audited():
    """The requester approving themselves would make the second actor optional."""
    request = await open_request()

    with pytest.raises(_errors()):
        await emergency_access_service.approve_emergency_access(
            request_id=request["request_id"], approved_by=REQUESTER
        )

    # The refusal is recorded on both sides: by break-glass, which owns the
    # rule, and by Kyber, which owns the critical emergency alert.
    blocked = await audit_events("break_glass.self_approval_blocked")
    assert len(blocked) == 1
    assert blocked[0]["outcome"] == "blocked"

    kyber_blocked = await audit_events("kyber.emergency.approval_blocked")
    assert len(kyber_blocked) == 1
    assert kyber_blocked[0]["outcome"] == "blocked"
    assert kyber_blocked[0]["metadata"]["severity"] == "critical"

    # And nothing was granted.
    assert await emergency_access_service.has_active_emergency(REQUESTER) is False


async def test_a_second_operator_can_approve():
    request = await open_request()

    approved = await emergency_access_service.approve_emergency_access(
        request_id=request["request_id"], approved_by=APPROVER
    )

    assert approved["status"] == "approved"
    assert approved["requested_by"] == REQUESTER
    assert approved["approved_by"] == APPROVER
    assert approved["expires_at"]


# ── Role binding ─────────────────────────────────────────────────────────────


def test_ordinary_role_binding_cannot_grant_emergency_root():
    """The guard the role-binding path calls before writing any binding."""
    with pytest.raises(_errors_forbidden()):
        assert_not_emergency_template(EMERGENCY_TEMPLATE_ID)


def test_the_guard_does_not_block_ordinary_templates():
    """A guard that refused everything would just be an outage."""
    for template_id in ROLE_TEMPLATES:
        if template_id == EMERGENCY_TEMPLATE_ID:
            continue
        assert_not_emergency_template(template_id)  # must not raise


# ── Visibility of a live grant ───────────────────────────────────────────────


async def test_an_active_emergency_grant_is_visible():
    request = await open_request()
    await emergency_access_service.approve_emergency_access(
        request_id=request["request_id"], approved_by=APPROVER
    )

    assert await emergency_access_service.has_active_emergency(REQUESTER) is True
    # The approver did not thereby elevate themselves.
    assert await emergency_access_service.has_active_emergency(APPROVER) is False

    active = await emergency_access_service.active_emergency_requests()
    assert [r["request_id"] for r in active] == [request["request_id"]]
    assert active[0]["tenant_id"] == PLATFORM_EMERGENCY_TENANT
    assert active[0]["requested_scope"] == EMERGENCY_SCOPE


async def test_an_unapproved_request_grants_nothing():
    await open_request()

    assert await emergency_access_service.has_active_emergency(REQUESTER) is False
    assert await emergency_access_service.active_emergency_requests() == []


# ── The sitting is bounded by the template ───────────────────────────────────


def test_emergency_session_ceiling_is_fifteen_minutes():
    """Asserted against the template, so drifting the template fails here."""
    template = ROLE_TEMPLATES[EMERGENCY_TEMPLATE_ID]

    assert template.session_absolute_minutes == 15
    assert template.session_idle_minutes == 15
    assert template.step_up_minutes == 15
    # No presence session: emergency root cannot be left sitting open.
    assert template.presence_minutes == 0
    # And it cannot approve the devices that would extend its own reach.
    assert template.may_approve_devices is False


# ── Critical audit on every transition ───────────────────────────────────────


async def test_a_critical_audit_event_is_written_on_request_and_on_approve():
    request = await open_request()

    requested = await audit_events("kyber.emergency.requested")
    assert len(requested) == 1
    assert requested[0]["actor_id"] == REQUESTER
    assert requested[0]["actor_type"] == "olympus_operator"
    assert requested[0]["tenant_id"] == PLATFORM_EMERGENCY_TENANT
    assert requested[0]["metadata"]["severity"] == "critical"
    assert requested[0]["metadata"]["role_template_id"] == EMERGENCY_TEMPLATE_ID
    assert requested[0]["metadata"]["ticket_reference"] == "INC-4417"

    await emergency_access_service.approve_emergency_access(
        request_id=request["request_id"], approved_by=APPROVER
    )

    approved = await audit_events("kyber.emergency.approved")
    assert len(approved) == 1
    assert approved[0]["actor_id"] == APPROVER
    assert approved[0]["resource_id"] == request["request_id"]
    assert approved[0]["metadata"]["severity"] == "critical"
    assert approved[0]["metadata"]["requested_by"] == REQUESTER


async def test_using_a_grant_is_itself_audited():
    """Holding emergency authority is not the event — reaching for it is."""
    request = await open_request()
    await emergency_access_service.approve_emergency_access(
        request_id=request["request_id"], approved_by=APPROVER
    )

    assert await audit_events("kyber.emergency.used") == []

    assert await emergency_access_service.has_active_emergency(REQUESTER) is True

    used = await audit_events("kyber.emergency.used")
    assert len(used) == 1
    assert used[0]["actor_id"] == REQUESTER
    assert used[0]["metadata"]["severity"] == "critical"
