"""
Aether — Gold Tier: Asset Composition Schema
Per-entity portfolio breakdown by asset category, computed per time window.
Source: Moralis portfolio API + silver_web3_events historical positions.
"""

from __future__ import annotations

GOLD_ASSET_COMPOSITION_DDL = """
CREATE TABLE IF NOT EXISTS gold_asset_composition (
    entity_id           String,
    tenant_id           String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days         Nullable(UInt16),
    -- Category percentages (0–100, sum ≈ 100)
    stablecoin_pct      Float32,
    eth_lst_pct         Float32,   -- ETH liquid staking tokens (stETH, rETH, etc.)
    btc_pct             Float32,
    altcoin_pct         Float32,
    nft_pct             Float32,
    other_pct           Float32,   -- tokens < 1% of portfolio collapsed here
    -- Portfolio total
    total_portfolio_usd Decimal(18, 6),
    -- Serialized JSON array: [{symbol, contract_address, chain_id, category, value_usd, pct}]
    asset_breakdown     String,
    computed_at         DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, window_days)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

# Token classification lists are maintained in PostgreSQL:
#   - stablecoin_tokens(address, chain_id, symbol)
#   - eth_lst_tokens(address, chain_id, symbol)
# The computation job joins silver_web3_events token balances against these lists.
