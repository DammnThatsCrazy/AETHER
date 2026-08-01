"""Communications entitlements + quotas (§20).

Plan-based control of comms access WITHOUT inventing prices: each
:class:`PlanTier` maps to concrete limits (which provider families are
available, how many connections, how large a backfill window, how many monthly
events), and :class:`CommsEntitlementPolicy` evaluates a request against them,
returning an explicit state — never a silent drop:

    allowed · quota_approaching · quota_reached · upgrade_required

The policy is pure and deterministic (no I/O), so it is trivially testable and
the frontend/connector layers can consult it before acting. Enforcement fails
*safe*: over-limit returns ``upgrade_required`` / ``quota_reached`` with the
limit and current value, so the customer sees exactly what to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shared.auth.auth import PlanTier

# Provider families available per plan. ``None`` = all families (no restriction).
# "lifecycle" covers Klaviyo-class marketing; premium families gate on plan.
_ALL_FAMILIES: Optional[frozenset[str]] = None


@dataclass(frozen=True)
class CommsPlanLimits:
    """Concrete comms limits for one plan tier (no pricing)."""

    provider_available: bool
    allowed_provider_families: Optional[frozenset[str]]  # None = all
    max_connections: Optional[int]        # None = unlimited
    max_provider_accounts: Optional[int]
    max_backfill_days: Optional[int]      # None = provider maximum
    monthly_event_limit: Optional[int]    # None = unlimited
    premium_providers_allowed: bool


# Comms is a paid capability: P1 (hobbyist) has no comms; P2+ unlock it with
# progressively higher limits. Values are packaging levers, not prices.
COMMS_PLAN_LIMITS: dict[PlanTier, CommsPlanLimits] = {
    PlanTier.P1_HOBBYIST: CommsPlanLimits(
        provider_available=False, allowed_provider_families=frozenset(),
        max_connections=0, max_provider_accounts=0, max_backfill_days=0,
        monthly_event_limit=0, premium_providers_allowed=False,
    ),
    PlanTier.P2_PROFESSIONAL: CommsPlanLimits(
        provider_available=True, allowed_provider_families=frozenset({"lifecycle"}),
        max_connections=2, max_provider_accounts=2, max_backfill_days=30,
        monthly_event_limit=100_000, premium_providers_allowed=False,
    ),
    PlanTier.P3_GROWTH_INTELLIGENCE: CommsPlanLimits(
        provider_available=True, allowed_provider_families=_ALL_FAMILIES,
        max_connections=10, max_provider_accounts=25, max_backfill_days=180,
        monthly_event_limit=2_000_000, premium_providers_allowed=True,
    ),
    PlanTier.P4_PROTOCOL_MASTER: CommsPlanLimits(
        provider_available=True, allowed_provider_families=_ALL_FAMILIES,
        max_connections=None, max_provider_accounts=None, max_backfill_days=None,
        monthly_event_limit=None, premium_providers_allowed=True,
    ),
}

# Approaching threshold: warn at 80% of a quota before it is reached.
_APPROACHING_RATIO = 0.8


@dataclass(frozen=True)
class EntitlementDecision:
    allowed: bool
    state: str          # allowed | quota_approaching | quota_reached | upgrade_required
    reason: str
    limit: Optional[int] = None
    current: Optional[int] = None


class CommsEntitlementPolicy:
    """Evaluates comms requests against per-plan limits (pure, no I/O)."""

    def limits_for(self, plan: PlanTier) -> CommsPlanLimits:
        return COMMS_PLAN_LIMITS.get(plan, COMMS_PLAN_LIMITS[PlanTier.P1_HOBBYIST])

    def evaluate_connection(
        self, plan: PlanTier, *, provider_family: str = "lifecycle",
        current_connections: int = 0,
    ) -> EntitlementDecision:
        limits = self.limits_for(plan)
        if not limits.provider_available:
            return EntitlementDecision(
                False, "upgrade_required",
                "Communications Intelligence is not included in this plan",
            )
        families = limits.allowed_provider_families
        if families is not None and provider_family not in families:
            return EntitlementDecision(
                False, "upgrade_required",
                f"provider family {provider_family!r} requires a higher plan",
            )
        cap = limits.max_connections
        if cap is not None and current_connections >= cap:
            return EntitlementDecision(
                False, "quota_reached",
                f"connection limit reached ({current_connections}/{cap})",
                limit=cap, current=current_connections,
            )
        if cap is not None and current_connections >= int(cap * _APPROACHING_RATIO):
            return EntitlementDecision(
                True, "quota_approaching",
                f"approaching connection limit ({current_connections}/{cap})",
                limit=cap, current=current_connections,
            )
        return EntitlementDecision(True, "allowed", "within plan limits", limit=cap,
                                   current=current_connections)

    def clamp_backfill_days(self, plan: PlanTier, requested_days: int) -> tuple[int, bool]:
        """Return (effective_days, was_clamped). Never silently exceed the plan."""
        limits = self.limits_for(plan)
        if limits.max_backfill_days is None:
            return requested_days, False
        if requested_days > limits.max_backfill_days:
            return limits.max_backfill_days, True
        return requested_days, False

    def evaluate_event_volume(
        self, plan: PlanTier, *, monthly_events: int,
    ) -> EntitlementDecision:
        limits = self.limits_for(plan)
        cap = limits.monthly_event_limit
        if cap is None:
            return EntitlementDecision(True, "allowed", "unlimited event volume")
        if monthly_events >= cap:
            return EntitlementDecision(
                False, "quota_reached",
                f"monthly event limit reached ({monthly_events}/{cap})",
                limit=cap, current=monthly_events,
            )
        if monthly_events >= int(cap * _APPROACHING_RATIO):
            return EntitlementDecision(
                True, "quota_approaching",
                f"approaching monthly event limit ({monthly_events}/{cap})",
                limit=cap, current=monthly_events,
            )
        return EntitlementDecision(True, "allowed", "within event volume limit",
                                   limit=cap, current=monthly_events)

    def summary(self, plan: PlanTier) -> dict:
        """Serializable entitlement summary for the connection wizard."""
        limits = self.limits_for(plan)
        return {
            "plan_tier": plan.value,
            "provider_available": limits.provider_available,
            "allowed_provider_families": (
                sorted(limits.allowed_provider_families)
                if limits.allowed_provider_families is not None else "all"
            ),
            "max_connections": limits.max_connections,
            "max_provider_accounts": limits.max_provider_accounts,
            "max_backfill_days": limits.max_backfill_days,
            "monthly_event_limit": limits.monthly_event_limit,
            "premium_providers_allowed": limits.premium_providers_allowed,
        }


def is_comms_connector(connector_type: str) -> bool:
    """True when a connector is a communications provider (declares comms outputs)."""
    try:
        from shared.integration_contracts.catalog import manifest_by_family
        m = manifest_by_family.get(connector_type)
        return bool(m and any(o.startswith("comms.") for o in m.data_outputs))
    except Exception:  # pragma: no cover
        return False


__all__ = [
    "CommsPlanLimits",
    "COMMS_PLAN_LIMITS",
    "EntitlementDecision",
    "CommsEntitlementPolicy",
    "is_comms_connector",
]
