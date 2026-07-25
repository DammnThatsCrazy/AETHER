"""Step-up elevation — the third Kyber session layer.

A step-up grant is a minutes-long proof that the human at the keyboard *right
now* re-asserted possession of the registered authenticator. It is what stands
between "someone is logged in on an approved laptop" and "unmasked raw tenant
evidence was read" or "a fleet kill switch was thrown".

Four properties make it worth having:

* **Bound to the session and the device.** A grant issued for one session on
  one device satisfies nothing else. Lifting a grant out of a captured session
  and replaying it elsewhere fails on the binding, not on luck.
* **Short and absolute.** Expiry comes from the role template's
  ``step_up_minutes`` and is never extended. Activity does not slide it — that
  is the difference between an elevation and a session.
* **Single-purpose when narrowed.** A grant may name the capability it was
  raised for. A grant taken for ``kyber.command.pause`` does not silently
  authorise ``kyber.tenant.raw.read``.
* **Consumable.** A consumed grant never satisfies a later check, so a
  high-impact command cannot be replayed against one elevation.

Granting requires a freshly verified authenticator assertion, checked through
the provider indirection. If the verification provider is unavailable the grant
is refused: a missing verifier is never treated as a passing verifier.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import BadRequestError, UnauthorizedError, parse_iso
from shared.logger.logger import get_logger, metrics
from shared.temporal.clock import SYSTEM_CLOCK, Clock

from ..access.contracts import DenialReason, StepUpGrant
from ..access.roles import ROLE_TEMPLATES
from .service import session_service

logger = get_logger("aether.kyber.step_up")

#: Hard bounds on an elevation, whatever a role template or caller asks for.
MIN_STEP_UP_MINUTES = 1
MAX_STEP_UP_MINUTES = 60

_DEFAULT_STEP_UP_MINUTES = 5


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parse_iso(value)
    except Exception:  # pragma: no cover - corrupt row, treated as expired
        return None


class StepUpGrantRepository(BaseRepository):
    """JSONB store for ``kyber_step_up_grants``."""

    def __init__(self) -> None:
        super().__init__("kyber_step_up_grants")


class StepUpService:
    """Issue, check, consume and revoke step-up elevations."""

    def __init__(
        self,
        repo: Optional[StepUpGrantRepository] = None,
        *,
        clock: Clock = SYSTEM_CLOCK,
    ) -> None:
        self._repo = repo or StepUpGrantRepository()
        self._clock = clock

    def set_clock(self, clock: Clock) -> None:
        """Swap the clock. Tests use this instead of sleeping."""
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock.now()

    # ── Lifetime resolution ──────────────────────────────────────────────────

    async def default_ttl_minutes(self, operator_id: str, environment: str) -> int:
        """The step-up lifetime for a principal, from their role templates.

        The shortest template wins, so holding a long-lived template alongside
        a break-glass one does not lengthen break-glass elevations.
        """
        from ..access.dependencies import get_providers

        principals = get_providers().principals
        template_ids: list[str] = []
        if principals is not None:
            try:
                template_ids = list(
                    await principals.role_template_ids(operator_id, environment=environment)
                )
            except Exception as exc:  # pragma: no cover - provider failure
                logger.warning(f"kyber: step-up ttl lookup failed operator={operator_id}: {exc}")
        minutes = [
            ROLE_TEMPLATES[t].step_up_minutes for t in template_ids if t in ROLE_TEMPLATES
        ]
        return min(minutes) if minutes else _DEFAULT_STEP_UP_MINUTES

    @staticmethod
    def _clamp(minutes: int) -> int:
        return max(MIN_STEP_UP_MINUTES, min(MAX_STEP_UP_MINUTES, int(minutes)))

    # ── Challenge / verification ─────────────────────────────────────────────

    async def issue_challenge(self, *, device_id: str) -> tuple[str, str]:
        """Ask the device plane for a fresh assertion challenge.

        Returns ``(challenge_id, challenge)``. Raises when the verification
        provider is unavailable — no provider means no elevation.
        """
        from ..access.dependencies import get_providers

        proof = get_providers().proof
        if proof is None:
            raise UnauthorizedError("Step-up is unavailable: device proof provider not loaded")
        return await proof.issue_challenge(device_id=device_id)

    async def _verify(self, *, device_id: str, challenge_id: str, signature_b64: str) -> bool:
        from ..access.dependencies import get_providers

        proof = get_providers().proof
        if proof is None:
            return False
        try:
            return bool(
                await proof.verify_proof(
                    device_id=device_id,
                    challenge_id=challenge_id,
                    signature_b64=signature_b64,
                )
            )
        except Exception as exc:  # pragma: no cover - provider failure is not proof
            logger.warning(f"kyber: step-up proof verification failed device={device_id}: {exc}")
            return False

    # ── Grants ───────────────────────────────────────────────────────────────

    async def grant(
        self,
        *,
        session_id: str,
        operator_id: str,
        device_id: Optional[str],
        capability_id: Optional[str] = None,
        reason: Optional[str] = None,
        ttl_minutes: Optional[int] = None,
        challenge_id: Optional[str] = None,
        signature_b64: Optional[str] = None,
    ) -> StepUpGrant:
        """Issue an elevation after verifying a fresh authenticator assertion.

        ``challenge_id`` and ``signature_b64`` are required: this method refuses
        to mint a grant it did not itself see verified. The session is promoted
        to ``stepped_up`` and its handle rotated as a side effect.
        """
        session = await session_service.get(session_id)
        if session is None:
            raise UnauthorizedError("Unknown Kyber session")
        if session.status in ("revoked", "expired"):
            raise UnauthorizedError("Kyber session is not live")
        if session.operator_id != operator_id:
            raise UnauthorizedError("Step-up operator does not match the session")

        bound_device = device_id or session.device_id
        if not bound_device:
            raise UnauthorizedError("Step-up requires a device-bound session")
        if session.device_id and bound_device != session.device_id:
            metrics.increment("kyber_auth_failure_total", labels={"reason": "device_mismatch"})
            raise UnauthorizedError("Step-up device does not match the session binding")

        if not challenge_id or not signature_b64:
            raise BadRequestError("Step-up requires a fresh authenticator assertion")

        verified = await self._verify(
            device_id=bound_device, challenge_id=challenge_id, signature_b64=signature_b64
        )
        if not verified:
            metrics.increment("kyber_auth_failure_total", labels={"reason": "device_proof_invalid"})
            await self._record_failure(session_id, operator_id, bound_device, capability_id)
            raise UnauthorizedError("Authenticator assertion did not verify")

        ttl = self._clamp(
            ttl_minutes
            if ttl_minutes is not None
            else await self.default_ttl_minutes(operator_id, session.environment)
        )
        now = self._now()
        expires_at = (now + timedelta(minutes=ttl)).isoformat()

        grant = StepUpGrant(
            session_id=session_id,
            operator_id=operator_id,
            device_id=bound_device,
            capability_id=capability_id,
            reason=reason,
            created_at=now.isoformat(),
            expires_at=expires_at,
        )
        await self._repo.insert(grant.grant_id, grant.model_dump())

        await session_service.apply_step_up(
            session_id, expires_at=expires_at, capability_id=capability_id
        )

        metrics.increment(
            "kyber_auth_success_total", labels={"strength": "stepped_up"}
        )
        await self._audit(grant, outcome="allowed")
        logger.info(
            f"kyber: step-up granted session={session_id} capability={capability_id} ttl={ttl}m"
        )
        return grant

    async def grant_and_rotate(self, **kwargs: Any) -> tuple[StepUpGrant, str]:
        """Grant an elevation and rotate the session handle.

        Returns ``(grant, raw_token)``. Rotating on elevation is what stops a
        handle captured before the step-up from riding it; the raw token is
        returned so the caller can put the new cookie on the response, which is
        why rotation is not buried inside :meth:`grant`.
        """
        grant = await self.grant(**kwargs)
        _session, raw_token = await session_service.rotate(
            grant.session_id, reason="step_up"
        )
        return grant, raw_token

    async def _record_failure(
        self,
        session_id: str,
        operator_id: str,
        device_id: Optional[str],
        capability_id: Optional[str],
    ) -> None:
        from services.security.audit_ledger import audit_ledger

        await audit_ledger.record(
            actor_id=operator_id,
            actor_type="olympus_operator",
            event_type="kyber.step_up.failed",
            resource_type="kyber_step_up",
            action="grant",
            outcome="failed",
            resource_id=session_id,
            metadata={"device_id": device_id, "capability_id": capability_id},
        )

    async def _audit(self, grant: StepUpGrant, *, outcome: str) -> None:
        from services.security.audit_ledger import audit_ledger

        await audit_ledger.record(
            actor_id=grant.operator_id,
            actor_type="olympus_operator",
            event_type="kyber.step_up.granted",
            resource_type="kyber_step_up",
            action="grant",
            outcome=outcome,  # type: ignore[arg-type]
            resource_id=grant.grant_id,
            metadata={
                "session_id": grant.session_id,
                "device_id": grant.device_id,
                "capability_id": grant.capability_id,
                "expires_at": grant.expires_at,
                "reason": grant.reason,
            },
        )

    # ── Checks ───────────────────────────────────────────────────────────────

    def _is_live(self, grant: StepUpGrant, now: datetime) -> bool:
        if grant.revoked_at or grant.consumed_at:
            return False
        expires = _parse(grant.expires_at)
        return expires is not None and now < expires

    async def active_grant(
        self, session_id: str, *, capability_id: Optional[str] = None
    ) -> Optional[StepUpGrant]:
        """The live elevation for a session, or ``None``.

        A grant narrowed to a capability only satisfies that capability; a
        grant with no capability is a general elevation and satisfies any
        check. The device binding is re-checked against the session on every
        lookup, so a device revoked since the grant was taken invalidates it.
        """
        session = await session_service.get(session_id)
        if session is None or session.status in ("revoked", "expired"):
            return None

        now = self._now()
        rows = await self._repo.find_many({"session_id": session_id}, limit=100)
        best: Optional[StepUpGrant] = None
        for row in rows:
            grant = StepUpGrant(**row)
            if not self._is_live(grant, now):
                continue
            if session.device_id and grant.device_id and grant.device_id != session.device_id:
                continue
            if capability_id is not None and grant.capability_id not in (None, capability_id):
                continue
            if best is None or grant.expires_at > best.expires_at:
                best = grant
        return best

    async def require_fresh(
        self, session_id: str, *, capability_id: Optional[str] = None
    ) -> tuple[bool, Optional[DenialReason]]:
        """Whether a live elevation covers this session (and capability).

        Returns ``(True, None)`` or ``(False, "step_up_required")``. There is
        no third outcome: any reason an elevation is unusable — expired,
        consumed, revoked, wrong device, wrong capability, absent — reads the
        same to the caller, so the response cannot be used to probe state.
        """
        grant = await self.active_grant(session_id, capability_id=capability_id)
        if grant is None:
            return False, "step_up_required"
        return True, None

    async def consume(self, grant_id: str) -> Optional[StepUpGrant]:
        """Burn a grant so it cannot satisfy a second check."""
        row = await self._repo.find_by_id(grant_id)
        if row is None:
            return None
        grant = StepUpGrant(**row)
        if grant.consumed_at:
            return grant
        grant.consumed_at = self._now().isoformat()
        await self._repo.update(grant_id, grant.model_dump())
        return grant

    async def revoke_for_session(self, session_id: str) -> int:
        """Revoke every elevation on a session. Returns the count revoked."""
        now = self._now().isoformat()
        rows = await self._repo.find_many({"session_id": session_id}, limit=500)
        revoked = 0
        for row in rows:
            grant = StepUpGrant(**row)
            if grant.revoked_at:
                continue
            grant.revoked_at = now
            await self._repo.update(grant.grant_id, grant.model_dump())
            revoked += 1
        if revoked:
            await session_service.clear_step_up(session_id)
        return revoked

    async def list_for_session(self, session_id: str) -> list[StepUpGrant]:
        """Every grant recorded against a session, newest first."""
        rows = await self._repo.find_many({"session_id": session_id}, limit=200)
        return [StepUpGrant(**row) for row in rows]

    async def describe(self, session_id: str) -> dict[str, Any]:
        """Body-safe elevation state for the session endpoint."""
        grant = await self.active_grant(session_id)
        return {
            "stepped_up": grant is not None,
            "step_up_expires_at": grant.expires_at if grant else None,
            "step_up_capability_id": grant.capability_id if grant else None,
        }


#: Process-wide singleton.
step_up_service = StepUpService()

__all__ = [
    "MAX_STEP_UP_MINUTES",
    "MIN_STEP_UP_MINUTES",
    "StepUpGrantRepository",
    "StepUpService",
    "step_up_service",
]
