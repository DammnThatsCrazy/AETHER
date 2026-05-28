"""
Aether — Retarget Recommendation Engine
Generates retargeting recommendations for entities with abandoned journeys
and a retarget_score >= 6.0.

Score formula:
  retarget_score = intent_signal × ltv_score × recency_decay × (1 - stage_depth)
  normalized to 0-10

  intent_signal:  JourneyPrediction model predicted_goal confidence (0-1)
  ltv_score:      LTVPrediction output normalized by cohort 95th percentile (0-1)
  recency_decay:  exp(-days_since_last_event / 7)
  stage_depth:    reached_stage_index / total_stages

Recommendation is surfaced to the analyst review queue. It is NEVER
executed automatically — the analyst must explicitly approve it.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from shared.logger.logger import get_logger

logger = get_logger("aether.recommendations.engine")

RETARGET_THRESHOLD = 6.0

# Mapping from entity behavioral signals to creative theme recommendations
_CREATIVE_THEME_MAP = {
    "YIELD_FARMER": "yield_and_rewards",
    "GOVERNANCE_PARTICIPANT": "governance_power",
    "DEFI_NATIVE": "defi_explorer",
    "POTENTIAL_WHALE": "exclusive_vip",
    "EARLY_ADOPTER": "pioneer_badge",
    "CROSS_CHAIN_POWER_USER": "multichain_journey",
    "BRIDGE_POWER_USER": "seamless_bridging",
    "HIGH_REFERRAL_GENERATOR": "referral_rewards",
    "AT_RISK_OF_CHURN": "come_back_offer",
    "DISCOUNT_SENSITIVE": "limited_offer",
    "STABLECOIN_DOMINANT": "stablecoin_yield",
    "HIGH_CRYPTO_EXPOSURE": "diversify_and_grow",
}

# Platform selection heuristics based on entity's social presence
_PLATFORM_PRIORITY = [
    "twitter_ads",
    "meta_ads",
    "google_ads",
    "linkedin_ads",
    "tiktok_ads",
]


@dataclass
class RecommendationInput:
    entity_id: str
    journey_id: str
    intent_signal: float         # 0-1 from JourneyPrediction model
    ltv_score: float             # 0-1 normalized by cohort P95
    days_since_last_event: float
    reached_stage_index: int
    total_stages: int
    active_signals: list[str]    # signal_ids active for this entity
    social_platforms: list[str]  # platforms entity is active on
    ltv_predicted_usd: float
    cpa_target_usd: float
    expected_conversion_rate: float


def compute_retarget_score(
    intent_signal: float,
    ltv_score: float,
    days_since_last_event: float,
    reached_stage_index: int,
    total_stages: int,
) -> float:
    """Compute the retarget score (0-10) for a given entity/journey state."""
    recency_decay = math.exp(-days_since_last_event / 7)
    stage_depth = reached_stage_index / max(total_stages, 1)
    raw_score = intent_signal * ltv_score * recency_decay * (1 - stage_depth)
    return round(min(raw_score * 10, 10.0), 2)


def select_platform(social_platforms: list[str]) -> str:
    """Select the recommended ad platform based on entity's social presence."""
    platform_map = {
        "twitter": "twitter_ads",
        "instagram": "meta_ads",
        "linkedin": "linkedin_ads",
        "tiktok": "tiktok_ads",
    }
    for social in social_platforms:
        if social in platform_map:
            return platform_map[social]
    return _PLATFORM_PRIORITY[0]  # default to twitter_ads


def select_creative_theme(active_signals: list[str]) -> str:
    """Select a creative theme based on the entity's active behavioral signals."""
    for signal_id in active_signals:
        if signal_id in _CREATIVE_THEME_MAP:
            return _CREATIVE_THEME_MAP[signal_id]
    return "general_reengagement"


def build_reasoning(
    retarget_score: float,
    intent_signal: float,
    ltv_predicted_usd: float,
    days_since_last_event: float,
    active_signals: list[str],
) -> list[str]:
    """Build human-readable evidence list for the analyst review UI."""
    reasoning = [
        f"Retarget score: {retarget_score:.1f}/10 — qualifies for analyst review (threshold: {RETARGET_THRESHOLD}).",
        f"Journey prediction intent signal: {intent_signal:.0%} confidence they will convert if re-engaged.",
        f"Predicted lifetime value: ${ltv_predicted_usd:,.0f} USD.",
        f"Last active {days_since_last_event:.0f} day(s) ago.",
    ]
    if active_signals:
        reasoning.append(
            f"Active behavioral signals: {', '.join(active_signals[:3])}."
        )
    return reasoning


def generate_recommendation(inp: RecommendationInput) -> dict | None:
    """
    Generate a retargeting recommendation for an entity/journey pair.

    Returns None if retarget_score < RETARGET_THRESHOLD.
    """
    retarget_score = compute_retarget_score(
        inp.intent_signal,
        inp.ltv_score,
        inp.days_since_last_event,
        inp.reached_stage_index,
        inp.total_stages,
    )

    if retarget_score < RETARGET_THRESHOLD:
        logger.debug(
            f"Entity {inp.entity_id} retarget_score={retarget_score} below threshold {RETARGET_THRESHOLD} — skipping"
        )
        return None

    platform = select_platform(inp.social_platforms)
    creative_theme = select_creative_theme(inp.active_signals)
    recommended_bid_usd = inp.cpa_target_usd * inp.expected_conversion_rate
    confidence = min((retarget_score / 10) * 0.95, 0.95)

    reasoning = build_reasoning(
        retarget_score,
        inp.intent_signal,
        inp.ltv_predicted_usd,
        inp.days_since_last_event,
        inp.active_signals,
    )

    now = datetime.now(timezone.utc).isoformat()

    return {
        "recommendation_id": str(uuid.uuid4()),
        "entity_id": inp.entity_id,
        "journey_id": inp.journey_id,
        "retarget_score": retarget_score,
        "recommended_platform": platform,
        "recommended_creative_theme": creative_theme,
        "recommended_bid_usd": float(Decimal(str(recommended_bid_usd)).quantize(Decimal("0.01"))),
        "recommended_audience_segment": f"{creative_theme}_segment",
        "confidence": confidence,
        "reasoning": reasoning,
        "status": "pending_review",
        "created_at": now,
        "reviewed_by": None,
        "review_notes": None,
        "executed_at": None,
    }
