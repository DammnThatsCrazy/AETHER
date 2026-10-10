"""Platform operator tenants: the people who run Aether, not its customers.

Olympus staff and invited advisors use staging (and later production) to vet
and operate the platform. They are not billed customers, so none of the
customer controls apply to them: an operator tenant resolves to the top plan
and bypasses burst rate limits, monthly quota/overage metering and the ML
extraction budget. External tenants are unaffected.

A tenant is an operator only through a signal a tenant cannot grant itself:

* ``PLATFORM_OPERATOR_TENANT_IDS`` (``settings.security_governance``), set per
  environment by deployment configuration; or
* in staging, the tenant bound by the single-use first-admin bootstrap record,
  which is by construction the platform's own administrative tenant.

People reach that tenant through ``PLATFORM_OPERATOR_EMAILS``: a verified
sign-in from a listed email with no user or invitation yet joins it as owner
(``services/api/tenancy/auth/sso_membership.py``).

Kyber access is a separate, narrower boundary (``is_kyber_operator``) and is
not widened by this module.
"""

from __future__ import annotations

from typing import Optional

from config.settings import settings
from shared.logger.logger import get_logger

logger = get_logger("aether.auth.platform_operator")

_bootstrap_tenant_id: Optional[str] = None
_bootstrap_resolved = False


async def _staging_bootstrap_tenant_id() -> Optional[str]:
    """The staging first-admin bootstrap tenant, cached once it is known.

    The claim is single-use and never rebound, so a found value is cached for
    the life of the process. A missing claim is re-checked on later requests
    (the bootstrap may complete after startup). A lookup failure grants
    nothing.
    """
    global _bootstrap_tenant_id, _bootstrap_resolved
    if _bootstrap_resolved:
        return _bootstrap_tenant_id
    if settings.env.value != "staging":
        _bootstrap_resolved = True
        return None
    try:
        from repositories.repos import FirstAdminBootstrapRepository

        record = await FirstAdminBootstrapRepository().find_by_id("staging")
    except Exception as exc:  # noqa: BLE001 — fail closed, never grant on error
        logger.warning("platform operator bootstrap lookup failed: %s", type(exc).__name__)
        return None
    tenant_id = str((record or {}).get("tenant_id") or "") or None
    if tenant_id:
        _bootstrap_tenant_id = tenant_id
        _bootstrap_resolved = True
    return tenant_id


async def is_platform_operator(tenant_id: Optional[str]) -> bool:
    """True when ``tenant_id`` runs the platform rather than consumes it."""
    if not tenant_id:
        return False
    if tenant_id in settings.security_governance.platform_operator_tenant_ids:
        return True
    return tenant_id == await _staging_bootstrap_tenant_id()


async def platform_operator_tenant_id() -> Optional[str]:
    """The tenant platform operators join: the first configured operator
    tenant, else the staging first-admin bootstrap tenant. None when neither
    exists."""
    configured = settings.security_governance.platform_operator_tenant_ids
    if configured:
        return configured[0]
    return await _staging_bootstrap_tenant_id()


def is_platform_operator_email(email: Optional[str]) -> bool:
    """True when ``email`` is on the deployment's PLATFORM_OPERATOR_EMAILS list.

    Callers must only rely on this for an identity-provider-verified email.
    """
    normalized = (email or "").strip().casefold()
    return bool(normalized) and normalized in settings.security_governance.platform_operator_emails


def reset_platform_operator_cache() -> None:
    """Forget the cached bootstrap tenant (tests)."""
    global _bootstrap_tenant_id, _bootstrap_resolved
    _bootstrap_tenant_id = None
    _bootstrap_resolved = False


__all__ = [
    "is_platform_operator",
    "is_platform_operator_email",
    "platform_operator_tenant_id",
    "reset_platform_operator_cache",
]
