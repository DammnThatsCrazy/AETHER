"""Workforce principal persistence and authority resolution.

A workforce principal is an Olympus Labs employee. It is never an Aether
tenant, it never holds a password, and it exists only because a founder
invited it or because the one-time founder bootstrap created it.

This module owns three things:

* the JSONB repositories for principals, role bindings and capability grants,
* the authentication-event recorder every Kyber authentication path writes to,
* :class:`PrincipalService`, the single place that answers "what may this
  operator do right now?".

Authority resolution is deliberately fail-closed. A principal that is not
``active``, whose ``kyber_enabled`` flag is off, or whose request names an
environment the principal may not reach, resolves to the empty capability set
rather than to a partial one. A live ``deny`` capability grant always beats a
role template that would allow the same capability, so removing one capability
from one operator never requires rebuilding a shared role.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.temporal.instant import try_parse_instant
from services.kyber.access.contracts import (
    AuthenticationEvent,
    AuthenticationEventType,
    CapabilityGrant,
    RoleBinding,
    WorkforcePrincipal,
    now_iso,
)
from services.kyber.access.roles import access_roles_for, capabilities_for, require_role_template
from services.security.audit_ledger import audit_ledger
from shared.common.common import BadRequestError, NotFoundError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.kyber.identity.principals")

#: The audit ledger actor type every Kyber workforce action is recorded under.
AUDIT_ACTOR_TYPE = "olympus_operator"

__all__ = [
    "AUDIT_ACTOR_TYPE",
    "AuthenticationEventRepository",
    "CapabilityGrantRepository",
    "PrincipalService",
    "RoleBindingRepository",
    "WorkforcePrincipalRepository",
    "environment_matches",
    "is_expired",
    "normalize_email",
    "parse_timestamp",
    "principal_service",
    "record_authentication_event",
]


# ── Small shared time / matching helpers ──────────────────────────────────────

def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Returns ``None`` for absent values and for anything unparseable. Callers
    treat ``None`` from an *expiry* field as "no expiry", so every caller that
    parses a value it did not itself write must decide what an unparseable
    value means; :func:`is_expired` treats it as expired.
    """
    if not value:
        return None
    # The canonical parser, not a local one. It rejects timezone-naive input
    # rather than assuming UTC — an invitation or binding expiry whose zone is
    # unknown must read as unusable, not as a moment we guessed.
    instant, _reason = try_parse_instant(str(value).strip())
    return instant


def is_expired(expires_at: Optional[str], *, at: Optional[datetime] = None) -> bool:
    """True when ``expires_at`` names a moment at or before now.

    An absent expiry never expires. A malformed expiry is treated as expired:
    a record whose lifetime cannot be established must not grant authority.
    """
    if not expires_at:
        return False
    moment = parse_timestamp(expires_at)
    if moment is None:
        return True
    return moment <= (at or datetime.now(timezone.utc))


def normalize_email(email: str) -> str:
    """Canonical form used for storage, invitation matching and comparison."""
    return (email or "").strip().lower()


def environment_matches(record_environment: Optional[str], environment: Optional[str]) -> bool:
    """Whether an environment-scoped record applies to the asked-about environment.

    A record with no environment applies everywhere. A caller that names no
    environment is asking for the principal's bindings in general, so every
    record matches; the environment ceiling is applied by the access dependency
    for a concrete request.
    """
    if record_environment is None:
        return True
    if environment is None:
        return True
    return record_environment == environment


# ── Repositories ──────────────────────────────────────────────────────────────

class WorkforcePrincipalRepository(BaseRepository):
    """``olympus_workforce_principals`` — one row per Olympus employee."""

    def __init__(self) -> None:
        super().__init__("olympus_workforce_principals")


class RoleBindingRepository(BaseRepository):
    """``olympus_role_bindings`` — principal → Kyber role template."""

    def __init__(self) -> None:
        super().__init__("olympus_role_bindings")


class CapabilityGrantRepository(BaseRepository):
    """``olympus_capability_grants`` — per-principal allow/deny overrides."""

    def __init__(self) -> None:
        super().__init__("olympus_capability_grants")


class AuthenticationEventRepository(BaseRepository):
    """``kyber_authentication_events`` — every authentication transition."""

    def __init__(self) -> None:
        super().__init__("kyber_authentication_events")


