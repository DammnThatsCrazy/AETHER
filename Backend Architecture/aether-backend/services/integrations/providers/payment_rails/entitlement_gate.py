"""Payment-rail entitlement gate — plan-tier + permission admission.

Every payment-rails tenant route today is permission-gated (``require_permission``)
but NOT plan/entitlement-gated: any tenant holding the generic permission could
reach the payment-rail surfaces. This module adds the missing entitlement-key
gate on top, default OFF so it changes nothing until the integration pass
enables it:

* ``entitlement_gate_enabled`` (``AETHER_PAYMENT_ENTITLEMENT_GATE_ENABLED``,
  default ``False``) turns the plan gate on.
* ``min_plan_tier`` (``AETHER_PAYMENT_MIN_PLAN_TIER``, default ``"P1"``) is the
  lowest ``PlanTier`` the payment-rails entitlement key grants. A tenant whose
  ``plan_tier`` ranks below the minimum is denied with a 403 even though its
  role holds the permission — the permission and the entitlement are separate
  axes.

:func:`require_payment_rails_entitlement` is the single choke point: it runs the
existing permission check AND the plan gate, so every payment-rails route can
call it (or route helpers like ``_tenant_id`` can call it centrally) without
duplicating the policy. Rank order is P1 < P2 < P3 < P4; an unparseable
configured minimum fails OPEN (P1) so a typo cannot lock every tenant out.

This is NOT the x402 token entitlement service — that mints resource
entitlements for paid content. This is the "is this tenant's plan entitled to
the payment-rails product" admission gate, keyed by the product entitlement key
``payment_rails``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from shared.auth.auth import PlanTier
from shared.common.common import ForbiddenError

#: Product entitlement key for the payment-rails capability (the same token the
#: capability lifecycle records under).
PAYMENT_RAILS_ENTITLEMENT_KEY = "payment_rails"

#: Settings attributes on ``settings.payment_rails`` (set by the integration
#: pass; absent → gate OFF / minimum P1).
ENTITLEMENT_GATE_ATTR = "entitlement_gate_enabled"
MIN_PLAN_TIER_ATTR = "min_plan_tier"

_PLAN_RANK: dict[PlanTier, int] = {
    PlanTier.P1_HOBBYIST: 1,
    PlanTier.P2_PROFESSIONAL: 2,
    PlanTier.P3_GROWTH_INTELLIGENCE: 3,
    PlanTier.P4_PROTOCOL_MASTER: 4,
}

_PLAN_BY_TOKEN: dict[str, PlanTier] = {
    "p1": PlanTier.P1_HOBBYIST,
    "p2": PlanTier.P2_PROFESSIONAL,
    "p3": PlanTier.P3_GROWTH_INTELLIGENCE,
    "p4": PlanTier.P4_PROTOCOL_MASTER,
}


def plan_rank(tier: Optional[PlanTier]) -> int:
    """Ordinal rank of a ``PlanTier`` (P1=1 … P4=4); unknown → 0."""
    if tier is None:
        return 0
    try:
        return _PLAN_RANK[tier]
    except (KeyError, TypeError):
        target = getattr(tier, "value", tier)
        for member, rank in _PLAN_RANK.items():
            if member.value == target:
                return rank
        return 0


def _parse_min_tier(raw: Any) -> PlanTier:
    """Parse a configured minimum tier token ("P2", "p2", PlanTier) → PlanTier.

    Unparseable → ``P1_HOBBYIST`` (fail-open: a misconfig must not lock every
    tenant out of the surface).
    """
    if isinstance(raw, PlanTier):
        return raw
    token = _PLAN_BY_TOKEN.get(re.sub(r"\s+", "", str(raw or "")).lower())
    return token if token is not None else PlanTier.P1_HOBBYIST


def entitlement_gate_enabled() -> bool:
    from config.settings import settings

    return bool(getattr(settings.payment_rails, ENTITLEMENT_GATE_ATTR, False))


def configured_min_plan_tier() -> PlanTier:
    from config.settings import settings

    return _parse_min_tier(getattr(settings.payment_rails, MIN_PLAN_TIER_ATTR, "P1"))


def tenant_entitled(tier: Optional[PlanTier]) -> bool:
    """True when ``tier`` satisfies the configured payment-rails minimum plan."""
    if not entitlement_gate_enabled():
        return True
    return plan_rank(tier) >= plan_rank(configured_min_plan_tier())


def require_payment_rails_entitlement(
    request: Any, permission: str = "read", *, tenant_id: Optional[str] = None
) -> str:
    """Admission choke point for every payment-rails tenant route.

    1. Permission: ``request.state.tenant.require_permission(permission)``
       (unchanged behavior — an unauthorized role is denied first).
    2. Entitlement: when the gate is enabled, the tenant's ``plan_tier`` must
       rank at/above ``min_plan_tier`` or the request is denied 403.

    Returns the resolved ``tenant_id`` (mirrors the existing ``_tenant_id``
    contract) so route helpers can keep their one-line shape.
    """
    tenant = request.state.tenant
    tenant.require_permission(permission)
    resolved = tenant_id or getattr(tenant, "tenant_id", None)
    if entitlement_gate_enabled() and not tenant_entitled(getattr(tenant, "plan_tier", None)):
        raise ForbiddenError(
            f"Tenant is not entitled to {PAYMENT_RAILS_ENTITLEMENT_KEY} "
            f"(plan below {configured_min_plan_tier().value})"
        )
    if not resolved:
        raise ForbiddenError("Tenant context is required")
    return resolved


__all__ = [
    "PAYMENT_RAILS_ENTITLEMENT_KEY",
    "ENTITLEMENT_GATE_ATTR",
    "MIN_PLAN_TIER_ATTR",
    "plan_rank",
    "entitlement_gate_enabled",
    "configured_min_plan_tier",
    "tenant_entitled",
    "require_payment_rails_entitlement",
]
