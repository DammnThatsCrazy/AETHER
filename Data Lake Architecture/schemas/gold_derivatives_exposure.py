"""
Aether — Gold Tier: Derivatives Exposure Schema
Daily per-tenant / account / market exposure and P&L rollups computed from
silver_derivatives_facts and derivatives_pnl_snapshots. Observation-only:
these rows describe externally executed trading activity; Aether never
executes. Private tenant account data — never mixed with public market
reference data, never model-training eligible (financial_activity purpose).
"""

from __future__ import annotations

GOLD_DERIVATIVES_EXPOSURE_DDL = """
CREATE TABLE IF NOT EXISTS gold_derivatives_exposure (
    tenant_id                 String,
    trading_account_id        String,
    -- '' when the row aggregates across markets / venues
    canonical_market_id       String DEFAULT '',
    venue_id                  String DEFAULT '',
    as_of_date                Date,
    gross_exposure            Decimal(38, 18),
    net_exposure              Decimal(38, 18),
    realized_pnl              Decimal(38, 18),
    unrealized_pnl            Decimal(38, 18),
    funding_paid              Decimal(38, 18),
    funding_received          Decimal(38, 18),
    fees_paid                 Decimal(38, 18),
    open_position_count       UInt32,
    liquidation_count         UInt32,
    accounting_method         LowCardinality(String),
    metric_version            LowCardinality(String),
    source_lineage            String,
    model_training_eligible   UInt8 DEFAULT 0,    -- financial_activity: never eligible
    materialized_at           DateTime
)
ENGINE = ReplacingMergeTree(materialized_at)
PARTITION BY toYYYYMM(as_of_date)
ORDER BY (tenant_id, trading_account_id, canonical_market_id, venue_id,
          as_of_date, metric_version)
TTL materialized_at + INTERVAL 7 YEAR
SETTINGS index_granularity = 8192;
"""
