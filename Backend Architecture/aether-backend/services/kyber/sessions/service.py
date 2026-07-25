"""Durable, revocable Kyber workforce sessions.

Kyber runs four authority layers over one session row. They are not four
tokens: one opaque handle is presented, and what it is worth depends on which
windows are still open.

1. **Presence** — up to the role template's ``presence_minutes``. Opens the
   console and shows low-risk aggregate health. No tenant detail, no evidence,
   no commands, no exports, no workforce administration. A presence session is
   ``restricted``; every authority route refuses it.
2. **Operator authority** — ``session_absolute_minutes`` is a hard ceiling that
   continuous activity cannot extend, and ``session_idle_minutes`` is a
   *sliding* inactivity window that closes an unattended console early.
3. **Step-up** — a minutes-long elevation proving a fresh authenticator
   assertion. Lives in :mod:`services.kyber.sessions.step_up`.
4. **Device registration** — a days-long trust decision about the machine,
   owned by the device plane, not by this module.

Two properties are worth stating outright because the previous session
implementation in this repository got them wrong.

*The idle window slides.* ``services/auth/sessions/service.py`` sets
``idle_expires_at`` at creation and never moves it, so its "idle" timeout is in
practice a second absolute cap and an actively-used session dies mid-work.
Here :meth:`KyberSessionService.validate` pushes ``idle_expires_at`` forward on
every successful use, clamped by the absolute ceiling — so an idle console
closes, an active one does not, and neither outlives the hard ceiling.

*The raw handle exists once.* Only ``sha256(token)`` is stored. The raw value
is returned by :meth:`create_session` and :meth:`rotate` and never again — not
in a log line, not in a response body, not in an audit record.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import parse_iso
from shared.logger.logger import get_logger, metrics
from shared.temporal.clock import SYSTEM_CLOCK, Clock

from ..access.contracts import (
    AuthenticationEvent,
    AuthenticationMethod,
    AuthenticationStrength,
    DenialReason,
    SessionStatus,
    WorkforceSession,
)
from ..access.roles import ROLE_TEMPLATES
from .cookies import SESSION_TOKEN_PREFIX, hash_csrf_token, issue_csrf_token

logger = get_logger("aether.kyber.sessions")

#: Bytes of entropy in a session handle. 24 bytes → 48 hex characters, matching
#: the opaque-token precedent already used by the tenant session service.
_TOKEN_BYTES = 24

#: Applied when no role template can be resolved — the shortest windows any
#: template defines, so an unresolvable principal gets the least session we
#: know how to issue rather than a generous default.
_FALLBACK_LIFETIME = {
    "absolute_minutes": 15,
    "idle_minutes": 15,
    "presence_minutes": 0,
    "step_up_minutes": 5,
}

#: The factors an authority session must present. Anything less is presence.
_AUTHORITY_METHODS = frozenset({"google_oidc", "webauthn", "device_proof"})

_TERMINAL_STATUSES: frozenset[str] = frozenset({"revoked", "expired"})


def hash_token(raw: str) -> str:
    """sha256 of a raw session handle, hex encoded. The only stored form."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mint_token() -> tuple[str, str]:
    raw = f"{SESSION_TOKEN_PREFIX}{secrets.token_hex(_TOKEN_BYTES)}"
    return raw, hash_token(raw)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parse_iso(value)
    except Exception:  # pragma: no cover - corrupt row, treated as expired
        return None


class KyberSessionRepository(BaseRepository):
    """JSONB store for ``kyber_workforce_sessions``."""

    def __init__(self) -> None:
        super().__init__("kyber_workforce_sessions")


class KyberAuthenticationEventRepository(BaseRepository):
    """Append-only store for ``kyber_authentication_events``."""

    def __init__(self) -> None:
        super().__init__("kyber_authentication_events")


