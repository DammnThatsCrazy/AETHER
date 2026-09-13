"""The single offboarding funnel.

Removing someone's Kyber access is four separate acts — end the employment
record, kill the sessions, revoke the trusted devices, close the tenant access
scopes — and doing three of them is indistinguishable from doing none. This
module is the one place that does all four, so no caller has to remember the
list.

The session, device and scope planes live in sibling packages that are
developed independently. They are imported *inside* the function and behind
``ImportError`` guards: a Kyber deployment that has not yet mounted one of them
must still be able to offboard someone, and the report says plainly which
subsystems were reached and which were not. Identity revocation happens first
and unconditionally, so a partial run still leaves the principal unable to
authenticate.
"""
from __future__ import annotations

import inspect
from typing import Any

from services.kyber.access.contracts import now_iso
from services.security.audit_ledger import audit_ledger
from shared.logger.logger import get_logger, metrics

from .principals import AUDIT_ACTOR_TYPE, principal_service

logger = get_logger("aether.kyber.identity.lifecycle")

__all__ = ["offboard_principal", "revoke_operator_access"]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_first(target: Any, names: tuple[str, ...], **kwargs: Any) -> Any:
    """Call the first method on ``target`` that exists, tolerating signatures.

    Sibling packages are allowed to name their bulk-revocation entry point
    differently; what matters here is that revocation is attempted, not that a
    particular spelling was agreed in advance. A ``TypeError`` from a narrower
    signature is retried without the optional ``reason``.
    """
    for name in names:
        method = getattr(target, name, None)
        if method is None:
            continue
        try:
            return await _maybe_await(method(**kwargs))
        except TypeError:
            trimmed = {k: v for k, v in kwargs.items() if k != "reason"}
            return await _maybe_await(method(**trimmed))
    raise AttributeError(f"none of {names} exist on {target!r}")


def _count(result: Any) -> int:
    if result is None:
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, (list, tuple, set, frozenset)):
        return len(result)
    if isinstance(result, dict):
        for key in ("revoked", "count", "revoked_count", "total"):
            if isinstance(result.get(key), int):
                return int(result[key])
        return len(result)
    return 1


async def revoke_operator_access(
    operator_id: str, *, actor_id: str, reason: str
) -> dict[str, Any]:
    """Revoke sessions, devices and tenant scopes for one operator.

    Returns the same shape as :func:`offboard_principal`'s ``revocations``
    block. Used on its own when access must end without ending employment.
    """
    report: dict[str, Any] = {
        "sessions_revoked": 0,
        "devices_revoked": 0,
        "scopes_revoked": 0,
        "unavailable": [],
        "errors": [],
    }

    # Each plane is resolved and called EXPLICITLY. An earlier version probed a
    # tuple of candidate method names through getattr, which meant a wrong
    # module or symbol was indistinguishable from an absent one: offboarding
    # reported success while devices stayed approved and tenant scopes stayed
    # open. Named calls turn that class of mistake into an ImportError or a
    # TypeError instead of a silent no-op.

    try:
        from services.kyber.sessions.service import session_service
    except ImportError:
        report["unavailable"].append("sessions")
    else:
        try:
            report["sessions_revoked"] = _count(
                await session_service.revoke_for_operator(operator_id, reason=reason)
            )
        except Exception as exc:  # noqa: BLE001 - one plane must not block another
            report["errors"].append(f"sessions: {exc}")

    try:
        from services.kyber.devices.approvals import device_approval_service
    except ImportError:
        report["unavailable"].append("devices")
    else:
        try:
            # There is no bulk per-operator revoke on the device plane, and
            # adding one would duplicate the per-device audit trail. Revoke each
            # device individually so every revocation keeps its own
            # DeviceApprovalEvent and audit-ledger record.
            revoked = 0
            for device in await device_approval_service.list_devices(operator_id):
                if device.revoked_at:
                    continue
                await device_approval_service.revoke_device(
                    device.device_id, actor_id=actor_id, reason=reason
                )
                revoked += 1
            report["devices_revoked"] = revoked
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"devices: {exc}")

    try:
        from services.kyber.access.scopes import access_scope_service
    except ImportError:
        report["unavailable"].append("scopes")
    else:
        try:
            report["scopes_revoked"] = _count(
                await access_scope_service.revoke_for_operator(operator_id, reason=reason)
            )
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(f"scopes: {exc}")

    return report


async def offboard_principal(
    operator_id: str, *, actor_id: str, reason: str
) -> dict[str, Any]:
    """End one operator's Kyber existence and report exactly what was revoked.

    Identity first: the principal is moved to ``offboarded`` and
    ``kyber_enabled`` is cleared before anything else is attempted, so even a
    fully failed downstream revocation leaves an operator who cannot
    authenticate or re-authorize.
    """
    principal = await principal_service.offboard(
        operator_id, actor_id=actor_id, reason=reason
    )
    revocations = await revoke_operator_access(
        operator_id, actor_id=actor_id, reason=reason
    )

    report: dict[str, Any] = {
        "operator_id": operator_id,
        "email": principal.email,
        "employment_status": principal.employment_status,
        "offboarded_at": principal.offboarded_at or now_iso(),
        "reason": reason,
        "actor_id": actor_id,
        "revocations": revocations,
        "complete": not revocations["unavailable"] and not revocations["errors"],
    }

    metrics.increment("kyber_offboard_total")
    if not report["complete"]:
        metrics.increment("kyber_offboard_partial_total")
        logger.warning(
            f"kyber offboard partial operator_id={operator_id} "
            f"unavailable={revocations['unavailable']} errors={revocations['errors']}"
        )

    await audit_ledger.record(
        actor_id=actor_id,
        actor_type=AUDIT_ACTOR_TYPE,
        event_type="kyber.principal.offboard_completed",
        resource_type="workforce_principal",
        action="offboard",
        outcome="allowed" if report["complete"] else "failed",
        resource_id=operator_id,
        metadata={
            "reason": reason,
            "sessions_revoked": revocations["sessions_revoked"],
            "devices_revoked": revocations["devices_revoked"],
            "scopes_revoked": revocations["scopes_revoked"],
            "unavailable": revocations["unavailable"],
            "errors": revocations["errors"],
        },
    )
    return report
