"""Tenant quota states (§3.17) and generic-webhook default policy (§3.18).

Both helpers are **fail-closed**:

* :func:`quota_state` surfaces ``quota_near_limit`` / ``quota_exceeded`` as soon
  as usage crosses the thresholds so downstream consumers can degrade safely.
* :func:`generic_webhook_enabled` defaults to ``False`` — the generic inbound
  webhook is disabled in V1 unless a tenant policy *explicitly* approves it
  (``generic_webhook_approved is True``). Any other value keeps it disabled.
"""
from __future__ import annotations

from typing import Any

# Quota state constants.
QUOTA_OK = "ok"
QUOTA_NEAR_LIMIT = "quota_near_limit"
QUOTA_EXCEEDED = "quota_exceeded"

QUOTA_STATES: tuple[str, ...] = (QUOTA_OK, QUOTA_NEAR_LIMIT, QUOTA_EXCEEDED)

# A tenant is "near limit" once usage reaches this fraction of the limit.
NEAR_LIMIT_THRESHOLD = 0.9

# V1 platform default: the generic inbound webhook is disabled for every tenant.
GENERIC_WEBHOOK_ENABLED_BY_DEFAULT = False


def quota_state(usage: int, limit: int) -> str:
    """Return the quota state for ``usage`` against ``limit``.

    * ``limit <= 0`` is treated as *no limit configured* -> :data:`QUOTA_OK`.
    * ``usage >= limit`` -> :data:`QUOTA_EXCEEDED`.
    * ``usage >= 90% of limit`` -> :data:`QUOTA_NEAR_LIMIT`.
    * otherwise -> :data:`QUOTA_OK`.
    """
    try:
        usage_val = float(usage)
        limit_val = float(limit)
    except (TypeError, ValueError):
        # Unusable inputs -> treat as unmetered rather than crash.
        return QUOTA_OK

    if usage_val < 0:
        usage_val = 0.0
    if limit_val <= 0:
        # No positive limit configured -> unmetered / unlimited.
        return QUOTA_OK
    if usage_val >= limit_val:
        return QUOTA_EXCEEDED
    if usage_val >= limit_val * NEAR_LIMIT_THRESHOLD:
        return QUOTA_NEAR_LIMIT
    return QUOTA_OK


def generic_webhook_enabled(tenant_policy: dict[str, Any] | None) -> bool:
    """Return whether the generic inbound webhook is enabled for a tenant.

    Defaults to ``False`` (V1 disabled). Enabled **only** when the tenant policy
    carries ``generic_webhook_approved is True`` (strict identity check — a
    truthy string / 1 / "true" does NOT enable it).
    """
    if not isinstance(tenant_policy, dict):
        return False
    return tenant_policy.get("generic_webhook_approved") is True


def generic_webhook_disabled(tenant_policy: dict[str, Any] | None) -> bool:
    """Convenience inverse of :func:`generic_webhook_enabled`.

    Useful for the ``generic_webhook_disabled`` launch-readiness check, which
    *passes* when the webhook is disabled.
    """
    return not generic_webhook_enabled(tenant_policy)
