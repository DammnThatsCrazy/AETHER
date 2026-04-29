"""Aether Plans — Plan Catalog

Single source of truth for the 4 self-serve plans (P1-P4). Numeric values
must match the Plans tab exactly.
"""

from __future__ import annotations

from decimal import Decimal

from shared.auth.auth import PlanTier
from shared.plans.models import PlanDefinition, PricingOptions


PLAN_CATALOG: dict[PlanTier, PlanDefinition] = {
    PlanTier.P1_HOBBYIST: PlanDefinition(
        plan_id="P1",
        display_name="Hobbyist",
        target_user="Solo Devs",
        monthly_quota=25_000,
        member_cap=1,
        burst_rpm=100,
        blended_overage_per_1k=Decimal("12.50"),
        service_count=10,
        pricing=PricingOptions(
            option_a=Decimal("99"),
            option_b=Decimal("299"),
            option_c=Decimal("449"),
        ),
    ),
    PlanTier.P2_PROFESSIONAL: PlanDefinition(
        plan_id="P2",
        display_name="Professional",
        target_user="Small Teams",
        monthly_quota=100_000,
        member_cap=3,
        burst_rpm=500,
        blended_overage_per_1k=Decimal("16.60"),
        service_count=19,
        pricing=PricingOptions(
            option_a=Decimal("499"),
            option_b=Decimal("829"),
            option_c=Decimal("1219"),
        ),
    ),
    PlanTier.P3_GROWTH_INTELLIGENCE: PlanDefinition(
        plan_id="P3",
        display_name="Growth Intelligence",
        target_user="Scale-ups",
        monthly_quota=250_000,
        member_cap=5,
        burst_rpm=1_200,
        blended_overage_per_1k=Decimal("28.70"),
        service_count=29,
        pricing=PricingOptions(
            option_a=Decimal("1499"),
            option_b=Decimal("2869"),
            option_c=Decimal("4239"),
        ),
    ),
    PlanTier.P4_PROTOCOL_MASTER: PlanDefinition(
        plan_id="P4",
        display_name="Protocol Master",
        target_user="Orgs",
        monthly_quota=500_000,
        member_cap=10,
        burst_rpm=3_000,
        blended_overage_per_1k=Decimal("35.00"),
        service_count=34,
        pricing=PricingOptions(
            option_a=Decimal("3999"),
            option_b=Decimal("8519"),
            option_c=Decimal("12499"),
        ),
    ),
}


def get_plan(plan_tier: PlanTier) -> PlanDefinition:
    """Return the PlanDefinition for a PlanTier (KeyError if missing)."""
    return PLAN_CATALOG[plan_tier]
