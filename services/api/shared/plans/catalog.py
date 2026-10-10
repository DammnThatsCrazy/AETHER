"""Aether Plans — Plan Catalog

Single source of truth for the 7 plan tiers: Alpha–Delta (self-serve) and
Epsilon/Omicron/Omega (contract / contact-us). Numeric values match the
Stripe product catalog and the canonical pricing spreadsheet.
"""

from __future__ import annotations

from decimal import Decimal

from shared.auth.auth import PlanTier
from shared.plans.models import PlanDefinition, PricingOptions


PLAN_CATALOG: dict[PlanTier, PlanDefinition] = {
    PlanTier.ALPHA: PlanDefinition(
        plan_id="alpha",
        display_name="Alpha",
        stripe_product_id="prod_VBIVKHD2G1maZC",
        target_user="Individuals",
        monthly_quota=3_000_000,
        member_cap=2,
        burst_rpm=100,
        event_overage_per_1k=Decimal("0.060"),
        acu_overage_per_1k=Decimal("7.00"),
        managed_per_acu=Decimal("0"),
        byok_per_acu=Decimal("0"),
        service_count=11,
        pricing=PricingOptions(monthly=Decimal("0"), annual=Decimal("0")),
    ),
    PlanTier.BETA: PlanDefinition(
        plan_id="beta",
        display_name="Beta",
        stripe_product_id="prod_V8G5BQNKwGiwJY",
        target_user="Growing Teams",
        monthly_quota=9_000_000,
        member_cap=3,
        burst_rpm=500,
        event_overage_per_1k=Decimal("0.050"),
        acu_overage_per_1k=Decimal("5.00"),
        managed_per_acu=Decimal("3.50"),
        byok_per_acu=Decimal("1.75"),
        service_count=22,
        pricing=PricingOptions(monthly=Decimal("299"), annual=Decimal("3050")),
    ),
    PlanTier.GAMMA: PlanDefinition(
        plan_id="gamma",
        display_name="Gamma",
        stripe_product_id="prod_V8G5BcUyK9FTN3",
        target_user="Scale-ups",
        monthly_quota=18_000_000,
        member_cap=5,
        burst_rpm=2_000,
        event_overage_per_1k=Decimal("0.040"),
        acu_overage_per_1k=Decimal("4.00"),
        managed_per_acu=Decimal("3.00"),
        byok_per_acu=Decimal("1.50"),
        service_count=36,
        pricing=PricingOptions(monthly=Decimal("899"), annual=Decimal("9170")),
    ),
    PlanTier.DELTA: PlanDefinition(
        plan_id="delta",
        display_name="Delta",
        stripe_product_id="prod_V8G6eoKilEbNf0",
        target_user="Enterprises",
        monthly_quota=27_000_000,
        member_cap=5,
        burst_rpm=5_000,
        event_overage_per_1k=Decimal("0.030"),
        acu_overage_per_1k=Decimal("3.00"),
        managed_per_acu=Decimal("1.25"),
        byok_per_acu=Decimal("0.625"),
        service_count=41,
        pricing=PricingOptions(monthly=Decimal("3449"), annual=Decimal("35180")),
    ),
    PlanTier.EPSILON: PlanDefinition(
        plan_id="epsilon",
        display_name="Epsilon",
        stripe_product_id="prod_VBMTchryHXE8RJ",
        target_user="High-Volume / Contact Sales",
        monthly_quota=54_000_000,
        member_cap=0,
        burst_rpm=10_000,
        event_overage_per_1k=Decimal("0"),
        acu_overage_per_1k=Decimal("0"),
        managed_per_acu=Decimal("0"),
        byok_per_acu=Decimal("0"),
        service_count=41,
        pricing=PricingOptions(monthly=Decimal("0"), annual=Decimal("0")),
    ),
    PlanTier.OMICRON: PlanDefinition(
        plan_id="omicron",
        display_name="Omicron",
        stripe_product_id="prod_VBMVO9hFtBnvd0",
        target_user="Dedicated / Governed Deployment",
        monthly_quota=0,
        member_cap=0,
        burst_rpm=0,
        event_overage_per_1k=Decimal("0"),
        acu_overage_per_1k=Decimal("0"),
        managed_per_acu=Decimal("0"),
        byok_per_acu=Decimal("0"),
        service_count=41,
        pricing=PricingOptions(monthly=Decimal("0"), annual=Decimal("0")),
    ),
    PlanTier.OMEGA: PlanDefinition(
        plan_id="omega",
        display_name="Omega",
        stripe_product_id="prod_VBMVpNS7m8fowq",
        target_user="Private / Regulated",
        monthly_quota=0,
        member_cap=0,
        burst_rpm=0,
        event_overage_per_1k=Decimal("0"),
        acu_overage_per_1k=Decimal("0"),
        managed_per_acu=Decimal("0"),
        byok_per_acu=Decimal("0"),
        service_count=41,
        pricing=PricingOptions(monthly=Decimal("0"), annual=Decimal("0")),
    ),
}


def get_plan(plan_tier: PlanTier) -> PlanDefinition:
    """Return the PlanDefinition for a PlanTier (KeyError if missing)."""
    return PLAN_CATALOG[plan_tier]
