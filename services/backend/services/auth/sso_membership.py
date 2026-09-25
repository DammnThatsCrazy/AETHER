"""Where an Auth0 sign-in lands when its ``sub`` is not yet linked to a user.

``sso_callback`` provisions a brand-new tenant for an unknown ``sub``. That is
right for self-serve customers, but it would give every Olympus teammate (and
every stranger who can reach staging) a separate end-user tenant. Before that
fallback, a sign-in with an identity-provider-verified email:

1. links to an existing active user with that email and no Auth0 link yet
   (e.g. the staging first-admin user), keeping that user's tenant and role; or
2. accepts the newest unexpired pending organization invitation addressed to
   that email, joining the inviting tenant with the invited role. A sign-in
   that claimed an invitation but failed before its access was written is
   resumed by the same identity's next sign-in.

An unverified email never links or joins anything. Returns ``None`` when
neither applies; the caller then self-provisions or, where self-signup is
disabled (staging), refuses the sign-in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from services.account_organization.grants import grants_for
from shared.logger.logger import get_logger, metrics
from shared.temporal import SYSTEM_CLOCK, parse_instant_strict, to_iso_utc

logger = get_logger("aether.auth.sso_membership")


@dataclass(frozen=True)
class SSOMembership:
    tenant_id: str
    user_id: str
    how: str  # "linked_existing_user" | "accepted_invitation"


def _expired(invitation: dict[str, Any]) -> bool:
    try:
        return parse_instant_strict(str(invitation["expires_at"])) <= SYSTEM_CLOCK.now()
    except (KeyError, TypeError, ValueError):
        return True


async def _provision(
    invitation: dict[str, Any],
    tenant_id: str,
    user_id: str,
    sub: str,
    email: str,
    name: str,
    user_repo: Any,
    organization_repo: Any,
) -> None:
    """Write the membership, then the user, for a claimed invitation.

    Every step is idempotent, and the order makes a failure part-way
    recoverable: until the user row (the one carrying ``auth0_sub``) exists,
    the identity is still unknown, so its next sign-in comes back here through
    ``find_unprovisioned_claims`` and finishes the job.
    """
    organization_role = str(invitation.get("role") or "viewer")
    if await organization_repo.get_active_member_by_user(tenant_id, user_id) is None:
        try:
            await organization_repo.add_member(
                tenant_id,
                user_id=user_id,
                role=organization_role,
                email=email,
                display_name=name or email,
            )
        except Exception:
            # A concurrent callback for the same identity won the insert (the
            # repository check or the database's unique index); anything else
            # is a real failure.
            if await organization_repo.get_active_member_by_user(tenant_id, user_id) is None:
                raise
    role, permissions = grants_for(organization_role)
    await user_repo.insert(user_id, {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "name": name or email,
        "auth0_sub": sub,
        "status": "active",
        "email_verified": True,
        "auth_method": "sso",
        "role": role,
        "permissions": permissions,
        "membership_status": "active",
    })
    invitation_id = invitation.get("invitation_id") or invitation.get("id")
    await organization_repo.update_invitation(
        tenant_id, invitation_id, {"provisioned_at": to_iso_utc(SYSTEM_CLOCK.now())}
    )


async def resolve_sso_membership(
    *,
    sub: str,
    email: str,
    email_verified: bool,
    name: str,
    user_repo: Any = None,
    organization_repo: Any = None,
) -> Optional[SSOMembership]:
    email = (email or "").strip().casefold()
    if not sub or not email or not email_verified:
        return None

    if user_repo is None:
        from repositories.repos import UserRepository

        user_repo = UserRepository()

    existing = await user_repo.find_by_email(email)
    if existing and existing.get("tenant_id") and not existing.get("auth0_sub"):
        user_id = str(existing.get("user_id") or existing.get("id"))
        await user_repo.update(user_id, {"auth0_sub": sub, "email_verified": True})
        metrics.increment("sso_membership_resolved_total", labels={"how": "linked_existing_user"})
        logger.info("SSO sign-in linked to existing user: tenant=%s", existing["tenant_id"])
        return SSOMembership(existing["tenant_id"], user_id, "linked_existing_user")

    if organization_repo is None:
        from services.account_organization.routes import get_organization_repository

        organization_repo = get_organization_repository()

    # One principal per Auth0 identity: concurrent or retried callbacks for the
    # same sub converge on the same user row instead of duplicating it.
    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aether:sso-user:{sub}"))

    # Resume first: an invitation this identity already claimed on an earlier
    # sign-in that failed before its membership or user row was written.
    for invitation in await organization_repo.find_unprovisioned_claims(email, user_id):
        tenant_id = invitation.get("tenant_id")
        # An administrator who removed the half-provisioned member meant it:
        # the claim is not resumed into access.
        if tenant_id and not await organization_repo.membership_removed(tenant_id, user_id):
            await _provision(invitation, tenant_id, user_id, sub, email, name, user_repo, organization_repo)
            metrics.increment("sso_membership_resolved_total", labels={"how": "resumed_invitation"})
            logger.info("SSO sign-in resumed an accepted invitation: tenant=%s", tenant_id)
            return SSOMembership(tenant_id, user_id, "accepted_invitation")

    for invitation in await organization_repo.find_pending_invitations_for_email(email):
        tenant_id = invitation.get("tenant_id")
        invitation_id = invitation.get("invitation_id") or invitation.get("id")
        if not tenant_id or not invitation_id or _expired(invitation):
            continue
        # Claim first, atomically: a revoked, expired or already-claimed
        # invitation provisions nothing.
        now = SYSTEM_CLOCK.now()
        claimed = await organization_repo.claim_pending_invitation(tenant_id, invitation_id, {
            "status": "accepted",
            "accepted_at": to_iso_utc(now),
            "accepted_user_id": user_id,
        }, now=now)
        if not claimed:
            continue
        await _provision(invitation, tenant_id, user_id, sub, email, name, user_repo, organization_repo)
        metrics.increment("sso_membership_resolved_total", labels={"how": "accepted_invitation"})
        logger.info("SSO sign-in accepted invitation: tenant=%s", tenant_id)
        return SSOMembership(tenant_id, user_id, "accepted_invitation")
    return None


__all__ = ["SSOMembership", "resolve_sso_membership"]
