"""
Aether — Gold Tier: Temporal Heatmap Schema
24x7 activity density matrix + streak data per entity per time window.
All times are converted to the entity's primary timezone before aggregation.
"""

from __future__ import annotations

GOLD_TEMPORAL_HEATMAP_DDL = """
CREATE TABLE IF NOT EXISTS gold_temporal_heatmap (
    entity_id               String,
    tenant_id               String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days             Nullable(UInt16),
    -- 24x7 heatmap as serialized JSON [[Float32 x 7] x 24]
    -- Outer index = hour (0-23), inner index = weekday (0=Sunday ... 6=Saturday)
    heatmap_json            String,
    -- Peak activity
    peak_hour               UInt8,   -- 0-23 in local timezone
    peak_day                UInt8,   -- 0=Sunday to 6=Saturday
    -- Activity streaks (consecutive active days = >= 1 session or on-chain event)
    current_streak_days     UInt32,
    longest_streak_days     UInt32,
    -- Intensity labels (relative ranks within entity's own distribution)
    morning_intensity       Float32,    -- hours 0-6 local time
    afternoon_intensity     Float32,    -- hours 6-12 local time
    evening_intensity       Float32,    -- hours 12-18 local time
    night_intensity         Float32,    -- hours 18-24 local time
    timezone                Nullable(String),
    computed_at             DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, window_days)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

# Streak computation:
#   A day is "active" if >= 1 session OR >= 1 on-chain event exists.
#   Streak resets at midnight in the entity's primary timezone.
#   Primary timezone sourced from gold_location_history (primary location) or
#   falls back to UTC.
