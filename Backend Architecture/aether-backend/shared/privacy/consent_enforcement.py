"""
Aether Privacy — Consent Enforcement at Processing Time

Enforces consent state at actual processing points, not just storage.
Called by middleware, async jobs, enrichment pipelines, and export paths.

Purposes derive from the canonical consent registry
(packages/shared/contracts/consent-registry.json) so this module can never
drift from the source of truth again. The registry loader fails closed to
the pre-registry purpose set only if the file is unreadable.
Enforcement behavior: fail-closed — disallowed processing is blocked.
"""

from __future__ import annotations

import json
import pathlib

from shared.logger.logger import get_logger

logger = get_logger("aether.privacy.consent")

_REGISTRY_PATH = (
    pathlib.Path(__file__).resolve().parents[4]
    / "packages" / "shared" / "contracts" / "consent-registry.json"
)

# Fallback only for environments where the registry file is unavailable.
_FALLBACK_PURPOSES = {
    "analytics", "marketing", "web3", "agent", "commerce",
    "personalization", "credit", "location",
}


def _load_registry_purposes() -> list[dict]:
    try:
        data = json.loads(_REGISTRY_PATH.read_text())
        purposes = data.get("purposes", [])
        if purposes:
            return purposes
    except Exception:  # pragma: no cover - registry file always ships with the repo
        logger.warning("consent registry unreadable; using fallback purpose set")
    return [{"key": key, "explicitOptInRequired": key in {"credit", "location"}}
            for key in sorted(_FALLBACK_PURPOSES)]


_REGISTRY_PURPOSES: list[dict] = _load_registry_purposes()

# Valid consent purposes that can be checked (registry-derived)
CONSENT_PURPOSES: set[str] = {p["key"] for p in _REGISTRY_PURPOSES}

# Purposes that require explicit consent rather than legitimate interest:
# every non-default-enabled purpose in the registry.
_CONSENT_REQUIRED_PURPOSES: set[str] = {
    p["key"] for p in _REGISTRY_PURPOSES if not p.get("defaultEnabled", False)
}


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
    return purpose in _CONSENT_REQUIRED_PURPOSES
