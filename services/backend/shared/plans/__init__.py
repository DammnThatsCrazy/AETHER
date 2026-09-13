"""Aether Shared — @aether/plans

Canonical definitions for Aether self-serve plans (P1-P4) and the 34-service
registry. Used by the rate limiter, feature gate, monthly quota engine, and
overage billing calculator.
"""

from shared.plans.models import (  # noqa: F401
    PlanDefinition, PricingOptions, ServiceDefinition, ServicePricing,
)
from shared.plans.catalog import PLAN_CATALOG  # noqa: F401
from shared.plans.service_catalog import (  # noqa: F401
    SERVICE_CATALOG,
    ENDPOINT_MATCHERS,
    MINIMUM_PLAN_FOR_SERVICE,
    resolve_service,
    check_plan_access,
    find_service_by_name,
)
