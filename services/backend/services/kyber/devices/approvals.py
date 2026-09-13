"""Device registration, approval and revocation.

A device grant is the third of the three things a trusted device must present.
It is the only one the server can hand out or take back on its own, which makes
it the revocation lever: a WebAuthn credential cannot be un-issued and a proof
key cannot be reached inside the operator's browser, but a grant can be voided
in one write and every session riding it dies with it.

Two rules carry most of the weight here:

* **The raw grant token exists exactly once.** :meth:`approve_device` returns
  it to its caller and stores only ``sha256(token)``. A dump of
  ``kyber_trusted_devices`` therefore cannot be replayed into device trust.
* **Nobody approves their own device.** This mirrors
  :mod:`services.security.break_glass`: the attempt is refused *and* written to
  the audit ledger, because a blocked self-approval is exactly the event an
  investigation needs to see. The single exception is an explicit, deliberate
  bootstrap of the very first founder device, which is itself audited as such.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any, Optional

from shared.common.common import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    utc_now,
)
from shared.logger.logger import get_logger, metrics

from ..access.contracts import DeviceApprovalEvent, TrustedDevice, now_iso
from ..access.roles import DEVICE_APPROVER_TEMPLATE_IDS
from .repository import (
    DeviceApprovalEventRepository,
    TrustedDeviceRepository,
    is_expired,
)

logger = get_logger("aether.kyber.devices.approvals")

#: Cookie carrying the opaque device grant. ``__Host-`` forces the browser to
#: reject it unless it is Secure, path ``/`` and carries no Domain attribute,
#: which is what stops a compromised sibling subdomain from planting one.
GRANT_COOKIE_NAME = "__Host-kyber_device"

#: Bounds on a grant lifetime, independent of what a caller asks for. Role
#: templates supply the intended value (``device_registration_days``); this is
#: the floor and ceiling that no template or request may cross.
MIN_REGISTRATION_DAYS = 1
MAX_REGISTRATION_DAYS = 90

_MAX_DISPLAY_NAME = 80

#: Reasons :meth:`DeviceApprovalService.is_usable` may return. Every value is a
#: member of ``contracts.DenialReason`` and is safe to hand back to a caller —
#: none of them disclose whether a device or operator exists. The finer state
#: lives in the audit ledger and the metric label, not in the response.
USABILITY_REASONS: tuple[str, ...] = ("device_unapproved", "device_revoked")


def grant_hash(token: str) -> str:
    """sha256 of a raw grant token. The only form the database ever sees."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class DeviceApprovalService:
    """The device lifecycle: request, approve, suspend, revoke, rename."""

    def __init__(
        self,
        devices: Optional[TrustedDeviceRepository] = None,
        events: Optional[DeviceApprovalEventRepository] = None,
    ) -> None:
        self._devices = devices or TrustedDeviceRepository()
        self._events = events or DeviceApprovalEventRepository()

    # ── Reads ─────────────────────────────────────────────────────────────────

    async def get_device(self, device_id: str) -> Optional[TrustedDevice]:
        if not device_id:
            return None
        return await self._devices.get(device_id)

    async def resolve_by_grant(self, grant_token: str) -> Optional[TrustedDevice]:
        """Resolve a presented grant cookie to its device.

        A revoked device still resolves. That is intentional: the caller gets a
        precise ``device_revoked`` denial and an audit trail, instead of an
        ambiguous "unknown device" that hides an active attempt to use a
        cancelled grant.
        """
        if not grant_token:
            return None
        return await self._devices.find_by_grant_hash(grant_hash(grant_token))

    async def list_devices(self, operator_id: str) -> list[TrustedDevice]:
        if not operator_id:
            return []
        devices = await self._devices.find_by_operator(operator_id)
        return sorted(devices, key=lambda d: d.requested_at, reverse=True)

    async def history(self, device_id: str) -> list[DeviceApprovalEvent]:
        events = await self._events.find_by_device(device_id)
        return sorted(events, key=lambda e: e.created_at)

    # ── Registration ──────────────────────────────────────────────────────────

    async def register_device(
        self,
        *,
        operator_id: str,
        display_name: str,
        platform_family: Optional[str] = None,
        browser_family: Optional[str] = None,
    ) -> TrustedDevice:
        """Record a device request. Always lands in ``pending``.

        Registration grants nothing. A second browser on the same laptop is a
        second device and waits for its own approval, which is the behaviour
        that makes a synced passkey useless on its own.
        """
        operator_id = (operator_id or "").strip()
        if not operator_id:
            raise BadRequestError("operator_id is required to register a device")
        display_name = self._clean_display_name(display_name)

        existing = await self._find_pending_duplicate(
            operator_id, display_name, browser_family
        )
        if existing is not None:
            # Idempotent: a retried enrollment must not litter the approver's
            # queue with indistinguishable pending rows.
            return existing

        device = TrustedDevice(
            operator_id=operator_id,
            display_name=display_name,
            platform_family=platform_family,
            browser_family=browser_family,
            approval_state="pending",
        )
        await self._devices.save(device)
        await self._record(
            device,
            action="requested",
            actor_id=operator_id,
            from_state=None,
            to_state="pending",
            reason="device registration requested",
        )
        await self._audit(
            actor_id=operator_id,
            event_type="kyber.device.registered",
            action="register",
            outcome="allowed",
            device_id=device.device_id,
            metadata={
                "operator_id": operator_id,
                "platform_family": platform_family,
                "browser_family": browser_family,
            },
        )
        metrics.increment("kyber_device_pending_total")
        logger.info(
            "kyber device registered device_id=%s operator_id=%s",
            device.device_id,
            operator_id,
        )
        return device

    async def _find_pending_duplicate(
        self, operator_id: str, display_name: str, browser_family: Optional[str]
    ) -> Optional[TrustedDevice]:
        for candidate in await self._devices.find_by_state(operator_id, "pending"):
            if (
                candidate.display_name == display_name
                and candidate.browser_family == browser_family
            ):
                return candidate
        return None

    # ── Approval ──────────────────────────────────────────────────────────────

    async def approve_device(
        self,
        device_id: str,
        *,
        actor_id: str,
        actor_role_template_ids: list[str],
        registration_days: int,
        allow_self_approval: bool = False,
        self_approval_reason: Optional[str] = None,
    ) -> tuple[TrustedDevice, str]:
        """Approve a device and mint its grant.

        Returns ``(device, raw_grant_token)``. The raw token is produced here
        and nowhere else; only its sha256 is persisted, so this return value is
        the single opportunity to deliver it to the browser.

        ``allow_self_approval`` is the deliberate bootstrap escape hatch for the
        first founder device, when by definition no second approver exists yet.
        It must be passed explicitly, and its use is audited as
        ``kyber.device.self_approval_bootstrap`` rather than as a normal
        approval.
        """
        device = await self._require_device(device_id)
        days = self._clean_registration_days(registration_days)

        if device.approval_state == "revoked":
            await self._audit(
                actor_id=actor_id,
                event_type="kyber.device.approve_blocked",
                action="approve",
                outcome="blocked",
                device_id=device.device_id,
                metadata={"reason": "device_revoked"},
            )
            raise ConflictError("a revoked device cannot be approved; re-register it")

        if not set(actor_role_template_ids or []) & DEVICE_APPROVER_TEMPLATE_IDS:
            await self._audit(
                actor_id=actor_id,
                event_type="kyber.device.approve_blocked",
                action="approve",
                outcome="blocked",
                device_id=device.device_id,
                metadata={
                    "reason": "approver_role_missing",
                    "actor_role_template_ids": list(actor_role_template_ids or []),
                },
            )
            metrics.increment("kyber_device_denied_total", labels={"reason": "not_approver"})
            raise ForbiddenError("approving a device requires a device-approver role template")

        if device.operator_id == actor_id and not allow_self_approval:
            # Mirrors break-glass second-actor approval: refused *and* recorded.
            # An operator who could approve their own device could enroll a
            # machine of their choosing and reach production unaccompanied.
            await self._audit(
                actor_id=actor_id,
                event_type="kyber.device.self_approval_blocked",
                action="approve",
                outcome="blocked",
                device_id=device.device_id,
                metadata={"reason": "self_approval", "operator_id": device.operator_id},
            )
            metrics.increment(
                "kyber_device_denied_total", labels={"reason": "self_approval"}
            )
            logger.warning(
                "kyber device self-approval blocked device_id=%s actor_id=%s",
                device.device_id,
                actor_id,
            )
            raise ForbiddenError(
                "device approval requires a different operator than the device owner"
            )

        self_approved = device.operator_id == actor_id
        previous_state = device.approval_state
        token = secrets.token_urlsafe(32)
        now = utc_now()

        device.approval_state = "approved"
        device.grant_hash = grant_hash(token)
        device.approved_at = now.isoformat()
        device.approved_by = actor_id
        device.expires_at = (now + timedelta(days=days)).isoformat()
        device.suspended_at = None
        device.metadata["registration_days"] = days
        device.metadata["self_approved"] = self_approved
        await self._devices.save(device)

        action = "reapproved" if previous_state == "approved" else "approved"
        await self._record(
            device,
            action=action,
            actor_id=actor_id,
            from_state=previous_state,
            to_state="approved",
            reason="self-approval bootstrap" if self_approved else None,
            metadata={"registration_days": days, "expires_at": device.expires_at},
        )
        await self._audit(
            actor_id=actor_id,
            event_type=(
                "kyber.device.self_approval_bootstrap"
                if self_approved
                else "kyber.device.approved"
            ),
            action="approve",
            outcome="allowed",
            device_id=device.device_id,
            metadata={
                "operator_id": device.operator_id,
                "registration_days": days,
                "expires_at": device.expires_at,
                "previous_state": previous_state,
                "self_approved": self_approved,
                "bootstrap_reason": self_approval_reason,
            },
        )
        metrics.increment("kyber_device_approved_total")
        logger.info(
            "kyber device approved device_id=%s actor_id=%s days=%s self=%s",
            device.device_id,
            actor_id,
            days,
            self_approved,
        )
        return device, token

    # ── Withdrawal ────────────────────────────────────────────────────────────

    async def suspend_device(
        self, device_id: str, *, actor_id: str, reason: str
    ) -> TrustedDevice:
        """Pause a device without destroying its grant. Idempotent."""
        device = await self._require_device(device_id)
        if device.approval_state == "revoked":
            raise ConflictError("a revoked device cannot be suspended")
        if device.approval_state == "suspended":
            return device

        previous_state = device.approval_state
        device.approval_state = "suspended"
        device.suspended_at = now_iso()
        device.metadata["suspension_reason"] = reason
        await self._devices.save(device)

        await self._record(
            device,
            action="suspended",
            actor_id=actor_id,
            from_state=previous_state,
            to_state="suspended",
            reason=reason,
        )
        await self._audit(
            actor_id=actor_id,
            event_type="kyber.device.suspended",
            action="suspend",
            outcome="allowed",
            device_id=device.device_id,
            metadata={"operator_id": device.operator_id, "reason": reason},
        )
        metrics.increment("kyber_device_suspended_total")
        return device

    async def revoke_device(
        self, device_id: str, *, actor_id: str, reason: str
    ) -> TrustedDevice:
        """Revoke a device and every session bound to it. Idempotent.

        Revocation is the lever that has to work under pressure — a lost
        laptop, an offboarding, a confirmed compromise — so it is written to be
        safe to call repeatedly and it never leaves the device trusted just
        because the session plane was unreachable.
        """
        device = await self._require_device(device_id)
        if device.approval_state == "revoked":
            # Still re-run session revocation: a previous attempt may have
            # failed while the session service was unavailable.
            report = await self._revoke_bound_sessions(device.device_id, reason)
            device.metadata["session_revocation"] = report
            await self._devices.save(device)
            return device

        previous_state = device.approval_state
        device.approval_state = "revoked"
        device.revoked_at = now_iso()
        device.revoked_by = actor_id
        device.revocation_reason = reason
        await self._devices.save(device)

        report = await self._revoke_bound_sessions(device.device_id, reason)
        device.metadata["session_revocation"] = report
        await self._devices.save(device)

        await self._record(
            device,
            action="revoked",
            actor_id=actor_id,
            from_state=previous_state,
            to_state="revoked",
            reason=reason,
            metadata={"session_revocation": report},
        )
        await self._audit(
            actor_id=actor_id,
            event_type="kyber.device.revoked",
            action="revoke",
            outcome="allowed",
            device_id=device.device_id,
            metadata={
                "operator_id": device.operator_id,
                "reason": reason,
                "session_revocation": report,
            },
        )
        metrics.increment("kyber_device_revoked_total")
        logger.warning(
            "kyber device revoked device_id=%s actor_id=%s reason=%s sessions=%s",
            device.device_id,
            actor_id,
            reason,
            report,
        )
        return device

    async def _revoke_bound_sessions(
        self, device_id: str, reason: str
    ) -> dict[str, Any]:
        """Ask the session plane to kill everything bound to this device.

        The session package is a sibling that may not be present in every
        deployment slice, so the import is function-level and guarded. A failure
        here is reported, never swallowed into a false "device is safe now" —
        the device is revoked either way, so a stale session is a bounded
        problem an operator can see in the report.
        """
        report: dict[str, Any] = {
            "attempted": True,
            "succeeded": False,
            "revoked": 0,
            "error": None,
            "at": now_iso(),
        }
        try:
            from services.kyber.sessions.service import session_service
        except ImportError:
            report["error"] = "session_service_unavailable"
            logger.warning(
                "kyber device revocation could not reach the session plane device_id=%s",
                device_id,
            )
            return report

        try:
            result = await session_service.revoke_for_device(device_id, reason=reason)
        except Exception as exc:  # noqa: BLE001 - reported, never fatal to revocation
            report["error"] = type(exc).__name__
            logger.error(
                "kyber device session revocation failed device_id=%s error=%s",
                device_id,
                exc,
            )
            return report

        report["succeeded"] = True
        report["revoked"] = result if isinstance(result, int) else len(result or [])
        return report

    async def rename_device(
        self, device_id: str, *, actor_id: str, display_name: str
    ) -> TrustedDevice:
        """Rename a device. Cosmetic only — it changes no authority. Idempotent."""
        device = await self._require_device(device_id)
        cleaned = self._clean_display_name(display_name)
        if cleaned == device.display_name:
            return device

        previous_name = device.display_name
        device.display_name = cleaned
        await self._devices.save(device)

        await self._record(
            device,
            action="renamed",
            actor_id=actor_id,
            from_state=device.approval_state,
            to_state=device.approval_state,
            reason="renamed",
            metadata={"from": previous_name, "to": cleaned},
        )
        await self._audit(
            actor_id=actor_id,
            event_type="kyber.device.renamed",
            action="rename",
            outcome="allowed",
            device_id=device.device_id,
            metadata={"from": previous_name, "to": cleaned},
        )
        return device

    async def touch(self, device_id: str) -> None:
        """Stamp last use. Never changes approval or risk state."""
        device = await self._devices.get(device_id)
        if device is None:
            return
        device.last_used_at = now_iso()
        await self._devices.save(device)

    # ── The gate ──────────────────────────────────────────────────────────────

    async def is_usable(self, device_id: str) -> tuple[bool, Optional[str]]:
        """Whether a device may carry authority right now.

        Returns ``(True, None)`` or ``(False, reason)`` where *reason* is one of
        :data:`USABILITY_REASONS` — a coarse, caller-safe string. An unknown
        device is reported exactly like an unapproved one so the answer never
        confirms that a device id exists.

        Expiry is evaluated lazily here rather than by a sweep, so a grant that
        has run out is denied at the moment it is used even if no background job
        has run.
        """
        device = await self._devices.get(device_id) if device_id else None
        if device is None:
            self._deny_metric("unknown")
            return False, "device_unapproved"

        if device.approval_state == "revoked":
            self._deny_metric("revoked")
            return False, "device_revoked"
        if device.approval_state == "suspended":
            self._deny_metric("suspended")
            return False, "device_revoked"
        if device.risk_state == "blocked":
            self._deny_metric("risk_blocked")
            return False, "device_revoked"
        if device.approval_state == "pending":
            self._deny_metric("pending")
            return False, "device_unapproved"
        if device.approval_state == "expired":
            self._deny_metric("expired")
            return False, "device_unapproved"
        if device.approval_state != "approved":
            self._deny_metric("not_approved")
            return False, "device_unapproved"

        if is_expired(device.expires_at):
            device.approval_state = "expired"
            await self._devices.save(device)
            self._deny_metric("expired")
            return False, "device_unapproved"

        return True, None

    @staticmethod
    def _deny_metric(detail: str) -> None:
        metrics.increment("kyber_device_denied_total", labels={"detail": detail})

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _require_device(self, device_id: str) -> TrustedDevice:
        device = await self._devices.get(device_id) if device_id else None
        if device is None:
            raise NotFoundError("Kyber device")
        return device

    @staticmethod
    def _clean_display_name(display_name: str) -> str:
        cleaned = (display_name or "").strip()
        if not cleaned:
            raise BadRequestError("display_name is required")
        if len(cleaned) > _MAX_DISPLAY_NAME:
            raise BadRequestError(
                f"display_name must be at most {_MAX_DISPLAY_NAME} characters"
            )
        return cleaned

    @staticmethod
    def _clean_registration_days(registration_days: int) -> int:
        try:
            days = int(registration_days)
        except (TypeError, ValueError) as exc:
            raise BadRequestError("registration_days must be an integer") from exc
        if days < MIN_REGISTRATION_DAYS or days > MAX_REGISTRATION_DAYS:
            raise BadRequestError(
                "registration_days must be between "
                f"{MIN_REGISTRATION_DAYS} and {MAX_REGISTRATION_DAYS}"
            )
        return days

    async def _record(
        self,
        device: TrustedDevice,
        *,
        action: str,
        actor_id: str,
        from_state: Optional[str],
        to_state: Optional[str],
        reason: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> DeviceApprovalEvent:
        event = DeviceApprovalEvent(
            device_id=device.device_id,
            operator_id=device.operator_id,
            action=action,  # type: ignore[arg-type]
            actor_id=actor_id,
            from_state=from_state,  # type: ignore[arg-type]
            to_state=to_state,  # type: ignore[arg-type]
            reason=reason,
            metadata=metadata or {},
        )
        return await self._events.append(event)

    @staticmethod
    async def _audit(
        *,
        actor_id: str,
        event_type: str,
        action: str,
        outcome: str,
        device_id: str,
        metadata: Optional[dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        from services.security.audit_ledger import audit_ledger

        await audit_ledger.record(
            actor_id=actor_id,
            actor_type="olympus_operator",
            event_type=event_type,
            resource_type="kyber_device",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            resource_id=device_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata=metadata or {},
        )


device_approval_service = DeviceApprovalService()

__all__ = [
    "GRANT_COOKIE_NAME",
    "MAX_REGISTRATION_DAYS",
    "MIN_REGISTRATION_DAYS",
    "USABILITY_REASONS",
    "DeviceApprovalService",
    "device_approval_service",
    "grant_hash",
]
