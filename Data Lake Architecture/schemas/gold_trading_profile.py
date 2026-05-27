"""
Aether — Gold Tier: Trading Profile Schema
Per-entity on-chain trading behavior: pairs, protocol loyalty,
gas strategy, slippage, success rate. Computed from silver_web3_events.
"""

from __future__ import annotations

GOLD_TRADING_PROFILE_DDL = """
CREATE TABLE IF NOT EXISTS gold_trading_profile (
    entity_id               String,
    tenant_id               String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days             Nullable(UInt16),
    -- Serialized JSON array: [{pair, trade_count, volume_usd}], sorted by volume_usd desc
    favorite_pairs          String,
    -- Serialized JSON array: [{protocol_name, volume_pct}], top-3 by volume share
    protocol_loyalty        String,
    -- Gas strategy relative to network P50 gas price
    gas_strategy            LowCardinality(String),    -- fast, normal, slow
    avg_slippage_pct        Float32,
    avg_trade_size_usd      Decimal(18, 6),
    tx_success_rate         Float32,                   -- 0–1
    avg_gas_cost_usd        Decimal(18, 6),
    computed_at             DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, window_days)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

# gas_strategy derivation:
#   fast   = entity avg_gas_price > network_p75_gas_price
#   slow   = entity avg_gas_price < network_p25_gas_price
#   normal = otherwise
# Network P25/P75 sourced from silver_web3_events aggregate per chain per day.
