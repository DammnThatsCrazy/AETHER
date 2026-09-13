"""
Aether Service — Rewards
Reward eligibility engine, queue processor, and automation routes.
"""

from services.rewards.eligibility import (
    Campaign,
    EligibilityEngine,
    EligibilityResult,
    RewardRule,
    RewardTier,
)
from services.rewards.queue import QueuedReward, RewardQueue

__all__ = [
    "Campaign",
    "EligibilityEngine",
    "EligibilityResult",
    "QueuedReward",
    "RewardQueue",
    "RewardRule",
    "RewardTier",
]
