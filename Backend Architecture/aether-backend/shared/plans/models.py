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
    """Monthly subscription price under each pricing strategy."""
    option_a: Decimal  # Market Entry
    option_b: Decimal  # Ideal / Fair
    option_c: Decimal  # Premium


@dataclass(frozen=True)
class PlanDefinition:
    """A self-serve plan tier (P1-P4)."""
    plan_id: str                      # "P1", "P2", "P3", "P4"
    display_name: str                 # "Hobbyist", "Professional", etc.
    target_user: str                  # "Solo Devs", "Small Teams", etc.
    monthly_quota: int                # 25_000, 100_000, 250_000, 500_000
    member_cap: int                   # 1, 3, 5, 10
    burst_rpm: int                    # 100, 500, 1_200, 3_000
    blended_overage_per_1k: Decimal   # Customer-facing fallback rate
    service_count: int                # 10, 19, 29, 34
    pricing: PricingOptions           # Subscription price under each option


@dataclass(frozen=True)
class ServicePricing:
    """Per-1k-request pricing for one service across the 3 pricing options."""
    cost_per_1k: Decimal       # AWS / underlying cost
    option_a_per_1k: Decimal   # Market Entry overage rate
    option_b_per_1k: Decimal   # Ideal / Fair overage rate
    option_c_per_1k: Decimal   # Premium overage rate


@dataclass(frozen=True)
class ServiceDefinition:
    """One of the 34 Aether services with its endpoint, pricing, and gating."""
    name: str                                          # "Omni-Capture"
    pillar: str                                        # "Ingestion"
    endpoint_pattern: str                              # "/v1/ingest/*"
    pricing: ServicePricing
    # Map PlanTier -> access tier label or None (None = blocked).
    plan_access: dict = field(default_factory=dict)
