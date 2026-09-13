"""
Aether — Gold Tier: Interoperability Path Health Schema
Daily per-provider / path delivery metrics computed from silver_interop_facts
and interop message projections. Public protocol topology metrics use the
sentinel tenant 'public'; tenant-linked context stays tenant-scoped and is
never merged into public rows.
"""

from __future__ import annotations

GOLD_INTEROP_PATHS_DDL = """
CREATE TABLE IF NOT EXISTS gold_interop_paths (
    tenant_id                     String,               -- 'public' for protocol-level rows
    provider_id                   String,
    path_id                       String,
    source_network_id             String,
    destination_network_id        String,
    as_of_date                    Date,
    message_count                 UInt64,
    source_confirmed_count        UInt64,
    verified_count                UInt64,
    delivered_count               UInt64,
    failed_count                  UInt64,
    timed_out_count               UInt64,
    recovered_count               UInt64,
    reorged_count                 UInt64,
    -- Latency percentiles in seconds (source observation -> delivery)
    delivery_latency_p50_s        Float64,
    delivery_latency_p95_s        Float64,
    delivery_success_rate         Float64,              -- 0-1
    retry_rate                    Float64,              -- attempts>1 / delivered
    security_policy_change_count  UInt32,
    fee_total                     Decimal(38, 18),
    fee_asset_id                  String DEFAULT '',
    metric_version                LowCardinality(String),
    source_lineage                String,
    model_training_eligible       UInt8 DEFAULT 0,      -- cross_chain_observability: never eligible
    materialized_at               DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(materialized_at)
PARTITION BY toYYYYMM(as_of_date)
ORDER BY (tenant_id, provider_id, path_id, as_of_date, metric_version)
TTL materialized_at + INTERVAL 7 YEAR
SETTINGS index_granularity = 8192;
"""
