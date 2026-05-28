"""
Aether — Gold Tier: TradFi Portfolio Schema
Brokerage positions per entity, sourced from Alpaca, IBKR, Schwab, Fidelity.
Requires 'credit' consent purpose for balance/position data.
"""

from __future__ import annotations

GOLD_TRADFI_PORTFOLIO_DDL = """
CREATE TABLE IF NOT EXISTS gold_tradfi_portfolio (
    entity_id           String,
    tenant_id           String,
    broker              LowCardinality(String),  -- alpaca, ibkr, schwab, fidelity, robinhood, other
    asset_class         LowCardinality(String),  -- equity, bond, etf, option, crypto, cash, other
    symbol              Nullable(String),
    quantity            Nullable(Float64),
    value_usd           Decimal(18, 6),
    cost_basis_usd      Nullable(Decimal(18, 6)),
    unrealized_pnl_usd  Nullable(Decimal(18, 6)),
    currency_code       LowCardinality(String),
    asset_count         UInt32,
    last_sync_at        DateTime
)
ENGINE = ReplacingMergeTree(last_sync_at)
ORDER BY (tenant_id, entity_id, broker, asset_class, symbol)
TTL last_sync_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""
