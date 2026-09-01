"""Purpose-bound tenant access scopes.

Reading one tenant's data is not a permission an operator holds standing; it is
an action they take, for a stated reason, for a bounded time, on one tenant.
A scope is that action made durable.

This replaces an in-process dictionary keyed by operator id. That dictionary
had five defects, each of which is a property asserted here instead:

============================  ==========================================
Previous behaviour            Behaviour now
============================  ==========================================
Lost on restart / per worker  Persisted in ``kyber_access_scopes``
Bound to the operator only    Bound to the session **and** the device
Implicitly re-scoped          Exactly one tenant; a mismatch is a denial
No expiry                     TTL of 1..480 minutes, swept and enforced
Entry logged, exit not        Open, exit, expiry and revoke are audited
============================  ==========================================

The tenant-mismatch rule deserves emphasis. When a request names tenant *B*
while the live scope names tenant *A*, the request is **denied**. It is not
silently re-scoped to *B*, and *A*'s scope is not quietly widened. Anything
else would mean a client-supplied identifier could redirect authority, which is
the exact failure this module exists to prevent.

A session holds at most one active scope. Opening another closes the previous
one first, so "which tenant is this operator looking at" always has one answer
and the transition is in the ledger.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional, get_args

from repositories.repos import BaseRepository
from shared.common.common import BadRequestError, parse_iso
from shared.logger.logger import get_logger, metrics
from shared.temporal.clock import SYSTEM_CLOCK, Clock

from .contracts import AccessScope, AccessScopePurpose, DenialReason
from .disclosure import DisclosureLevel

logger = get_logger("aether.kyber.scopes")

#: TTL bounds. A scope shorter than a minute is unusable; one longer than eight
#: hours is a standing grant wearing a scope's clothes.
MIN_SCOPE_MINUTES = 1
MAX_SCOPE_MINUTES = 480
DEFAULT_SCOPE_MINUTES = 60

#: The existing tenant-entry endpoint required a reason of at least this
#: length. Keeping it means the audit trail keeps carrying an actual sentence
#: rather than "." — the ledger is only as useful as the reasons in it.
MIN_REASON_LENGTH = 10

VALID_PURPOSES: frozenset[str] = frozenset(get_args(AccessScopePurpose))

_CLOSED_STATUSES: frozenset[str] = frozenset({"expired", "exited", "revoked"})


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parse_iso(value)
    except Exception:  # pragma: no cover - corrupt row, treated as expired
        return None


class AccessScopeRepository(BaseRepository):
    """JSONB store for ``kyber_access_scopes``."""

    def __init__(self) -> None:
        super().__init__("kyber_access_scopes")


class AccessScopeService:
    """Open, resolve, close and sweep purpose-bound tenant scopes."""

    def __init__(
        self,
        repo: Optional[AccessScopeRepository] = None,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        self._repo = repo or AccessScopeRepository()
        self._clock = clock

    def set_clock(self, clock: Clock) -> None:
        """Swap the clock. Tests use this instead of sleeping."""
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock.now()

    # ── Validation helpers ───────────────────────────────────────────────────

    @staticmethod
    def _clamp_ttl(minutes: Optional[int]) -> int:
        if minutes is None:
            return DEFAULT_SCOPE_MINUTES
        return max(MIN_SCOPE_MINUTES, min(MAX_SCOPE_MINUTES, int(minutes)))

    @staticmethod
    def _validate_reason(reason: str) -> str:
        cleaned = (reason or "").strip()
        if len(cleaned) < MIN_REASON_LENGTH:
            raise BadRequestError(
                f"A tenant access reason must be at least {MIN_REASON_LENGTH} characters"
            )
        return cleaned

    @staticmethod
    def _validate_purpose(purpose: str) -> str:
        if purpose not in VALID_PURPOSES:
            raise BadRequestError(f"Unknown tenant access purpose: {purpose!r}")
        return purpose

    @staticmethod
    def _to_model(row: dict) -> AccessScope:
        return AccessScope(**row)

    # ── Opening ──────────────────────────────────────────────────────────────

    async def open_scope(
        self,
        *,
        operator_id: str,
        session_id: str,
        device_id: Optional[str],
        environment: str,
        tenant_id: str,
        purpose: str,
        reason: str,
        ticket_reference: Optional[str] = None,
        disclosure_level: "DisclosureLevel | int | str" = DisclosureLevel.D3_TENANT_VISIBLE,
        ttl_minutes: Optional[int] = None,
        policy_decision_id: Optional[str] = None,
        rights_envelope_ref: Optional[str] = None,
    ) -> AccessScope:
        """Open a scope on exactly one tenant, closing any previous one.

        The scope records the session and device that opened it, so a handle
        replayed from another machine cannot ride it, and the ceiling it
        carries becomes one more input to the disclosure minimum — a scope can
        lower what a role could otherwise see, never raise it.
        """
        if not tenant_id:
            raise BadRequestError("A tenant access scope must name a tenant")
        from shared.rights_authority.pep import rights_mode
        if rights_mode() != "off" and not (ticket_reference or "").strip():
            raise BadRequestError(
                "a rights-enforced Kyber scope requires a case/ticket reference"
            )

        purpose = self._validate_purpose(purpose)
        reason = self._validate_reason(reason)
        ttl = self._clamp_ttl(ttl_minutes)
        level = DisclosureLevel.parse(disclosure_level)
        now = self._now()

        previous = await self.current_scope(session_id)
        if previous is not None:
            await self._close(
                previous,
                status="exited",
                actor_id=operator_id,
                reason=f"superseded by a new scope on tenant {tenant_id}",
            )

        scope = AccessScope(
            operator_id=operator_id,
            session_id=session_id,
            device_id=device_id,
            environment=environment,
            tenant_id=tenant_id,
            purpose=purpose,  # type: ignore[arg-type]
            reason=reason,
            ticket_reference=ticket_reference,
            disclosure_level=int(level),
            status="active",
            entered_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=ttl)).isoformat(),
            policy_decision_id=policy_decision_id,
            rights_envelope_ref=rights_envelope_ref,
            metadata={"ttl_minutes": ttl, "superseded": previous.scope_id if previous else None},
        )
        await self._repo.insert(scope.scope_id, scope.model_dump())

        await self._emit_active_gauge()
        await self._audit(scope, action="open", outcome="allowed")
        logger.info(
            f"kyber: scope opened id={scope.scope_id} operator={operator_id} "
            f"tenant={tenant_id} purpose={purpose} ttl={ttl}m d={int(level)}"
        )
        return scope

    # ── Resolution ───────────────────────────────────────────────────────────

    async def get(self, scope_id: str) -> Optional[AccessScope]:
        """Load one scope by id."""
        row = await self._repo.find_by_id(scope_id)
        return self._to_model(row) if row else None

    async def current_scope(self, session_id: str) -> Optional[AccessScope]:
        """The session's live scope, or ``None``.

        Expiry is applied lazily here as well as by the sweep, so a scope is
        never returned as live merely because the sweep has not run yet.
        """
        now = self._now()
        rows = await self._repo.find_many({"session_id": session_id, "status": "active"}, limit=50)
        newest: Optional[AccessScope] = None
        for row in rows:
            scope = self._to_model(row)
            expires = _parse(scope.expires_at)
            if expires is None or now >= expires:
                await self._close(scope, status="expired", actor_id="system", reason="ttl elapsed")
                continue
            if newest is None or scope.entered_at > newest.entered_at:
                newest = scope
        return newest

    async def resolve_for_tenant(
        self, session_id: str, tenant_id: str
    ) -> tuple[Optional[AccessScope], Optional[DenialReason]]:
        """Resolve the scope authorising this session to read ``tenant_id``.

        Returns ``(scope, None)`` or ``(None, reason)`` where reason is one of
        ``scope_missing``, ``scope_expired`` or ``scope_tenant_mismatch``.

        The mismatch branch is deliberately a denial. A request that names a
        different tenant than the open scope is either a bug or an attempt to
        pivot; either way the answer is no, and the scope is left exactly as it
        was.
        """
        now = self._now()
        rows = await self._repo.find_many({"session_id": session_id}, limit=200)
        if not rows:
            return None, "scope_missing"

        saw_expired = False
        for row in sorted(rows, key=lambda r: r.get("entered_at", ""), reverse=True):
            scope = self._to_model(row)
            if scope.status != "active":
                if scope.status == "expired" and scope.tenant_id == tenant_id:
                    saw_expired = True
                continue
            expires = _parse(scope.expires_at)
            if expires is None or now >= expires:
                await self._close(scope, status="expired", actor_id="system", reason="ttl elapsed")
                if scope.tenant_id == tenant_id:
                    saw_expired = True
                continue
            if scope.tenant_id != tenant_id:
                logger.warning(
                    f"kyber: scope tenant mismatch session={session_id} "
                    f"scope_tenant={scope.tenant_id} requested_tenant={tenant_id}"
                )
                return None, "scope_tenant_mismatch"
            return scope, None

        return None, ("scope_expired" if saw_expired else "scope_missing")

    async def list_scopes(
        self,
        *,
        operator_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[AccessScope]:
        """List scopes, newest first, optionally narrowed and active-only."""
        filters: dict[str, Any] = {}
        if operator_id:
            filters["operator_id"] = operator_id
        if tenant_id:
            filters["tenant_id"] = tenant_id
        if active_only:
            filters["status"] = "active"

        now = self._now()
        out: list[AccessScope] = []
        for row in await self._repo.find_many(filters, limit=max(limit, 1) * 2):
            scope = self._to_model(row)
            if active_only:
                expires = _parse(scope.expires_at)
                if expires is None or now >= expires:
                    await self._close(
                        scope, status="expired", actor_id="system", reason="ttl elapsed"
                    )
                    continue
            out.append(scope)
        out.sort(key=lambda s: s.entered_at, reverse=True)
        return out[:limit]

    # ── Closing ──────────────────────────────────────────────────────────────

    async def _close(
        self, scope: AccessScope, *, status: str, actor_id: str, reason: Optional[str]
    ) -> AccessScope:
        if scope.status in _CLOSED_STATUSES:
            return scope
        now = self._now().isoformat()
        scope.status = status  # type: ignore[assignment]
        if status == "revoked":
            scope.revoked_at = now
        else:
            scope.exited_at = now
        if reason:
            scope.metadata = {**scope.metadata, "close_reason": reason}
        await self._repo.update(scope.scope_id, scope.model_dump())

        await self._emit_active_gauge()
        await self._audit(
            scope,
            action=status,
            outcome="allowed" if status == "exited" else "blocked",
            actor_id=actor_id,
            reason=reason,
        )
        logger.info(f"kyber: scope {status} id={scope.scope_id} actor={actor_id}")
        return scope

    async def exit_scope(self, scope_id: str, *, actor_id: str) -> Optional[AccessScope]:
        """Close a scope deliberately. Idempotent."""
        scope = await self.get(scope_id)
        if scope is None:
            return None
        return await self._close(
            scope, status="exited", actor_id=actor_id, reason="operator exited the scope"
        )

    async def _revoke_matching(self, filters: dict[str, Any], reason: str) -> int:
        rows = await self._repo.find_many({**filters, "status": "active"}, limit=1000)
        revoked = 0
        for row in rows:
            await self._close(self._to_model(row), status="revoked", actor_id="system", reason=reason)
            revoked += 1
        return revoked

    async def revoke_for_session(self, session_id: str, *, reason: str) -> int:
        """Close every scope a session holds. Returns the count revoked."""
        return await self._revoke_matching({"session_id": session_id}, reason)

    async def revoke_for_operator(self, operator_id: str, *, reason: str) -> int:
        """Close every scope a principal holds. Returns the count revoked.

        Called when a principal is suspended or offboarded: an open scope is
        live authorization to read a tenant and must not outlive the identity
        that opened it.
        """
        return await self._revoke_matching({"operator_id": operator_id}, reason)

    async def expire_due(self) -> int:
        """Close scopes whose TTL has elapsed. Returns the count expired."""
        now = self._now()
        expired = 0
        for row in await self._repo.find_many({"status": "active"}, limit=1000):
            scope = self._to_model(row)
            expires = _parse(scope.expires_at)
            if expires is None or now >= expires:
                await self._close(scope, status="expired", actor_id="system", reason="ttl elapsed")
                expired += 1
        return expired

    # ── Observability ────────────────────────────────────────────────────────

    async def _emit_active_gauge(self) -> None:
        try:
            active = await self._repo.count({"status": "active"})
            metrics.gauge("kyber_scope_active", float(active))
        except Exception:  # pragma: no cover - metrics are never load-bearing
            pass

    async def _audit(
        self,
        scope: AccessScope,
        *,
        action: str,
        outcome: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        from services.security.audit_ledger import audit_ledger

        await audit_ledger.record(
            actor_id=actor_id or scope.operator_id,
            actor_type="olympus_operator",
            event_type=f"kyber.scope.{action}",
            resource_type="kyber_access_scope",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            tenant_id=scope.tenant_id,
            resource_id=scope.scope_id,
            policy_decision_id=scope.policy_decision_id,
            metadata={
                "session_id": scope.session_id,
                "device_id": scope.device_id,
                "purpose": scope.purpose,
                "reason": reason or scope.reason,
                "ticket_reference": scope.ticket_reference,
                "disclosure_level": scope.disclosure_level,
                "expires_at": scope.expires_at,
                "environment": scope.environment,
            },
        )


#: Process-wide singleton.
access_scope_service = AccessScopeService()

__all__ = [
    "DEFAULT_SCOPE_MINUTES",
    "MAX_SCOPE_MINUTES",
    "MIN_REASON_LENGTH",
    "MIN_SCOPE_MINUTES",
    "VALID_PURPOSES",
    "AccessScopeRepository",
    "AccessScopeService",
    "access_scope_service",
]
