"""Tenant launch readiness, trust states, and quota / generic-webhook policy.

New, additive service (§3.13 / §3.14 / §3.17 / §3.18). Wires nothing into the
app itself — see ``routes.py`` for the optional read-only router.
"""
from __future__ import annotations

from .quota import (
    GENERIC_WEBHOOK_ENABLED_BY_DEFAULT,
    NEAR_LIMIT_THRESHOLD,
    QUOTA_EXCEEDED,
    QUOTA_NEAR_LIMIT,
    QUOTA_OK,
    QUOTA_STATES,
    generic_webhook_disabled,
    generic_webhook_enabled,
    quota_state,
)
from .service import (
    LAUNCH_READINESS_CHECKS,
    VALID_STATUSES,
    TenantLaunchReadiness,
    TenantReadinessRepository,
)
from .trust_states import (
    TRUST_STATES,
    TrustState,
    derive_trust_states,
    is_trust_state,
)

__all__ = [
    "LAUNCH_READINESS_CHECKS",
    "VALID_STATUSES",
    "TenantLaunchReadiness",
    "TenantReadinessRepository",
    "TRUST_STATES",
    "TrustState",
    "derive_trust_states",
    "is_trust_state",
    "QUOTA_OK",
    "QUOTA_NEAR_LIMIT",
    "QUOTA_EXCEEDED",
    "QUOTA_STATES",
    "NEAR_LIMIT_THRESHOLD",
    "GENERIC_WEBHOOK_ENABLED_BY_DEFAULT",
    "quota_state",
    "generic_webhook_enabled",
    "generic_webhook_disabled",
]
