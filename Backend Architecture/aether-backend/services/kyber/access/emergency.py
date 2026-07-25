"""Emergency root access — the ``emergency_root`` template, wired to break-glass.

``emergency_root`` is the one Kyber role that carries D5 raw evidence and a
fleet-destructive action ceiling on a 15-minute session. Until this module it
existed only as a template in :mod:`services.kyber.access.roles` and as a name
in the invitation blocklist: nothing bound it to an approval, nothing alerted
when it was used, and nothing stopped an ordinary role binding from handing it
out. A break-glass identity that can be granted like any other role is not a
break-glass identity.

**One emergency path, not two.** Every transition here delegates to
:mod:`services.security.break_glass`, which already implements the parts that
are easy to get wrong — second-actor approval (the requester may never approve
their own request, and the refusal is itself audited), automatic expiry, and a
tamper-evident record of request/approve/deny/revoke/expire/use. This module
adds the Kyber-specific layer on top: a reserved platform scope, a critical
audit event on every transition, ``kyber_emergency_access_*_total`` metrics,
and the guard that keeps ``emergency_root`` out of ordinary role binding.

**Mapping a platform-wide emergency onto a tenant-oriented service.**
``break_glass_service`` is scoped to one tenant, because ordinary break-glass
is "let me into tenant X for four hours". Emergency root is not tenant-scoped —
it is authority over the platform. Rather than fork the service or invent a
second table, an emergency-root request is recorded against the reserved tenant
id :data:`PLATFORM_EMERGENCY_TENANT` (``"__platform__"``), which is not a
routable tenant and can never collide with a real one, and carries the reserved
scope string :data:`EMERGENCY_SCOPE`. Every read here filters on that reserved
tenant, so platform emergencies and ordinary tenant break-glass never mix in
either direction.

**The window is not the sitting.** :data:`EMERGENCY_WINDOW_HOURS` is 1, the
smallest window ``break_glass_service`` accepts. It bounds how long the *grant*
stays approvable-into; what bounds an actual sitting is the ``emergency_root``
template's ``session_absolute_minutes`` of 15. The grant is the outer envelope,
the session is the inner one, and the inner one is what an operator feels.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.common.common import ForbiddenError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.kyber.access.emergency")

#: Reserved, non-routable tenant id under which platform-wide emergency access
#: is recorded in ``security_break_glass_requests``. Not a real tenant: the
#: double-underscore form cannot be issued by tenant provisioning, so a
#: platform emergency can never be confused with a tenant break-glass grant.
PLATFORM_EMERGENCY_TENANT = "__platform__"

#: The scope string every emergency-root request carries.
EMERGENCY_SCOPE = "kyber:emergency_root"

#: The role template this module governs.
EMERGENCY_TEMPLATE_ID = "emergency_root"

#: Grant window handed to ``break_glass_service`` — its accepted minimum. The
#: operative ceiling is the template's 15-minute session, not this.
EMERGENCY_WINDOW_HOURS = 1

#: Actor type every Kyber audit entry uses.
_ACTOR_TYPE = "olympus_operator"


class EmergencyAccessService:
    """Request, approve and observe emergency root access.

    Every method delegates the state machine to ``break_glass_service`` and
    keeps only the Kyber-facing concerns: the reserved platform scope, critical
    audit events, and metrics. Nothing here re-implements approval, expiry or
    the second-actor rule.
    """

    # ── Transitions ──────────────────────────────────────────────────────────

    async def request_emergency_access(
        self,
        *,
        operator_id: str,
        reason: str,
        ticket_reference: Optional[str] = None,
    ) -> dict[str, Any]:
        """Open an emergency-root request awaiting a second operator's approval.

        Args:
            operator_id: The principal asking for emergency authority.
            reason: Free text, required and non-empty (enforced downstream).
            ticket_reference: Optional incident/ticket id, recorded in audit.

        Returns:
            The break-glass request as a plain dict, status ``requested``.
            A request grants nothing on its own — approval does.
        """
        from services.security.break_glass import break_glass_service

        request = await break_glass_service.request(
            tenant_id=PLATFORM_EMERGENCY_TENANT,
            requested_by=operator_id,
            reason=reason,
            requested_scope=EMERGENCY_SCOPE,
            window_hours=EMERGENCY_WINDOW_HOURS,
        )
        await self._audit(
            actor_id=operator_id,
            event_type="kyber.emergency.requested",
            action="request",
            outcome="allowed",
            resource_id=request.request_id,
            metadata={"reason": reason, "ticket_reference": ticket_reference},
        )
        metrics.increment("kyber_emergency_access_requested_total")
        logger.warning(
            f"kyber: EMERGENCY ROOT requested operator={operator_id} "
            f"request={request.request_id} ticket={ticket_reference or '-'}"
        )
        return request.model_dump()

    async def approve_emergency_access(
        self,
        *,
        request_id: str,
        approved_by: str,
    ) -> dict[str, Any]:
        """Approve an emergency-root request as the second actor.

        Self-approval is refused by ``break_glass_service.approve`` — which
        also audits the refusal — and that refusal is deliberately not
        re-implemented here. This method adds the Kyber-side critical event for
        both outcomes and lets the original error propagate unchanged.

        Raises:
            BadRequestError: when the approver is the requester, or the
                request is not in ``requested`` status.
        """
        from services.security.break_glass import break_glass_service

        try:
            approved = await break_glass_service.approve(
                request_id=request_id, approved_by=approved_by
            )
        except Exception as exc:
            await self._audit(
                actor_id=approved_by,
                event_type="kyber.emergency.approval_blocked",
                action="approve",
                outcome="blocked",
                resource_id=request_id,
                metadata={"error": type(exc).__name__, "detail": str(exc)},
            )
            metrics.increment("kyber_emergency_access_blocked_total")
            logger.warning(
                f"kyber: EMERGENCY ROOT approval blocked request={request_id} "
                f"approver={approved_by}: {exc}"
            )
            raise

        await self._audit(
            actor_id=approved_by,
            event_type="kyber.emergency.approved",
            action="approve",
            outcome="allowed",
            resource_id=request_id,
            metadata={
                "requested_by": approved.requested_by,
                "expires_at": approved.expires_at,
            },
        )
        metrics.increment("kyber_emergency_access_approved_total")
        logger.warning(
            f"kyber: EMERGENCY ROOT approved request={request_id} "
            f"approver={approved_by} requester={approved.requested_by}"
        )
        return approved.model_dump()

    # ── Reads ────────────────────────────────────────────────────────────────

    async def has_active_emergency(self, operator_id: str) -> bool:
        """Whether ``operator_id`` holds a live, approved emergency grant.

        Reading this is itself a use of emergency authority, so it emits the
        critical ``kyber.emergency.used`` event and increments the use metric
        whenever the answer is yes. ``break_glass_service.has_active_grant``
        expires stale grants as a side effect, so a lapsed grant reads false.
        """
        from services.security.break_glass import break_glass_service

        active = await break_glass_service.has_active_grant(
            PLATFORM_EMERGENCY_TENANT, operator_id
        )
        if active:
            await self._audit(
                actor_id=operator_id,
                event_type="kyber.emergency.used",
                action="access",
                outcome="allowed",
                resource_id=None,
                metadata={"scope": EMERGENCY_SCOPE},
            )
            metrics.increment("kyber_emergency_access_used_total")
            logger.warning(f"kyber: EMERGENCY ROOT grant used operator={operator_id}")
        return active

    async def active_emergency_requests(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Every live (``approved``) emergency request, newest data first.

        Filtered to the reserved platform tenant, so ordinary tenant
        break-glass never appears on the emergency surface.
        """
        from services.security.break_glass import break_glass_service

        rows = await break_glass_service.list_requests(
            tenant_id=PLATFORM_EMERGENCY_TENANT, limit=limit
        )
        return [row for row in rows if row.get("status") == "approved"]

    # ── Guard for the role-binding path ──────────────────────────────────────

    @staticmethod
    def assert_not_emergency_template(role_template_id: str) -> None:
        """Refuse ``emergency_root`` as an ordinary role binding.

        ``emergency_root`` is reachable only through the approved break-glass
        path in this module. Binding it as a normal role would produce exactly
        the thing the template exists to prevent: standing D5, action-class-5
        authority with no second actor, no expiry and no alert.

        The integrator calls this from
        ``services.kyber.identity.principals.PrincipalService.bind_role`` before
        any binding is written.

        Raises:
            ForbiddenError: when ``role_template_id`` is ``emergency_root``.
        """
        if role_template_id == EMERGENCY_TEMPLATE_ID:
            metrics.increment("kyber_emergency_access_binding_refused_total")
            raise ForbiddenError(
                "emergency_root cannot be granted through role binding; it is "
                "reachable only through an approved emergency access request",
                details={"role_template_id": role_template_id},
            )

    # ── Internals ────────────────────────────────────────────────────────────

    @staticmethod
    async def _audit(
        *,
        actor_id: str,
        event_type: str,
        action: str,
        outcome: str,
        resource_id: Optional[str],
        metadata: dict[str, Any],
    ) -> None:
        """Write one critical emergency event to the shared audit ledger.

        Severity travels in ``metadata`` because the ledger's schema carries
        ``outcome`` rather than a severity column; alerting keys off
        ``event_type`` starting ``kyber.emergency.`` plus this marker.
        """
        from services.security.audit_ledger import audit_ledger

        await audit_ledger.record(
            actor_id=actor_id,
            actor_type=_ACTOR_TYPE,
            event_type=event_type,
            resource_type="kyber_emergency_access",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            tenant_id=PLATFORM_EMERGENCY_TENANT,
            resource_id=resource_id,
            metadata={
                "severity": "critical",
                "role_template_id": EMERGENCY_TEMPLATE_ID,
                "scope": EMERGENCY_SCOPE,
                **metadata,
            },
        )


#: Process-wide singleton.
emergency_access_service = EmergencyAccessService()


def assert_not_emergency_template(role_template_id: str) -> None:
    """Module-level alias of :meth:`EmergencyAccessService.assert_not_emergency_template`.

    Exposed as a plain function so the role-binding path can import one symbol
    rather than reach through the singleton.
    """
    EmergencyAccessService.assert_not_emergency_template(role_template_id)


__all__ = [
    "EMERGENCY_SCOPE",
    "EMERGENCY_TEMPLATE_ID",
    "EMERGENCY_WINDOW_HOURS",
    "EmergencyAccessService",
    "PLATFORM_EMERGENCY_TENANT",
    "assert_not_emergency_template",
    "emergency_access_service",
]