authentication_event_repository = AuthenticationEventRepository()


async def record_authentication_event(
    *,
    event_type: AuthenticationEventType,
    outcome: str = "succeeded",
    reason: Optional[str] = None,
    operator_id: Optional[str] = None,
    google_subject: Optional[str] = None,
    email: Optional[str] = None,
    session_id: Optional[str] = None,
    device_id: Optional[str] = None,
    environment: Optional[str] = None,
    client_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> AuthenticationEvent:
    """Append one authentication event.

    Failures record a coarse ``reason`` and never the submitted credential, so
    the table stays safe to read widely during an investigation.
    """
    event = AuthenticationEvent(
        event_type=event_type,
        outcome="succeeded" if outcome == "succeeded" else "failed",
        reason=reason,
        operator_id=operator_id,
        google_subject=google_subject,
        email=normalize_email(email) if email else None,
        session_id=session_id,
        device_id=device_id,
        environment=environment,
        client_ip=client_ip,
        user_agent=user_agent,
        metadata=metadata or {},
    )
    await authentication_event_repository.insert(event.event_id, event.model_dump())
    metrics.increment(
        "kyber_authentication_events_total",
        labels={"event_type": event.event_type, "outcome": event.outcome},
    )
    return event


# ── Service ───────────────────────────────────────────────────────────────────

class PrincipalService:
    """Reads and writes workforce principals, role bindings and grants."""

    def __init__(self) -> None:
        self.principals = WorkforcePrincipalRepository()
        self.bindings = RoleBindingRepository()
        self.grants = CapabilityGrantRepository()

    # ── Lookups ───────────────────────────────────────────────────────────────

    async def get_by_operator_id(self, operator_id: str) -> Optional[WorkforcePrincipal]:
        record = await self.principals.find_by_id(operator_id)
        return WorkforcePrincipal(**record) if record else None

    async def get_by_google_subject(self, google_subject: str) -> Optional[WorkforcePrincipal]:
        """Resolve by the identity key. Blank subjects never match."""
        if not google_subject:
            return None
        records = await self.principals.find_many(
            {"google_subject": google_subject}, limit=2
        )
        if not records:
            return None
        return WorkforcePrincipal(**records[0])

    async def get_by_email(self, email: str) -> Optional[WorkforcePrincipal]:
        normalized = normalize_email(email)
        if not normalized:
            return None
        records = await self.principals.find_many({"email": normalized}, limit=2)
        if not records:
            return None
        return WorkforcePrincipal(**records[0])

    async def list_principals(
        self, *, status: Optional[str] = None, limit: int = 100
    ) -> list[WorkforcePrincipal]:
        filters = {"employment_status": status} if status else None
        records = await self.principals.find_many(filters, limit=limit)
        return [WorkforcePrincipal(**r) for r in records]

    async def count_principals(self) -> int:
        return await self.principals.count()

    async def require_principal(self, operator_id: str) -> WorkforcePrincipal:
        principal = await self.get_by_operator_id(operator_id)
        if principal is None:
            raise NotFoundError("workforce principal")
        return principal

    # ── Role bindings ─────────────────────────────────────────────────────────

    async def list_role_bindings(
        self, operator_id: str, *, include_inactive: bool = False
    ) -> list[RoleBinding]:
        """Every binding on record for a principal, newest first.

        This is the reporting view: unlike :meth:`role_template_ids` it does not
        fail closed on employment status, because an administrator inspecting a
        suspended operator still needs to see what that operator was holding.
        """
        records = await self.bindings.find_many({"operator_id": operator_id}, limit=500)
        bindings = [RoleBinding(**r) for r in records]
        if include_inactive:
            return bindings
        return [
            b for b in bindings
            if b.revoked_at is None and not is_expired(b.expires_at)
        ]

    async def role_template_ids(
        self, operator_id: str, *, environment: Optional[str] = None
    ) -> list[str]:
        """Role template ids this principal may currently exercise.

        Fail-closed: an inactive principal, a Kyber-disabled principal, or one
        whose ``allowed_environments`` excludes the named environment holds no
        templates at all.
        """
        principal = await self.get_by_operator_id(operator_id)
        if principal is None or not principal.is_active:
            return []
        if not self._environment_allowed(principal, environment):
            return []
        template_ids: list[str] = []
        for binding in await self.list_role_bindings(operator_id):
            if not environment_matches(binding.environment, environment):
                continue
            if binding.role_template_id not in template_ids:
                template_ids.append(binding.role_template_id)
        return template_ids

    async def active_capability_grants(
        self, operator_id: str, *, environment: Optional[str] = None
    ) -> list[CapabilityGrant]:
        """Live allow/deny overrides applicable to the named environment."""
        records = await self.grants.find_many({"operator_id": operator_id}, limit=500)
        grants: list[CapabilityGrant] = []
        for record in records:
            grant = CapabilityGrant(**record)
            if grant.revoked_at is not None or is_expired(grant.expires_at):
                continue
            if not environment_matches(grant.environment, environment):
                continue
            grants.append(grant)
        return grants

    async def effective_capabilities(
        self, operator_id: str, *, environment: Optional[str] = None
    ) -> frozenset[str]:
        """Capabilities the principal actually holds right now.

        Union of the capability sets of its live role templates plus its live
        ``allow`` grants, minus its live ``deny`` grants. A ``deny`` always
        wins, including over a template the principal legitimately holds.
        """
        principal = await self.get_by_operator_id(operator_id)
        if principal is None or not principal.is_active:
            return frozenset()
        if not self._environment_allowed(principal, environment):
            return frozenset()

        template_ids = await self.role_template_ids(operator_id, environment=environment)
        capabilities = set(capabilities_for(template_ids))

        allowed: set[str] = set()
        denied: set[str] = set()
        for grant in await self.active_capability_grants(operator_id, environment=environment):
            (denied if grant.effect == "deny" else allowed).add(grant.capability_id)

        return frozenset((capabilities | allowed) - denied)

    async def access_roles(
        self, operator_id: str, *, environment: Optional[str] = None
    ) -> list[str]:
        """Governance AccessRoles implied by the principal's live templates."""
        template_ids = await self.role_template_ids(operator_id, environment=environment)
        return list(access_roles_for(template_ids))

    @staticmethod
    def _environment_allowed(
        principal: WorkforcePrincipal, environment: Optional[str]
    ) -> bool:
        if environment is None or not principal.allowed_environments:
            return True
        return environment in principal.allowed_environments

    # ── Writes ────────────────────────────────────────────────────────────────

    async def create_principal(
        self,
        *,
        email: str,
        google_subject: Optional[str],
        display_name: Optional[str],
        created_by: str,
        role_template_ids: list[str],
        allowed_environments: list[str],
    ) -> WorkforcePrincipal:
        """Create an ``invited`` principal and bind its role templates.

        Every requested template must exist. An unknown template is a caller
        error rather than a silently dropped grant, because dropping it would
        create a principal with less authority than the inviter believes.
        """
        normalized = normalize_email(email)
        if not normalized or "@" not in normalized:
            raise BadRequestError("a valid workforce email is required")
        for template_id in role_template_ids:
            try:
                require_role_template(template_id)
            except KeyError as exc:
                raise BadRequestError(str(exc)) from exc

        existing = await self.get_by_email(normalized)
        if existing is not None:
            raise BadRequestError("a workforce principal already exists for that email")
        if google_subject:
            by_subject = await self.get_by_google_subject(google_subject)
            if by_subject is not None:
                raise BadRequestError("a workforce principal already exists for that identity")

        principal = WorkforcePrincipal(
            email=normalized,
            google_subject=google_subject,
            display_name=display_name,
            employment_status="invited",
            created_by=created_by,
            allowed_environments=list(allowed_environments or []),
        )
        await self.principals.insert(principal.operator_id, principal.model_dump())

        for template_id in role_template_ids:
            await self._insert_binding(
                operator_id=principal.operator_id,
                role_template_id=template_id,
                granted_by=created_by,
                environment=None,
                expires_at=None,
                reason="created with principal",
            )

        metrics.increment("kyber_principal_created_total")
        await audit_ledger.record(
            actor_id=created_by,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.principal.created",
            resource_type="workforce_principal",
            action="create",
            outcome="allowed",
            resource_id=principal.operator_id,
            metadata={
                "email": normalized,
                "role_template_ids": list(role_template_ids),
                "allowed_environments": list(allowed_environments or []),
            },
        )
        logger.info(f"kyber principal created operator_id={principal.operator_id}")
        return principal

    async def activate(self, operator_id: str, *, google_subject: str) -> WorkforcePrincipal:
        """Bind the Google identity key and move the principal to ``active``.

        Idempotent for an already-active principal presenting the same subject;
        a *different* subject on an existing principal is rejected, because
        rebinding the identity key is how one operator would inherit another's
        authority.
        """
        principal = await self.require_principal(operator_id)
        if not google_subject:
            raise BadRequestError("google_subject is required to activate a principal")
        if principal.google_subject and principal.google_subject != google_subject:
            raise BadRequestError("principal is already bound to a different Google identity")
        if principal.employment_status == "offboarded":
            raise BadRequestError("an offboarded principal cannot be reactivated in place")

        patch = {
            "google_subject": google_subject,
            "employment_status": "active",
            "activated_at": principal.activated_at or now_iso(),
            "suspended_at": None,
        }
        record = await self.principals.update(operator_id, patch)
        metrics.increment("kyber_principal_activated_total")
        await audit_ledger.record(
            actor_id=operator_id,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.principal.activated",
            resource_type="workforce_principal",
            action="activate",
            outcome="allowed",
            resource_id=operator_id,
            metadata={"email": principal.email},
        )
        return WorkforcePrincipal(**record)

    async def suspend(
        self, operator_id: str, *, actor_id: str, reason: str
    ) -> WorkforcePrincipal:
        """Suspend Kyber access without changing role bindings.

        Idempotent: suspending an already-suspended principal re-records the
        audit event and returns the record unchanged.
        """
        principal = await self.require_principal(operator_id)
        if principal.employment_status in ("suspended", "offboarded"):
            await self._audit_lifecycle(
                principal, actor_id=actor_id, reason=reason, action="suspend", repeated=True
            )
            return principal

        record = await self.principals.update(
            operator_id,
            {
                "employment_status": "suspended",
                "kyber_enabled": False,
                "suspended_at": now_iso(),
            },
        )
        metrics.increment("kyber_principal_suspended_total")
        await self._audit_lifecycle(
            principal, actor_id=actor_id, reason=reason, action="suspend", repeated=False
        )
        logger.warning(f"kyber principal suspended operator_id={operator_id}")
        return WorkforcePrincipal(**record)

    async def offboard(
        self, operator_id: str, *, actor_id: str, reason: str
    ) -> WorkforcePrincipal:
        """Terminal state. Kyber access ends and cannot be restored in place.

        Idempotent. This is the identity half of offboarding only — session,
        device and scope revocation runs through
        :func:`services.kyber.identity.lifecycle.offboard_principal`.
        """
        principal = await self.require_principal(operator_id)
        if principal.employment_status == "offboarded":
            await self._audit_lifecycle(
                principal, actor_id=actor_id, reason=reason, action="offboard", repeated=True
            )
            return principal

        record = await self.principals.update(
            operator_id,
            {
                "employment_status": "offboarded",
                "kyber_enabled": False,
                "offboarded_at": now_iso(),
                "suspended_at": principal.suspended_at or now_iso(),
            },
        )
        metrics.increment("kyber_principal_offboarded_total")
        await self._audit_lifecycle(
            principal, actor_id=actor_id, reason=reason, action="offboard", repeated=False
        )
        logger.warning(f"kyber principal offboarded operator_id={operator_id}")
        return WorkforcePrincipal(**record)

    async def mark_directory_synced(self, operator_id: str, *, at: Optional[str] = None) -> None:
        """Stamp the directory freshness clock. Only a real reconcile calls this."""
        await self.principals.update(
            operator_id, {"last_directory_sync_at": at or now_iso()}
        )

    async def mark_login(self, operator_id: str) -> None:
        await self.principals.update(operator_id, {"last_login_at": now_iso()})

    async def _audit_lifecycle(
        self,
        principal: WorkforcePrincipal,
        *,
        actor_id: str,
        reason: str,
        action: str,
        repeated: bool,
    ) -> None:
        await audit_ledger.record(
            actor_id=actor_id,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type=f"kyber.principal.{action}ed",
            resource_type="workforce_principal",
            action=action,
            outcome="allowed",
            resource_id=principal.operator_id,
            metadata={
                "email": principal.email,
                "reason": reason,
                "previous_status": principal.employment_status,
                "repeated": repeated,
            },
        )

    # ── Role binding writes ───────────────────────────────────────────────────

    async def bind_role(
        self,
        *,
        operator_id: str,
        role_template_id: str,
        granted_by: str,
        environment: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> RoleBinding:
        """Grant one role template to one principal."""
        await self.require_principal(operator_id)
        try:
            require_role_template(role_template_id)
        except KeyError as exc:
            raise BadRequestError(str(exc)) from exc

        binding = await self._insert_binding(
            operator_id=operator_id,
            role_template_id=role_template_id,
            granted_by=granted_by,
            environment=environment,
            expires_at=expires_at,
            reason=None,
        )
        metrics.increment("kyber_role_binding_created_total")
        await audit_ledger.record(
            actor_id=granted_by,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.role_binding.created",
            resource_type="role_binding",
            action="grant",
            outcome="allowed",
            resource_id=binding.binding_id,
            metadata={
                "operator_id": operator_id,
                "role_template_id": role_template_id,
                "environment": environment,
                "expires_at": expires_at,
            },
        )
        return binding

    async def revoke_role_binding(
        self, binding_id: str, *, actor_id: str, reason: str
    ) -> RoleBinding:
        """Revoke one binding. Idempotent."""
        record = await self.bindings.find_by_id(binding_id)
        if record is None:
            raise NotFoundError("role binding")
        binding = RoleBinding(**record)
        if binding.revoked_at is not None:
            return binding

        updated = await self.bindings.update(
            binding_id,
            {"revoked_at": now_iso(), "revoked_by": actor_id, "reason": reason},
        )
        metrics.increment("kyber_role_binding_revoked_total")
        await audit_ledger.record(
            actor_id=actor_id,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.role_binding.revoked",
            resource_type="role_binding",
            action="revoke",
            outcome="allowed",
            resource_id=binding_id,
            metadata={
                "operator_id": binding.operator_id,
                "role_template_id": binding.role_template_id,
                "reason": reason,
            },
        )
        return RoleBinding(**updated)

    async def grant_capability(
        self,
        *,
        operator_id: str,
        capability_id: str,
        effect: str,
        granted_by: str,
        environment: Optional[str] = None,
        expires_at: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> CapabilityGrant:
        """Add a per-principal allow/deny override on one capability."""
        await self.require_principal(operator_id)
        if effect not in ("allow", "deny"):
            raise BadRequestError("capability grant effect must be 'allow' or 'deny'")

        grant = CapabilityGrant(
            operator_id=operator_id,
            capability_id=capability_id,
            effect=effect,  # type: ignore[arg-type]
            environment=environment,
            granted_by=granted_by,
            expires_at=expires_at,
            reason=reason,
        )
        await self.grants.insert(grant.grant_id, grant.model_dump())
        metrics.increment("kyber_capability_grant_created_total", labels={"effect": effect})
        await audit_ledger.record(
            actor_id=granted_by,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.capability_grant.created",
            resource_type="capability_grant",
            action="grant",
            outcome="allowed",
            resource_id=grant.grant_id,
            metadata={
                "operator_id": operator_id,
                "capability_id": capability_id,
                "effect": effect,
                "environment": environment,
            },
        )
        return grant

    async def _insert_binding(
        self,
        *,
        operator_id: str,
        role_template_id: str,
        granted_by: str,
        environment: Optional[str],
        expires_at: Optional[str],
        reason: Optional[str],
    ) -> RoleBinding:
        template = require_role_template(role_template_id)
        binding = RoleBinding(
            operator_id=operator_id,
            role_template_id=role_template_id,
            access_roles=list(template.access_roles),
            environment=environment,
            granted_by=granted_by,
            expires_at=expires_at,
            reason=reason,
        )
        await self.bindings.insert(binding.binding_id, binding.model_dump())
        return binding


principal_service = PrincipalService()
