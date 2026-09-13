"""The one-time founder bootstrap.

Kyber is invite-only, which leaves an obvious question: who invites the first
person? This module answers it once and then closes the door behind itself.

Three independent conditions must all hold for a bootstrap to succeed:

1. ``KYBER_BOOTSTRAP_ENABLED`` is explicitly on,
2. there is not a single workforce principal on record, and
3. the verified Google identity presented matches the configured founder
   email *and*, when one is configured, the configured Google subject.

After a successful bootstrap an immutable ``kyber.bootstrap.completed``
authentication event is written. A second attempt fails on that marker even if
the operator forgets to turn the environment gate back off and even if the
founder principal is later removed, so the gate is never the only thing
standing between an attacker and a founder account.

Environment configuration is read here rather than through ``config/settings``
because the bootstrap path must work before any Kyber configuration object is
guaranteed to have been constructed.
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from services.kyber.access.contracts import WorkforcePrincipal
from services.security.audit_ledger import audit_ledger
from shared.common.common import ConflictError, ForbiddenError
from shared.logger.logger import get_logger, metrics

from .principals import (
    AUDIT_ACTOR_TYPE,
    authentication_event_repository,
    normalize_email,
    principal_service,
    record_authentication_event,
)

logger = get_logger("aether.kyber.identity.bootstrap")

#: The role template the first principal receives. Nothing else is assignable
#: by this path.
BOOTSTRAP_ROLE_TEMPLATE_ID = "founder_operator"

BOOTSTRAP_AUDIT_EVENT = "kyber.bootstrap.completed"

#: Environment variables this module reads. Mirrored in the workforce identity
#: source-of-truth document.
SETTINGS_NEEDED: tuple[tuple[str, str, str, str], ...] = (
    (
        "KYBER_BOOTSTRAP_ENABLED",
        "bool",
        "false",
        "Master gate for the one-time founder bootstrap. Off in every "
        "environment except the moment the first principal is created.",
    ),
    (
        "KYBER_BOOTSTRAP_FOUNDER_EMAIL",
        "str",
        "",
        "The verified Google Workspace email permitted to bootstrap.",
    ),
    (
        "KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT",
        "str",
        "",
        "Optional pinning of the founder's Google subject. When set, the "
        "email alone is not sufficient.",
    ),
)

__all__ = [
    "BOOTSTRAP_AUDIT_EVENT",
    "BOOTSTRAP_ROLE_TEMPLATE_ID",
    "FounderBootstrapService",
    "SETTINGS_NEEDED",
    "founder_bootstrap_service",
]

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


class FounderBootstrapService:
    """Creates the first workforce principal, exactly once, ever."""

    def __init__(self) -> None:
        self._consumed_in_process = False

    # ── Configuration ─────────────────────────────────────────────────────────

    @staticmethod
    def gate_enabled() -> bool:
        return _env_flag("KYBER_BOOTSTRAP_ENABLED", default=False)

    @staticmethod
    def founder_email() -> str:
        return normalize_email(os.getenv("KYBER_BOOTSTRAP_FOUNDER_EMAIL") or "")

    @staticmethod
    def founder_google_subject() -> str:
        return (os.getenv("KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT") or "").strip()

    # ── Availability ──────────────────────────────────────────────────────────

    async def has_been_consumed(self) -> bool:
        """True once a bootstrap has completed, from the durable marker."""
        if self._consumed_in_process:
            return True
        records = await authentication_event_repository.find_many(
            {"event_type": "bootstrap_completed"}, limit=1
        )
        if records:
            self._consumed_in_process = True
            return True
        return False

    async def is_available(self) -> bool:
        """Whether the bootstrap route may do anything at all right now."""
        if not self.gate_enabled():
            return False
        if await self.has_been_consumed():
            return False
        return await principal_service.count_principals() == 0

    # ── Execution ─────────────────────────────────────────────────────────────

    async def bootstrap(
        self,
        *,
        google_subject: str,
        email: str,
        display_name: Optional[str] = None,
        client_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> WorkforcePrincipal:
        """Create the founder principal. Refuses in every ambiguous case."""
        presented_email = normalize_email(email)

        if not self.gate_enabled():
            await self._deny(
                "bootstrap_disabled", email=presented_email, google_subject=google_subject,
                client_ip=client_ip, user_agent=user_agent,
            )
            raise ForbiddenError("founder bootstrap is disabled")

        if await self.has_been_consumed():
            await self._deny(
                "bootstrap_already_consumed", email=presented_email,
                google_subject=google_subject, client_ip=client_ip, user_agent=user_agent,
            )
            raise ConflictError("founder bootstrap has already been completed")

        if await principal_service.count_principals() != 0:
            await self._deny(
                "principals_exist", email=presented_email, google_subject=google_subject,
                client_ip=client_ip, user_agent=user_agent,
            )
            raise ConflictError("workforce principals already exist")

        configured_email = self.founder_email()
        if not configured_email:
            await self._deny(
                "founder_not_configured", email=presented_email,
                google_subject=google_subject, client_ip=client_ip, user_agent=user_agent,
            )
            raise ForbiddenError("founder bootstrap is not configured")
        if not presented_email or not hmac.compare_digest(presented_email, configured_email):
            await self._deny(
                "founder_email_mismatch", email=presented_email,
                google_subject=google_subject, client_ip=client_ip, user_agent=user_agent,
            )
            raise ForbiddenError("this identity may not bootstrap Kyber")

        configured_subject = self.founder_google_subject()
        if configured_subject and not hmac.compare_digest(
            (google_subject or "").strip(), configured_subject
        ):
            await self._deny(
                "founder_subject_mismatch", email=presented_email,
                google_subject=google_subject, client_ip=client_ip, user_agent=user_agent,
            )
            raise ForbiddenError("this identity may not bootstrap Kyber")
        if not (google_subject or "").strip():
            await self._deny(
                "subject_missing", email=presented_email, google_subject=google_subject,
                client_ip=client_ip, user_agent=user_agent,
            )
            raise ForbiddenError("this identity may not bootstrap Kyber")

        principal = await principal_service.create_principal(
            email=presented_email,
            google_subject=google_subject,
            display_name=display_name,
            created_by="kyber_bootstrap",
            role_template_ids=[BOOTSTRAP_ROLE_TEMPLATE_ID],
            allowed_environments=[],
        )
        activated = await principal_service.activate(
            principal.operator_id, google_subject=google_subject
        )

        # The durable "already consumed" marker. Written before the audit
        # record so a crash between the two still closes the door.
        await record_authentication_event(
            event_type="bootstrap_completed",
            outcome="succeeded",
            operator_id=activated.operator_id,
            google_subject=google_subject,
            email=presented_email,
            client_ip=client_ip,
            user_agent=user_agent,
            metadata={"role_template_id": BOOTSTRAP_ROLE_TEMPLATE_ID},
        )
        self._consumed_in_process = True

        metrics.increment("kyber_bootstrap_completed_total")
        await audit_ledger.record(
            actor_id=activated.operator_id,
            actor_type=AUDIT_ACTOR_TYPE,
            event_type=BOOTSTRAP_AUDIT_EVENT,
            resource_type="workforce_principal",
            action="bootstrap",
            outcome="allowed",
            resource_id=activated.operator_id,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={
                "email": presented_email,
                "role_template_id": BOOTSTRAP_ROLE_TEMPLATE_ID,
            },
        )
        logger.warning(
            f"kyber founder bootstrap completed operator_id={activated.operator_id}"
        )
        return activated

    async def _deny(
        self,
        reason: str,
        *,
        email: str,
        google_subject: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        metrics.increment("kyber_bootstrap_denied_total", labels={"reason": reason})
        await record_authentication_event(
            event_type="login_failed",
            outcome="failed",
            reason=reason,
            google_subject=google_subject or None,
            email=email or None,
            client_ip=client_ip,
            user_agent=user_agent,
            metadata={"stage": "bootstrap"},
        )
        await audit_ledger.record(
            actor_id=google_subject or "unknown",
            actor_type=AUDIT_ACTOR_TYPE,
            event_type="kyber.bootstrap.denied",
            resource_type="workforce_principal",
            action="bootstrap",
            outcome="blocked",
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": reason, "email": email},
        )
        logger.warning(f"kyber founder bootstrap denied reason={reason}")


founder_bootstrap_service = FounderBootstrapService()
