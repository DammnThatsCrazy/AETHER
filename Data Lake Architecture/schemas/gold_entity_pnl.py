"""
Aether — Gold Tier: Entity PNL Schema
Realized + unrealized PNL and TVL delta per entity per time window.
Realized PNL computed via FIFO cost basis from silver_web3_events tx history
plus CoinGecko historical prices. data_confidence = 'estimated' when
partial tx history prevents exact FIFO calculation.
"""

from __future__ import annotations

GOLD_ENTITY_PNL_DDL = """
CREATE TABLE IF NOT EXISTS gold_entity_pnl (
    entity_id               String,
    tenant_id               String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days             Nullable(UInt16),
    -- Aggregated for the window
    realized_pnl_usd        Decimal(18, 6),
    unrealized_pnl_usd      Decimal(18, 6),
    -- Portfolio value change over window
    tvl_delta_usd           Decimal(18, 6),
    tvl_delta_pct           Float32,
    -- Best / worst day stats
    best_day_pnl_usd        Nullable(Decimal(18, 6)),
    best_day_date           Nullable(Date),
    worst_day_pnl_usd       Nullable(Decimal(18, 6)),
    worst_day_date          Nullable(Date),
    -- Cost basis metadata
    cost_basis_method       LowCardinality(String),    -- FIFO or LIFO
    data_confidence         LowCardinality(String),    -- exact or estimated
    computed_at             DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, window_days)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

GOLD_ENTITY_PNL_DAILY_DDL = """
CREATE TABLE IF NOT EXISTS gold_entity_pnl_daily (
    entity_id               String,
    tenant_id               String,
    date                    Date,
    realized_pnl_usd        Decimal(18, 6),
    unrealized_pnl_usd      Decimal(18, 6),
    tvl_usd                 Decimal(18, 6),
    computed_at             DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(date)
ORDER BY (tenant_id, entity_id, date)
TTL date + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""
