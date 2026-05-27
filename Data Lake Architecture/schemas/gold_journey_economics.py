"""
Aether — Gold Tier: Journey Economics Schema
Per-journey ROAS, CPA, LTV, and retarget score.
Also includes stage-by-stage time-to-convert data.
"""

from __future__ import annotations

GOLD_JOURNEY_ECONOMICS_DDL = """
CREATE TABLE IF NOT EXISTS gold_journey_economics (
    entity_id                           String,
    tenant_id                           String,
    journey_id                          String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days                         Nullable(UInt16),
    -- Campaign context
    campaign_id                         Nullable(String),
    channel                             Nullable(String),
    platform                            Nullable(String),
    -- Economics
    revenue_attributed_usd              Decimal(18, 6),
    ad_spend_usd                        Decimal(18, 6),
    roas                                Float32,     -- revenue_attributed / ad_spend
    cpa_usd                             Decimal(18, 6),  -- ad_spend / conversions
    ltv_predicted_usd                   Decimal(18, 6),
    ltv_actual_usd                      Decimal(18, 6),
    aov_usd                             Decimal(18, 6),  -- average order value
    repeat_count                        UInt32,
    -- Retarget scoring (0-10)
    retarget_score                      Float32,
    retarget_recommendation_id          Nullable(String),
    -- Stage-to-stage conversion times (milliseconds, Nullable if stage not reached)
    time_impression_to_click_ms         Nullable(Int64),
    time_click_to_visit_ms              Nullable(Int64),
    time_visit_to_connect_ms            Nullable(Int64),
    time_connect_to_swap_ms             Nullable(Int64),
    time_swap_to_liquidity_ms           Nullable(Int64),
    computed_at                         DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, journey_id, window_days)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

# retarget_score formula:
#   score = intent_signal(0-1) × ltv_score(0-1) × recency_decay × (1 - stage_depth)
#   normalized to 0-10
# intent_signal: from JourneyPrediction model predicted_goal confidence
# ltv_score: LTVPrediction output normalized by cohort max
# recency_decay: exp(-days_since_last_event / 7)
# stage_depth: reached_stage_index / total_stages
