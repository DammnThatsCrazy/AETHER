"""Regression: offboarding must actually revoke devices and scopes.

The revocation funnel resolves the session, device and scope planes through
lazy imports guarded by ``except ImportError``. That guard is correct — one
plane being unavailable must not stop the others — but it means a WRONG module
or symbol name is indistinguishable from an absent one: offboarding reports
success while silently leaving devices approved and tenant scopes open.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")


async def test_offboarding_revokes_devices_and_scopes() -> None:
    from services.kyber.identity.lifecycle import revoke_operator_access

    report = await revoke_operator_access(
        "op_nonexistent", actor_id="op_founder", reason="regression probe"
    )
    assert report["unavailable"] == [], (
        f"offboarding could not resolve these planes: {report['unavailable']} — "
        f"devices and/or scopes would silently survive an offboard. "
        f"full report: {report}"
    )
    assert not report["errors"], f"offboarding errors: {report['errors']}"


async def test_offboarding_actually_revokes_a_real_device_and_scope() -> None:
    """End-to-end: an approved device and an open scope must not survive.

    Resolving the planes is not the same as revoking anything, so this drives
    real records through the funnel rather than asserting on the report shape.
    """
    from services.kyber.access.scopes import access_scope_service
    from services.kyber.devices.approvals import device_approval_service
    from services.kyber.identity.lifecycle import revoke_operator_access

    operator_id = "op_offboard_e2e"

    device = await device_approval_service.register_device(
        operator_id=operator_id, display_name="personal laptop",
        platform_family="macos", browser_family="chrome",
    )
    await device_approval_service.approve_device(
        device.device_id, actor_id="op_founder",
        actor_role_template_ids=["founder_operator"], registration_days=30,
    )
    usable, _ = await device_approval_service.is_usable(device.device_id)
    assert usable, "precondition: the device should be usable before offboarding"

    scope = await access_scope_service.open_scope(
        operator_id=operator_id, session_id="kses_offboard_e2e",
        device_id=device.device_id, environment="local", tenant_id="tenant_x",
        purpose="incident_response", reason="offboarding regression fixture",
        disclosure_level=3, ttl_minutes=30,
    )
    assert scope.status == "active"

    report = await revoke_operator_access(
        operator_id, actor_id="op_founder", reason="offboarded"
    )

    assert report["devices_revoked"] >= 1, f"device not revoked: {report}"
    # scopes_revoked can legitimately be 0 here: revoking the device cascades
    # through session revocation, which already closes the scopes bound to
    # those sessions. What must hold is the END STATE, not which plane got
    # there first — so assert on surviving records below rather than on the
    # counter, which would make a correct cascade look like a failure.

    still_usable, reason = await device_approval_service.is_usable(device.device_id)
    assert not still_usable, "device survived offboarding"
    assert reason == "device_revoked"

    surviving = await access_scope_service.list_scopes(
        operator_id=operator_id, active_only=True
    )
    assert not surviving, f"tenant scope survived offboarding: {surviving}"
