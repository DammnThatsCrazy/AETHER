"""
Aether Shared — Budget Policies per Model Sensitivity Tier

Defines budget limits for each axis × window × tier combination.
Stricter limits for Tier 1 (critical) models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shared.scoring.extraction_models import ModelSensitivityTier
from shared.rate_limit.budget_keys import BudgetAxis, BudgetWindow


@dataclass(frozen=True)
class BudgetLimit:
    """A single budget limit for one axis/window combination."""
    axis: BudgetAxis
    window: BudgetWindow
    max_count: int


@dataclass
class TierBudgetPolicy:
    """Complete budget policy for a sensitivity tier."""
    tier: ModelSensitivityTier
    limits: list[BudgetLimit] = field(default_factory=list)
    max_batch_rows: int = 0           # 0 = batch denied
    batch_allowed: bool = False
    require_privileged_for_batch: bool = True

    def get_limit(self, axis: BudgetAxis, window: BudgetWindow) -> Optional[int]:
        for lim in self.limits:
            if lim.axis == axis and lim.window == window:
                return lim.max_count
        return None


# ═══════════════════════════════════════════════════════════════════════════
# TIER 1 — CRITICAL (tightest budgets)
# ═══════════════════════════════════════════════════════════════════════════

TIER_1_POLICY = TierBudgetPolicy(
    tier=ModelSensitivityTier.TIER_1_CRITICAL,
    max_batch_rows=0,
    batch_allowed=False,
    require_privileged_for_batch=True,
    limits=[
        # Per API key
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.MINUTE, 30),
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.HOUR, 500),
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.DAY, 5000),
        # Per IP
        BudgetLimit(BudgetAxis.IP, BudgetWindow.MINUTE, 60),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.HOUR, 1000),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.DAY, 10000),
        # Per tenant
        BudgetLimit(BudgetAxis.TENANT, BudgetWindow.HOUR, 5000),
        BudgetLimit(BudgetAxis.TENANT, BudgetWindow.DAY, 50000),
        # Per device fingerprint
        BudgetLimit(BudgetAxis.DEVICE, BudgetWindow.HOUR, 300),
        BudgetLimit(BudgetAxis.DEVICE, BudgetWindow.DAY, 3000),
        # Per identity cluster
        BudgetLimit(BudgetAxis.IDENTITY_CLUSTER, BudgetWindow.HOUR, 2000),
        BudgetLimit(BudgetAxis.IDENTITY_CLUSTER, BudgetWindow.DAY, 20000),
        # Per graph cluster
        BudgetLimit(BudgetAxis.GRAPH_CLUSTER, BudgetWindow.HOUR, 3000),
        BudgetLimit(BudgetAxis.GRAPH_CLUSTER, BudgetWindow.DAY, 30000),
    ],
)

# ═══════════════════════════════════════════════════════════════════════════
# TIER 2 — HIGH
# ═══════════════════════════════════════════════════════════════════════════

TIER_2_POLICY = TierBudgetPolicy(
    tier=ModelSensitivityTier.TIER_2_HIGH,
    max_batch_rows=0,
    batch_allowed=False,
    require_privileged_for_batch=True,
    limits=[
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.MINUTE, 60),
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.HOUR, 1000),
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.DAY, 10000),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.MINUTE, 120),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.HOUR, 3000),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.DAY, 30000),
        BudgetLimit(BudgetAxis.TENANT, BudgetWindow.HOUR, 10000),
        BudgetLimit(BudgetAxis.TENANT, BudgetWindow.DAY, 100000),
        BudgetLimit(BudgetAxis.DEVICE, BudgetWindow.HOUR, 600),
        BudgetLimit(BudgetAxis.DEVICE, BudgetWindow.DAY, 6000),
        BudgetLimit(BudgetAxis.IDENTITY_CLUSTER, BudgetWindow.HOUR, 5000),
        BudgetLimit(BudgetAxis.IDENTITY_CLUSTER, BudgetWindow.DAY, 50000),
        BudgetLimit(BudgetAxis.GRAPH_CLUSTER, BudgetWindow.HOUR, 8000),
        BudgetLimit(BudgetAxis.GRAPH_CLUSTER, BudgetWindow.DAY, 80000),
    ],
)

# ═══════════════════════════════════════════════════════════════════════════
# TIER 3 — STANDARD (most permissive)
# ═══════════════════════════════════════════════════════════════════════════

TIER_3_POLICY = TierBudgetPolicy(
    tier=ModelSensitivityTier.TIER_3_STANDARD,
    max_batch_rows=0,
    batch_allowed=False,
    require_privileged_for_batch=True,
    limits=[
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.MINUTE, 120),
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.HOUR, 3000),
        BudgetLimit(BudgetAxis.API_KEY, BudgetWindow.DAY, 30000),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.MINUTE, 240),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.HOUR, 6000),
        BudgetLimit(BudgetAxis.IP, BudgetWindow.DAY, 60000),
        BudgetLimit(BudgetAxis.TENANT, BudgetWindow.HOUR, 20000),
        BudgetLimit(BudgetAxis.TENANT, BudgetWindow.DAY, 200000),
        BudgetLimit(BudgetAxis.DEVICE, BudgetWindow.HOUR, 1200),
        BudgetLimit(BudgetAxis.DEVICE, BudgetWindow.DAY, 12000),
        BudgetLimit(BudgetAxis.IDENTITY_CLUSTER, BudgetWindow.HOUR, 10000),
        BudgetLimit(BudgetAxis.IDENTITY_CLUSTER, BudgetWindow.DAY, 100000),
        BudgetLimit(BudgetAxis.GRAPH_CLUSTER, BudgetWindow.HOUR, 15000),
        BudgetLimit(BudgetAxis.GRAPH_CLUSTER, BudgetWindow.DAY, 150000),
    ],
)

# ═══════════════════════════════════════════════════════════════════════════
# POLICY LOOKUP
# ═══════════════════════════════════════════════════════════════════════════

TIER_POLICIES: dict[ModelSensitivityTier, TierBudgetPolicy] = {
    ModelSensitivityTier.TIER_1_CRITICAL: TIER_1_POLICY,
    ModelSensitivityTier.TIER_2_HIGH: TIER_2_POLICY,
    ModelSensitivityTier.TIER_3_STANDARD: TIER_3_POLICY,
}


def get_tier_policy(tier: ModelSensitivityTier) -> TierBudgetPolicy:
    return TIER_POLICIES.get(tier, TIER_2_POLICY)
