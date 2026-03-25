"""
Aether Privacy — Consent Enforcement at Processing Time

Enforces consent state at actual processing points, not just storage.
Called by middleware, async jobs, enrichment pipelines, and export paths.

Consent purposes: analytics, marketing, web3, agent, commerce
Enforcement behavior: fail-closed — disallowed processing is blocked.
"""

from __future__ import annotations

from typing import Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.privacy.consent")


# Valid consent purposes that can be checked
CONSENT_PURPOSES = {"analytics", "marketing", "web3", "agent", "commerce", "personalization"}


class ConsentDeniedError(Exception):
    """Raised when processing is denied due to consent state."""

    def __init__(self, user_id: str, purpose: str, tenant_id: str = ""):
        self.user_id = user_id
        self.purpose = purpose
        self.tenant_id = tenant_id
        super().__init__(
            f"Consent denied: user={user_id} purpose={purpose} tenant={tenant_id}"
        )


async def check_consent(
    consent_repo,
    tenant_id: str,
    user_id: str,
    purpose: str,
) -> bool:
    """
    Check if a user has granted consent for a specific purpose.

    Args:
        consent_repo: ConsentRepository instance.
        tenant_id: Tenant scope.
        user_id: The user whose consent is being checked.
        purpose: The processing purpose (analytics, marketing, web3, etc.).

    Returns:
        True if consent is granted for the purpose. False otherwise.
    """
    if not user_id or not tenant_id:
        return False

    record = await consent_repo.get_consent(tenant_id, user_id)
    if not record:
        # No consent record = no explicit grant. Depends on lawful basis.
        # For consent-required purposes, this is a denial.
        return False

    # Check if consent was explicitly granted
    if not record.get("granted", False):
        return False

    # Check if this specific purpose is in the granted purposes list
    granted_purposes = record.get("purposes", [])
    return purpose in granted_purposes


async def require_consent(
    consent_repo,
    tenant_id: str,
    user_id: str,
    purpose: str,
) -> None:
    """
    Require consent for a specific purpose. Raises ConsentDeniedError if not granted.

    Usage:
        await require_consent(consent_repo, tenant_id, user_id, "analytics")
    """
    allowed = await check_consent(consent_repo, tenant_id, user_id, purpose)
    if not allowed:
        logger.warning(
            f"Consent denied: user={user_id} purpose={purpose} tenant={tenant_id}"
        )
        raise ConsentDeniedError(user_id, purpose, tenant_id)


async def filter_by_consent(
    consent_repo,
    tenant_id: str,
    user_ids: list[str],
    purpose: str,
) -> list[str]:
    """
    Filter a list of user_ids to only those who have consented to a purpose.

    Useful for batch processing, enrichment pipelines, and export paths
    where a full list needs to be narrowed to consented users.

    Args:
        consent_repo: ConsentRepository instance.
        tenant_id: Tenant scope.
        user_ids: List of user IDs to check.
        purpose: The processing purpose.

    Returns:
        List of user_ids that have granted consent for the purpose.
    """
    consented: list[str] = []
    for uid in user_ids:
        if await check_consent(consent_repo, tenant_id, uid, purpose):
            consented.append(uid)
    return consented


def is_consent_required_purpose(purpose: str) -> bool:
    """Check if a purpose requires explicit consent (vs. legitimate interest)."""
    # These purposes require explicit opt-in consent
    consent_required = {"marketing", "personalization", "web3", "agent", "commerce"}
    return purpose in consent_required
