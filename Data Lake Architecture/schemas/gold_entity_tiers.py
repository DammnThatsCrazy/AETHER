"""
Aether — Gold Tier: Entity Tier Intelligence Schema
Nightly computed tier assignments per entity per tenant.
Tier is derived from portfolio TVL percentile rank within the tenant population.
"""

from __future__ import annotations

GOLD_ENTITY_TIERS_DDL = """
CREATE TABLE IF NOT EXISTS gold_entity_tiers (
    entity_id       String,
    tenant_id       String,
    -- Tier assignment
    tier_name       LowCardinality(String),  -- Whale, Shark, Dolphin, Fish, Shrimp
    tier_level      UInt8,                   -- 1 (Whale) to 5 (Shrimp)
    percentile      Float32,                 -- 0–100 within tenant population
    tvl_usd         Decimal(18, 6),          -- portfolio value driving assignment
    -- Validity window
    valid_from      DateTime,
    valid_until     Nullable(DateTime),
    computed_at     DateTime
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(valid_from)
ORDER BY (tenant_id, entity_id)
TTL valid_from + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

# Population percentile query — run nightly per tenant
COMPUTE_TIERS_QUERY = """
INSERT INTO gold_entity_tiers
SELECT
    entity_id,
    tenant_id,
    multiIf(
        pct >= 99.9, 'Whale',
        pct >= 99.0, 'Shark',
        pct >= 95.0, 'Dolphin',
        pct >= 80.0, 'Fish',
        'Shrimp'
    ) AS tier_name,
    multiIf(
        pct >= 99.9, 1,
        pct >= 99.0, 2,
        pct >= 95.0, 3,
        pct >= 80.0, 4,
        5
    ) AS tier_level,
    pct AS percentile,
    tvl_usd,
    today() AS valid_from,
    today() + INTERVAL 1 DAY AS valid_until,
    now() AS computed_at
FROM (
    SELECT
        entity_id,
        tenant_id,
        total_portfolio_usd AS tvl_usd,
        -- PERCENT_RANK returns 0–1; multiply by 100 for percentile
        toFloat32(percent_rank() OVER (
            PARTITION BY tenant_id
            ORDER BY total_portfolio_usd ASC
        ) * 100) AS pct
    FROM (
        SELECT
            entity_id,
            tenant_id,
            sum(tvl_usd) AS total_portfolio_usd
        FROM gold_web3_daily_metrics
        WHERE date >= today() - 1
        GROUP BY entity_id, tenant_id
    )
)
"""
