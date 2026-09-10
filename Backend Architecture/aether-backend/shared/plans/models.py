"""Aether Plans — Data Models

Frozen dataclasses for plan and service definitions. These are pure data
containers; lookup logic lives in catalog.py and service_catalog.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from shared.auth.auth import PlanTier


@dataclass(frozen=True)
class PricingOptions:
    """Subscription pricing (monthly and annual)."""
    monthly: Decimal
    annual: Decimal


@dataclass(frozen=True)
class PlanDefinition:
    """A self-serve plan tier (Alpha–Delta)."""
    plan_id: str
    display_name: str
    stripe_product_id: str
    target_user: str
    monthly_quota: int
    member_cap: int
    burst_rpm: int
    event_overage_per_1k: Decimal
    acu_overage_per_1k: Decimal
    managed_per_acu: Decimal
    byok_per_acu: Decimal
    service_count: int
    pricing: PricingOptions


@dataclass(frozen=True)
class ServicePricing:
    """Per-1k-request pricing for one service across the 3 pricing options."""
    cost_per_1k: Decimal
    option_a_per_1k: Decimal
    option_b_per_1k: Decimal
    option_c_per_1k: Decimal


@dataclass(frozen=True)
class ServiceDefinition:
    """One of the Aether services with its endpoint, pricing, and gating."""
    name: str
    pillar: str
    endpoint_pattern: str
    pricing: ServicePricing
    plan_access: dict = field(default_factory=dict)