class KyberSessionService:
    """Create, validate, slide, rotate and revoke Kyber sessions."""

    def __init__(
        self,
        repo: Optional[KyberSessionRepository] = None,
        *,
        clock: Clock = SYSTEM_CLOCK,
        events: Optional[KyberAuthenticationEventRepository] = None,
    ) -> None:
        self._repo = repo or KyberSessionRepository()
        self._events = events or KyberAuthenticationEventRepository()
        self._clock = clock

    # ── Test / deployment seams ──────────────────────────────────────────────

    @property
    def clock(self) -> Clock:
        return self._clock

    def set_clock(self, clock: Clock) -> None:
        """Swap the clock. Tests use this instead of sleeping."""
        self._clock = clock

    def _now(self) -> datetime:
        return self._clock.now()

    # ── Lifetimes ────────────────────────────────────────────────────────────

    async def _lifetimes(self, operator_id: str, environment: str) -> tuple[dict[str, int], list[str]]:
        """Resolve session windows from the principal's role templates.

        Multiple templates compose to the **most restrictive** window, not the
        most generous: holding a break-glass template alongside a working one
        must not silently extend the break-glass session. When no template
        resolves — including when the identity provider is unavailable — the
        fallback is the shortest window Kyber defines.
        """
        template_ids = await self._role_template_ids(operator_id, environment)
        templates = [ROLE_TEMPLATES[t] for t in template_ids if t in ROLE_TEMPLATES]
        if not templates:
            return dict(_FALLBACK_LIFETIME), list(template_ids)
        return (
            {
                "absolute_minutes": min(t.session_absolute_minutes for t in templates),
                "idle_minutes": min(t.session_idle_minutes for t in templates),
                "presence_minutes": min(t.presence_minutes for t in templates),
                "step_up_minutes": min(t.step_up_minutes for t in templates),
            },
            list(template_ids),
        )

    async def _role_template_ids(self, operator_id: str, environment: str) -> list[str]:
        from ..access.dependencies import get_providers  # local: avoids an import cycle

        principals = get_providers().principals
        if principals is None:
            return []
        try:
            return list(await principals.role_template_ids(operator_id, environment=environment))
        except Exception as exc:  # pragma: no cover - provider failure is not authority
            logger.warning(f"kyber: role template lookup failed operator={operator_id}: {exc}")
            return []

    async def _device_usable(self, device_id: Optional[str]) -> bool:
        if not device_id:
            return False
        from ..access.dependencies import get_providers  # local: avoids an import cycle

        devices = get_providers().devices
        if devices is None:
            return False
        try:
            usable, _reason = await devices.is_usable(device_id)
            return bool(usable)
        except Exception as exc:  # pragma: no cover - provider failure is not authority
            logger.warning(f"kyber: device usability check failed device={device_id}: {exc}")
            return False

    @staticmethod
    def _derive_strength(
        methods: list[AuthenticationMethod], *, device_usable: bool
    ) -> tuple[AuthenticationStrength, SessionStatus]:
        """Derive the strength band. Never supplied by the caller.

        A caller that claims ``device_bound`` without having presented a device
        proof on an approved device gets ``identity_only`` regardless of what
        it asked for, because this function only reads the factors that were
        actually verified.
        """
        presented = frozenset(methods)
        if _AUTHORITY_METHODS <= presented and device_usable:
            return "device_bound", "active"
        if "google_oidc" in presented:
            return "identity_only", "restricted"
        return "none", "restricted"

    # ── Persistence helpers ──────────────────────────────────────────────────

    @staticmethod
    def _to_model(row: Optional[dict]) -> Optional[WorkforceSession]:
        if row is None:
            return None
        return WorkforceSession(**row)

    async def _save(self, session: WorkforceSession) -> WorkforceSession:
        await self._repo.update(session.session_id, session.model_dump())
        return session

    async def get(self, session_id: str) -> Optional[WorkforceSession]:
        """Load one session by id."""
        return self._to_model(await self._repo.find_by_id(session_id))

    async def _by_token_hash(self, token_hash: str) -> Optional[WorkforceSession]:
        rows = await self._repo.find_many({"token_hash": token_hash}, limit=2)
        if not rows:
            return None
        return self._to_model(rows[0])

    async def _record_event(
        self,
        *,
        event_type: str,
        session: Optional[WorkforceSession] = None,
        operator_id: Optional[str] = None,
        outcome: str = "succeeded",
        reason: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        event = AuthenticationEvent(
            event_type=event_type,  # type: ignore[arg-type]
            operator_id=operator_id or (session.operator_id if session else None),
            google_subject=session.google_subject if session else None,
            session_id=session.session_id if session else None,
            device_id=session.device_id if session else None,
            environment=session.environment if session else None,
            outcome=outcome,  # type: ignore[arg-type]
            reason=reason,
            client_ip=client_ip,
            user_agent=user_agent,
            metadata=metadata or {},
        )
        await self._events.insert(event.event_id, event.model_dump())

    async def _audit(
        self,
        *,
        session: WorkforceSession,
        action: str,
        outcome: str,
        reason: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        from services.security.audit_ledger import audit_ledger

        payload = {"session_status": session.status, "environment": session.environment}
        if reason:
            payload["reason"] = reason
        payload.update(metadata or {})
        await audit_ledger.record(
            actor_id=session.operator_id,
            actor_type="olympus_operator",
            event_type=f"kyber.session.{action}",
            resource_type="kyber_session",
            action=action,
            outcome=outcome,  # type: ignore[arg-type]
            resource_id=session.session_id,
            ip_address=session.client_ip,
            user_agent=session.user_agent,
            metadata=payload,
        )

    async def _emit_active_gauge(self) -> None:
        try:
            active = await self._repo.count({"status": "active"})
            metrics.gauge("kyber_session_active", float(active))
        except Exception:  # pragma: no cover - metrics are never load-bearing
            pass

    # ── Creation ─────────────────────────────────────────────────────────────

    async def create_session(
        self,
        *,
        operator_id: str,
        google_subject: Optional[str],
        device_id: Optional[str],
        environment: str,
        authentication_methods: list[AuthenticationMethod],
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> tuple[WorkforceSession, str]:
        """Open a session. Returns ``(session, raw_token)``.

        The raw handle is returned here and nowhere else. The strength band and
        status are derived from the factors actually presented plus the live
        device state — a caller cannot assert its own authority.
        """
        now = self._now()
        lifetimes, template_ids = await self._lifetimes(operator_id, environment)
        device_usable = await self._device_usable(device_id)
        strength, status = self._derive_strength(authentication_methods, device_usable=device_usable)

        raw_token, token_hash = _mint_token()
        _csrf_raw, csrf_hash = issue_csrf_token()

        session = WorkforceSession(
            token_hash=token_hash,
            operator_id=operator_id,
            google_subject=google_subject,
            device_id=device_id,
            status=status,
            authentication_methods=list(authentication_methods),
            authentication_strength=strength,
            environment=environment,
            presence_expires_at=_iso(now + timedelta(minutes=lifetimes["presence_minutes"])),
            authority_expires_at=_iso(now + timedelta(minutes=lifetimes["absolute_minutes"])),
            idle_expires_at=_iso(now + timedelta(minutes=lifetimes["idle_minutes"])),
            created_at=_iso(now),
            last_seen_at=_iso(now),
            csrf_token_hash=csrf_hash,
            client_ip=client_ip,
            user_agent=user_agent,
            metadata={
                **lifetimes,
                "role_template_ids": template_ids,
                "device_usable_at_creation": device_usable,
            },
        )
        await self._repo.insert(session.session_id, session.model_dump())

        metrics.increment("kyber_auth_success_total", labels={"strength": strength})
        await self._emit_active_gauge()
        await self._record_event(
            event_type="session_created",
            session=session,
            client_ip=client_ip,
            user_agent=user_agent,
            metadata={"strength": strength, "role_template_ids": template_ids},
        )
        await self._audit(
            session=session,
            action="create",
            outcome="allowed",
            metadata={"strength": strength, "role_template_ids": template_ids},
        )
        logger.info(
            f"kyber: session opened id={session.session_id} operator={operator_id} "
            f"strength={strength} status={status}"
        )
        return session, raw_token

    async def issue_csrf_token(self, session_id: str) -> Optional[str]:
        """Mint (and store the digest of) a fresh CSRF token for a session.

        Returns the raw token once, for the response body. Rotating the CSRF
        token independently of the session handle lets a long-lived console tab
        refresh it without disturbing the session.
        """
        session = await self.get(session_id)
        if session is None:
            return None
        raw, digest = issue_csrf_token()
        session.csrf_token_hash = digest
        await self._save(session)
        return raw

    def verify_csrf(self, session: WorkforceSession, raw_token: Optional[str]) -> bool:
        """Compare an echoed CSRF token against the digest stored on a session."""
        if not raw_token or not session.csrf_token_hash:
            return False
        return secrets.compare_digest(hash_csrf_token(raw_token), session.csrf_token_hash)

    # ── Validation ───────────────────────────────────────────────────────────

    def _governing_absolute(self, session: WorkforceSession) -> Optional[datetime]:
        """The hard ceiling that applies to this session's current layer.

        A ``restricted`` session is a presence session and is bounded by
        ``presence_expires_at``; an authority session is bounded by
        ``authority_expires_at``. Authority never silently degrades into
        presence when its ceiling passes — the operator re-authenticates.
        """
        if session.status == "restricted":
            return _parse(session.presence_expires_at)
        return _parse(session.authority_expires_at)

    async def validate(
        self,
        raw_token: str,
        *,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> tuple[Optional[WorkforceSession], Optional[DenialReason]]:
        """Resolve a raw handle to a live session.

        Checks run in a fixed order — unknown, revoked, absolute, idle, device
        binding, then restricted — and the first failure is returned as its
        ``DenialReason``. A ``restricted`` session is returned *with* the
        ``session_restricted`` reason so presence-only routes can still serve
        it while every authority route refuses.

        On success the idle window slides forward (clamped by the absolute
        ceiling) and ``last_seen_at`` is stamped.

        ``device_id``, when supplied, is the device the *request* proved. A
        mismatch against the session's binding is a stolen-handle replay and is
        denied with ``device_mismatch``.
        """
        if not raw_token:
            return None, "no_session"

        session = await self._by_token_hash(hash_token(raw_token))
        if session is None:
            metrics.increment("kyber_auth_failure_total", labels={"reason": "no_session"})
            return None, "no_session"

        if session.revoked_at or session.status == "revoked":
            metrics.increment("kyber_auth_failure_total", labels={"reason": "session_revoked"})
            return None, "session_revoked"

        now = self._now()

        if session.status == "expired":
            return None, "session_expired"

        absolute = self._governing_absolute(session)
        if absolute is None or now >= absolute:
            await self._mark_expired(session, reason="absolute_expiry")
            metrics.increment("kyber_auth_failure_total", labels={"reason": "session_expired"})
            return None, "session_expired"

        idle = _parse(session.idle_expires_at)
        if idle is None or now >= idle:
            await self._mark_expired(session, reason="idle_expiry")
            metrics.increment("kyber_auth_failure_total", labels={"reason": "session_expired"})
            return None, "session_expired"

        if device_id is not None and session.device_id and device_id != session.device_id:
            metrics.increment("kyber_auth_failure_total", labels={"reason": "device_mismatch"})
            await self._record_event(
                event_type="login_failed",
                session=session,
                outcome="failed",
                reason="device_mismatch",
                client_ip=client_ip,
                user_agent=user_agent,
            )
            return None, "device_mismatch"

        session = await self._slide(session, now, client_ip=client_ip, user_agent=user_agent)

        if session.status == "restricted":
            return session, "session_restricted"
        if session.status in ("risk_limited", "locked"):
            return session, "session_restricted"
        return session, None

    async def _slide(
        self,
        session: WorkforceSession,
        now: datetime,
        *,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> WorkforceSession:
        """Push the idle window forward, clamped by the absolute ceiling."""
        idle_minutes = int(session.metadata.get("idle_minutes", _FALLBACK_LIFETIME["idle_minutes"]))
        candidate = now + timedelta(minutes=idle_minutes)
        ceiling = self._governing_absolute(session)
        if ceiling is not None and candidate > ceiling:
            candidate = ceiling

        session.idle_expires_at = _iso(candidate)
        session.last_seen_at = _iso(now)
        if client_ip:
            session.client_ip = client_ip
        if user_agent:
            session.user_agent = user_agent

        step_up_expiry = _parse(session.metadata.get("step_up_expires_at"))
        if session.authentication_strength == "stepped_up" and (
            step_up_expiry is None or now >= step_up_expiry
        ):
            # The elevation lapsed. Fall back to the standing device-bound
            # strength rather than keeping a stale claim on the row.
            session.authentication_strength = "device_bound"
            session.metadata.pop("step_up_expires_at", None)

        return await self._save(session)

    async def touch(self, session_id: str) -> None:
        """Slide the idle window for a session that is being actively used."""
        session = await self.get(session_id)
        if session is None or session.status in _TERMINAL_STATUSES:
            return
        await self._slide(session, self._now())

    async def _mark_expired(self, session: WorkforceSession, *, reason: str) -> WorkforceSession:
        session.status = "expired"
        await self._save(session)
        await self._emit_active_gauge()
        await self._record_event(
            event_type="session_revoked",
            session=session,
            outcome="failed",
            reason=reason,
        )
        return session

    # ── Rotation ─────────────────────────────────────────────────────────────

    async def rotate(self, session_id: str, *, reason: str) -> tuple[WorkforceSession, str]:
        """Replace the session handle in place. Returns ``(session, raw_token)``.

        The previous handle stops resolving the instant the digest is
        overwritten, which is what makes rotation a fixation defence rather
        than bookkeeping. Rotate on every authentication-strength change,
        privilege change and step-up.
        """
        session = await self.get(session_id)
        if session is None:
            raise KeyError(f"unknown Kyber session: {session_id}")

        raw_token, token_hash = _mint_token()
        _csrf_raw, csrf_hash = issue_csrf_token()
        session.token_hash = token_hash
        session.csrf_token_hash = csrf_hash
        session.rotated_at = _iso(self._now())
        await self._save(session)

        await self._record_event(
            event_type="session_rotated", session=session, reason=reason
        )
        await self._audit(session=session, action="rotate", outcome="allowed", reason=reason)
        logger.info(f"kyber: session rotated id={session_id} reason={reason}")
        return session, raw_token

    async def apply_step_up(
        self, session_id: str, *, expires_at: str, capability_id: Optional[str] = None
    ) -> WorkforceSession:
        """Promote a session to ``stepped_up`` until ``expires_at``.

        Called by the step-up service after an assertion verifies. Rotation is
        a separate call so the caller that must hand the new handle back to the
        browser is the one that mints it — a rotation whose token nobody
        receives would lock the operator out of their own session.
        """
        session = await self.get(session_id)
        if session is None:
            raise KeyError(f"unknown Kyber session: {session_id}")
        session.authentication_strength = "stepped_up"
        session.metadata["step_up_expires_at"] = expires_at
        if capability_id:
            session.metadata["step_up_capability_id"] = capability_id
        return await self._save(session)

    async def clear_step_up(self, session_id: str) -> Optional[WorkforceSession]:
        """Drop a session's elevation without ending the session."""
        session = await self.get(session_id)
        if session is None:
            return None
        session.metadata.pop("step_up_expires_at", None)
        session.metadata.pop("step_up_capability_id", None)
        if session.authentication_strength == "stepped_up":
            session.authentication_strength = "device_bound"
        return await self._save(session)

    # ── Revocation ───────────────────────────────────────────────────────────

    async def revoke(self, session_id: str, *, reason: str) -> Optional[WorkforceSession]:
        """End one session immediately. Idempotent."""
        session = await self.get(session_id)
        if session is None:
            return None
        if session.status == "revoked":
            return session

        session.status = "revoked"
        session.revoked_at = _iso(self._now())
        session.revocation_reason = reason
        await self._save(session)

        metrics.increment("kyber_session_revoked_total", labels={"reason": reason})
        await self._emit_active_gauge()
        await self._record_event(
            event_type="session_revoked", session=session, outcome="succeeded", reason=reason
        )
        await self._audit(session=session, action="revoke", outcome="blocked", reason=reason)
        logger.info(f"kyber: session revoked id={session_id} reason={reason}")
        return session

    async def _revoke_matching(self, filters: dict[str, Any], reason: str) -> list[WorkforceSession]:
        rows = await self._repo.find_many(filters, limit=1000)
        revoked: list[WorkforceSession] = []
        for row in rows:
            if row.get("status") in _TERMINAL_STATUSES:
                continue
            session = await self.revoke(row["session_id"], reason=reason)
            if session is not None:
                revoked.append(session)
        return revoked

    async def revoke_for_device(self, device_id: str, *, reason: str) -> int:
        """End every session bound to a device. Returns the count revoked.

        Called when a device is revoked or its risk state turns hostile. The
        device decision and the session decision must not be able to disagree.
        """
        revoked = await self._revoke_matching({"device_id": device_id}, reason)
        return len(revoked)

    async def revoke_for_operator(self, operator_id: str, *, reason: str) -> int:
        """End every session for a principal and close their tenant scopes.

        Suspension and offboarding must not leave a live tenant scope behind:
        an open scope is standing authorization to read one tenant, so it is
        closed in the same operation rather than left to expire.
        """
        revoked = await self._revoke_matching({"operator_id": operator_id}, reason)
        try:
            from ..access.scopes import access_scope_service

            await access_scope_service.revoke_for_operator(operator_id, reason=reason)
        except Exception as exc:  # pragma: no cover - scope store unavailable
            logger.error(
                f"kyber: session revocation could not close scopes operator={operator_id}: {exc}"
            )
        return len(revoked)

    async def reconcile_privileges(
        self, operator_id: str, *, new_template_ids: list[str], reason: str = "role_change"
    ) -> int:
        """Revoke sessions whose bound role templates no longer match.

        A session caches the role templates that sized its windows and shaped
        its authority. When the binding set changes, the cached view is stale
        in a security-relevant way, so the session ends and the operator picks
        up the new authority on the next sign-in.
        """
        target = frozenset(new_template_ids)
        rows = await self._repo.find_many({"operator_id": operator_id}, limit=1000)
        revoked = 0
        for row in rows:
            if row.get("status") in _TERMINAL_STATUSES:
                continue
            bound = frozenset((row.get("metadata") or {}).get("role_template_ids") or ())
            if bound == target:
                continue
            if await self.revoke(row["session_id"], reason=reason) is not None:
                revoked += 1
        return revoked

    # ── Queries ──────────────────────────────────────────────────────────────

    async def list_for_operator(self, operator_id: str) -> list[WorkforceSession]:
        """Every session row for a principal, newest first."""
        rows = await self._repo.find_many({"operator_id": operator_id}, limit=200)
        return [WorkforceSession(**row) for row in rows]

    async def list_active_for_operator(self, operator_id: str) -> list[WorkforceSession]:
        """Sessions that are neither revoked nor expired."""
        return [
            s for s in await self.list_for_operator(operator_id)
            if s.status not in _TERMINAL_STATUSES
        ]

    async def expire_due(self) -> int:
        """Sweep sessions whose windows have closed. Returns the count expired.

        Validation already fails closed on an expired row, so this sweep exists
        for hygiene and for the active-session gauge, not for correctness.
        """
        now = self._now()
        expired = 0
        for row in await self._repo.find_many({}, limit=1000):
            if row.get("status") in _TERMINAL_STATUSES:
                continue
            session = WorkforceSession(**row)
            absolute = self._governing_absolute(session)
            idle = _parse(session.idle_expires_at)
            if (absolute is not None and now >= absolute) or (idle is not None and now >= idle):
                await self._mark_expired(session, reason="sweep")
                expired += 1
        return expired


#: Process-wide singleton. Workers A and B call into this instance.
session_service = KyberSessionService()

__all__ = [
    "KyberAuthenticationEventRepository",
    "KyberSessionRepository",
    "KyberSessionService",
    "hash_token",
    "session_service",
]
