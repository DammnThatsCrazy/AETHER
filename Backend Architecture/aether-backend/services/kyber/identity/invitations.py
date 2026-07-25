"""Invite-only admission to the Kyber workforce.

There is no self-service signup and no way to become a workforce principal by
authenticating with a Google account that happens to be in the right domain.
Someone holding ``kyber.workforce.manage`` issues an invitation; the invited
person accepts it once, with the same verified email, through Google.

The invitation token exists only in the response to its creation. What is
stored is ``sha256(token)``, so a database read discloses nothing usable and a
leaked backup cannot be replayed into an account.

Two authority limits are enforced here rather than left to review:

* an invitation may not request ``founder_operator`` or ``emergency_root`` —
  those are assigned by a founder after the fact, so an invitation can never
  bootstrap workforce or role administration for its own recipient, and
* acceptance is rejected when the verified email Google returned differs from
  the invited email, so forwarding an invitation grants nothing.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Optional

from repositories.repos import BaseRepository
from services.kyber.access.contracts import (
    WorkforceInvitation,
    WorkforcePrincipal,
    now_iso,
)
from services.kyber.access.roles import require_role_template
from services.security.audit_ledger import audit_ledger
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError, utc_now
from shared.logger.logger import get_logger, metrics

from .principals import (
    AUDIT_ACTOR_TYPE,
    is_expired,
    normalize_email,
    principal_service,
)

logger = get_logger("aether.kyber.identity.invitations")

#: Templates an invitation may never request. Both confer authority over the
#: workforce itself, so they are founder-assigned after acceptance.
FOUNDER_ASSIGNED_TEMPLATE_IDS: frozenset[str] = frozenset(
    {"founder_operator", "emergency_root"}
)

MIN_TTL_HOURS = 1
MAX_TTL_HOURS = 48
DEFAULT_TTL_HOURS = 24

__all__ = [
    "DEFAULT_TTL_HOURS",
    "FOUNDER_ASSIGNED_TEMPLATE_IDS",
    "InvitationRepository",
    "InvitationService",
    "MAX_TTL_HOURS",
    "MIN_TTL_HOURS",
    "hash_invitation_token",
    "invitation_service",
]


def hash_invitation_token(token: str) -> str:
    """The only representation of an invitation token that is ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class InvitationRepository(BaseRepository):
    """``olympus_workforce_invitations`` — single-use workforce invitations."""

    def __init__(self) -> None:
        super().__init__("olympus_workforce_invitations")


