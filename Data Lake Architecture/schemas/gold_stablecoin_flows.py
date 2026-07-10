"""
Aether — Gold Tier: Stablecoin Flow Aggregates Schema
Windowed stablecoin flow metrics per tenant / asset / deployment / chain,
computed from silver_stablecoin_facts (finalized observations only —
pending, reverted, and reorged activity never enters gold volume).
Historical windows are immutable: new (window, metric_version) rows are
appended; existing windows are never overwritten.
"""

from __future__ import annotations

GOLD_STABLECOIN_FLOWS_DDL = """
CREATE TABLE IF NOT EXISTS gold_stablecoin_flows (
    tenant_id                     String,
    canonical_asset_id            String,
    -- '' when the row aggregates across deployments / chains
    deployment_id                 String DEFAULT '',
    chain_id                      String DEFAULT '',
    window_start                  DateTime,
    window_end                    DateTime,
    direction                     LowCardinality(String),   -- inflow, outflow, net, internal
    -- Fixed-precision decimal strings parsed server-side; never float transit
    gross_transfer_volume         Decimal(38, 18),
    finalized_payment_volume      Decimal(38, 18),
    transfer_count                UInt64,
    unique_senders                UInt64,
    unique_recipients             UInt64,
    metric_version                LowCardinality(String),
    -- Lineage
    source_lineage                String,                   -- JSON: silver fact id range / run id
    model_training_eligible       UInt8 DEFAULT 0,          -- economic_observability: never eligible
    materialized_at               DateTime
)
ENGINE = ReplacingMergeTree(materialized_at)
PARTITION BY toYYYYMM(window_start)
ORDER BY (tenant_id, canonical_asset_id, deployment_id, chain_id,
          window_start, window_end, direction, metric_version)
TTL materialized_at + INTERVAL 7 YEAR
SETTINGS index_granularity = 8192;
"""