class InvitationService:
    """Issues, revokes and redeems workforce invitations."""

    def __init__(self) -> None:
        self.repo = InvitationRepository()

    # ── Creation ──────────────────────────────────────────────────────────────

    async def create_invitation(
        self,
        *,
        email: str,
        role_template_ids: list[str],
        allowed_environments: list[str],
        invited_by: str,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> tuple[WorkforceInvitation, str]:
        """Issue one invitation and create its ``invited`` principal.

        Returns ``(invitation, raw_token)``. The raw token is returned exactly
        once and is not recoverable afterwards; re-sending an invitation means
        revoking this one and issuing another.
        """
        normalized = normalize_email(email)
        if not normalized or "@" not in normalized:
            raise BadRequestError("a valid workforce email is required")
        if not role_template_ids:
            raise BadRequestError("an invitation must request at least one role template")

        for template_id in role_template_ids:
            if template_id in FOUNDER_ASSIGNED_TEMPLATE_IDS:
                await self._audit_denied_creation(
                    email=normalized, invited_by=invited_by, template_id=template_id
                )
                raise ForbiddenError(
                    f"role template '{template_id}' is founder-assigned and cannot be "
                    "granted by invitation"
                )
            try:
                require_role_template(template_id)
            except KeyError as exc:
                raise BadRequestError(str(exc)) from exc

        ttl = max(MIN_TTL_HOURS, min(MAX_TTL_HOURS, int(ttl_hours)))
        token = secrets.token_urlsafe(32)
        invitation = WorkforceInvitation(
            token_hash=hash_invitation_token(token),
            email=normalized,
            role_template_ids=list(role_template_ids),
            allowed_environments=list(allowed_environments or []),
            invited_by=invited_by,
            expires_at=(utc_now() + timedelta(hours=ttl)).isoformat(),
        )

        # The principal is created now, holding no bindings: an invited
        # principal must be resolvable (so a duplicate invitation is refused)
        # without holding any authority before acceptance.
        principal = await principal_service.create_principal(
            email=normalized,
            google_subject=None,
            display_name=None,
            created_by=invited_by,
            role_template_ids=[],
            allowed_environments=list(allowed_environments or []),
        )
        invitation.metadata["principal_operator_id"] = principal.operator_id
        await self.repo.insert(invitation.invitation_id, invitation.model_dump())

        metrics.increment("kyber_invitation_created_total")
        await audit_ledger.record(
            actor_id=invited_by,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.invitation.created",
            resource_type="workforce_invitation",
            action="create",
            outcome="allowed",
            resource_id=invitation.invitation_id,
            metadata={
                "email": normalized,
                "role_template_ids": list(role_template_ids),
                "allowed_environments": list(allowed_environments or []),
                "ttl_hours": ttl,
                "operator_id": principal.operator_id,
            },
        )
        logger.info(f"kyber invitation created invitation_id={invitation.invitation_id}")
        return invitation, token

    # ── Redemption ────────────────────────────────────────────────────────────

    async def accept_invitation(
        self,
        *,
        token: str,
        google_subject: str,
        email: str,
        display_name: Optional[str] = None,
    ) -> WorkforcePrincipal:
        """Redeem an invitation once, for the identity it was issued to.

        ``email`` is the *verified* address Google asserted, not one the caller
        typed. Every rejection path records an audit event and raises with a
        reason that does not disclose whether the invitation exists.
        """
        if not token or not google_subject:
            raise ForbiddenError("invalid invitation")
        presented_hash = hash_invitation_token(token)
        invitation = await self._find_by_token_hash(presented_hash)
        if invitation is None:
            await self._audit_denied_acceptance(
                invitation_id=None, reason="unknown_token", google_subject=google_subject
            )
            raise ForbiddenError("invalid invitation")

        if invitation.status == "accepted":
            await self._audit_denied_acceptance(
                invitation_id=invitation.invitation_id,
                reason="already_accepted",
                google_subject=google_subject,
            )
            raise ForbiddenError("invalid invitation")
        if invitation.status == "revoked":
            await self._audit_denied_acceptance(
                invitation_id=invitation.invitation_id,
                reason="revoked",
                google_subject=google_subject,
            )
            raise ForbiddenError("invalid invitation")
        if invitation.status == "expired" or is_expired(invitation.expires_at):
            await self.repo.update(invitation.invitation_id, {"status": "expired"})
            await self._audit_denied_acceptance(
                invitation_id=invitation.invitation_id,
                reason="expired",
                google_subject=google_subject,
            )
            raise ForbiddenError("invalid invitation")

        presented_email = normalize_email(email)
        if not hmac.compare_digest(presented_email, invitation.email):
            await self._audit_denied_acceptance(
                invitation_id=invitation.invitation_id,
                reason="email_mismatch",
                google_subject=google_subject,
            )
            raise ForbiddenError("invalid invitation")

        existing_identity = await principal_service.get_by_google_subject(google_subject)
        operator_id = invitation.metadata.get("principal_operator_id")
        principal = (
            await principal_service.get_by_operator_id(operator_id) if operator_id else None
        )
        if principal is None:
            principal = await principal_service.get_by_email(invitation.email)
        if principal is None:
            await self._audit_denied_acceptance(
                invitation_id=invitation.invitation_id,
                reason="principal_missing",
                google_subject=google_subject,
            )
            raise NotFoundError("workforce principal")
        if existing_identity is not None and existing_identity.operator_id != principal.operator_id:
            await self._audit_denied_acceptance(
                invitation_id=invitation.invitation_id,
                reason="identity_already_bound",
                google_subject=google_subject,
            )
            raise ForbiddenError("invalid invitation")

        # Mark the invitation consumed before granting anything, so a
        # concurrent second redemption of the same token finds it accepted.
        await self.repo.update(
            invitation.invitation_id,
            {
                "status": "accepted",
                "accepted_at": now_iso(),
                "accepted_by_operator_id": principal.operator_id,
            },
        )

        if display_name and not principal.display_name:
            await principal_service.principals.update(
                principal.operator_id, {"display_name": display_name}
            )
        activated = await principal_service.activate(
            principal.operator_id, google_subject=google_subject
        )
        for template_id in invitation.role_template_ids:
            await principal_service.bind_role(
                operator_id=activated.operator_id,
                role_template_id=template_id,
                granted_by=invitation.invited_by,
            )

        metrics.increment("kyber_invitation_accepted_total")
        await audit_ledger.record(
            actor_id=activated.operator_id,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.invitation.accepted",
            resource_type="workforce_invitation",
            action="accept",
            outcome="allowed",
            resource_id=invitation.invitation_id,
            metadata={
                "operator_id": activated.operator_id,
                "role_template_ids": list(invitation.role_template_ids),
            },
        )
        logger.info(f"kyber invitation accepted operator_id={activated.operator_id}")
        return await principal_service.require_principal(activated.operator_id)

    # ── Administration ────────────────────────────────────────────────────────

    async def revoke_invitation(
        self, invitation_id: str, *, actor_id: str
    ) -> WorkforceInvitation:
        """Revoke a pending invitation. Idempotent; accepted ones stay accepted."""
        record = await self.repo.find_by_id(invitation_id)
        if record is None:
            raise NotFoundError("workforce invitation")
        invitation = WorkforceInvitation(**record)
        if invitation.status == "accepted":
            raise BadRequestError("an accepted invitation cannot be revoked")
        if invitation.status == "revoked":
            return invitation

        updated = await self.repo.update(
            invitation_id,
            {"status": "revoked", "revoked_at": now_iso(), "revoked_by": actor_id},
        )
        metrics.increment("kyber_invitation_revoked_total")
        await audit_ledger.record(
            actor_id=actor_id,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.invitation.revoked",
            resource_type="workforce_invitation",
            action="revoke",
            outcome="allowed",
            resource_id=invitation_id,
            metadata={"email": invitation.email},
        )
        return WorkforceInvitation(**updated)

    async def list_invitations(
        self, *, status: Optional[str] = None, limit: int = 100
    ) -> list[WorkforceInvitation]:
        filters = {"status": status} if status else None
        records = await self.repo.find_many(filters, limit=limit)
        return [WorkforceInvitation(**r) for r in records]

    async def get_invitation(self, invitation_id: str) -> Optional[WorkforceInvitation]:
        record = await self.repo.find_by_id(invitation_id)
        return WorkforceInvitation(**record) if record else None

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _find_by_token_hash(self, token_hash: str) -> Optional[WorkforceInvitation]:
        """Resolve a presented token digest to at most one invitation.

        The digest is compared with :func:`hmac.compare_digest` after the
        lookup so the comparison itself is constant time regardless of which
        backend served the read.
        """
        records = await self.repo.find_many({"token_hash": token_hash}, limit=2)
        for record in records:
            stored = str(record.get("token_hash") or "")
            if stored and hmac.compare_digest(stored, token_hash):
                return WorkforceInvitation(**record)
        return None

    async def _audit_denied_creation(
        self, *, email: str, invited_by: str, template_id: str
    ) -> None:
        metrics.increment("kyber_invitation_denied_total", labels={"reason": "founder_assigned"})
        await audit_ledger.record(
            actor_id=invited_by,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.invitation.denied",
            resource_type="workforce_invitation",
            action="create",
            outcome="blocked",
            metadata={
                "email": email,
                "reason": "founder_assigned_template",
                "role_template_id": template_id,
            },
        )

    async def _audit_denied_acceptance(
        self, *, invitation_id: Optional[str], reason: str, google_subject: str
    ) -> None:
        metrics.increment("kyber_invitation_denied_total", labels={"reason": reason})
        await audit_ledger.record(
            actor_id=google_subject,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.invitation.denied",
            resource_type="workforce_invitation",
            action="accept",
            outcome="blocked",
            resource_id=invitation_id,
            metadata={"reason": reason},
        )
        logger.warning(f"kyber invitation acceptance denied reason={reason}")


invitation_service = InvitationService()
