-- Gold measurement tables for attribution, spend, and journey economics.
--
-- Design principles:
--   - ReplacingMergeTree on ingested_at so re-materializations are idempotent
--   - Partitioned by (tenant_id, toYYYYMM(period_date)) to enable per-tenant pruning
--     and efficient range scans; ClickHouse drops whole partitions on TTL
--   - ORDER BY chosen to serve the three primary query patterns:
--       1. Campaign dashboard: (tenant_id, campaign_id, period_date)
--       2. Attribution drill-down: (tenant_id, conversion_id)
--       3. Channel/source roll-up: (tenant_id, channel, source, period_date)
--   - PROJECTIONS materialise secondary sort orders without duplicate tables
--   - Bloom-filter SKIPPING INDEX on string columns with high cardinality but
--     selective point lookups (campaign_id, channel, source)
--   - TTL: raw fact rows retained 13 months; summary rows retained 5 years
--
-- Target SLO: p95 ≤ 2 s for standard dashboard API queries on datasets up to
-- 10M rows per tenant per month.

CREATE DATABASE IF NOT EXISTS aether_gold;

-- ─────────────────────────────────────────────────────────────────────────────
-- gold_campaign_performance_daily
--
-- One row per (tenant_id, campaign_id, period_date, channel, source).
-- Populated by gold_materializer.materialize_campaign_performance_daily().
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aether_gold.gold_campaign_performance_daily
(
    -- Identifiers
    tenant_id                   String,
    campaign_id                 String,
    ad_group_id                 String DEFAULT '',
    channel                     String DEFAULT '',
    source                      String DEFAULT '',
    platform                    String DEFAULT '',

    -- Time dimension
    period_date                 Date,

    -- Spend metrics (from spend_records)
    impressions                 UInt64 DEFAULT 0,
    clicks                      UInt64 DEFAULT 0,
    reach                       UInt64 DEFAULT 0,
    media_spend                 Decimal(18, 6) DEFAULT 0,
    total_cost                  Decimal(18, 6) DEFAULT 0,
    currency                    String DEFAULT 'USD',

    -- Attribution metrics (from attribution_credits + canonical_conversions)
    attributed_conversions      Decimal(12, 8) DEFAULT 0,
    attributed_gross_revenue    Decimal(18, 6) DEFAULT 0,
    attributed_net_revenue      Decimal(18, 6) DEFAULT 0,
    unique_converted_profiles   UInt32 DEFAULT 0,

    -- Derived metrics (computed at materialisation time)
    roas                        Nullable(Float64),   -- attributed_net_revenue / total_cost
    cpa                         Nullable(Float64),   -- total_cost / attributed_conversions
    ctr                         Nullable(Float64),   -- clicks / impressions
    cvr                         Nullable(Float64),   -- conversions / clicks

    -- Quality signals
    spend_coverage_pct          Float32 DEFAULT 0,   -- fraction of days with spend records
    attribution_coverage_pct    Float32 DEFAULT 0,
    data_freshness_ts           DateTime64(3, 'UTC') DEFAULT now64(3),

    -- Housekeeping
    ingested_at                 DateTime64(3, 'UTC') DEFAULT now64(3),
    model_type                  String DEFAULT 'last_touch',
    schema_version              UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (tenant_id, toYYYYMM(period_date))
ORDER BY (tenant_id, campaign_id, period_date, channel, source, ad_group_id)
TTL period_date + INTERVAL 13 MONTH
SETTINGS index_granularity = 4096;

-- Secondary projection: efficient channel/source roll-ups across campaigns
ALTER TABLE aether_gold.gold_campaign_performance_daily
    ADD PROJECTION IF NOT EXISTS proj_channel_rollup (
        SELECT
            tenant_id, channel, source, platform,
            period_date,
            sum(media_spend) AS media_spend,
            sum(total_cost) AS total_cost,
            sum(attributed_conversions) AS attributed_conversions,
            sum(attributed_net_revenue) AS attributed_net_revenue,
            max(ingested_at) AS ingested_at
        GROUP BY tenant_id, channel, source, platform, period_date
    );

-- Skip index: bloom filter for campaign_id point lookups
ALTER TABLE aether_gold.gold_campaign_performance_daily
    ADD INDEX IF NOT EXISTS idx_campaign_id campaign_id TYPE bloom_filter(0.01) GRANULARITY 4;

ALTER TABLE aether_gold.gold_campaign_performance_daily
    ADD INDEX IF NOT EXISTS idx_channel channel TYPE bloom_filter(0.01) GRANULARITY 4;


-- ─────────────────────────────────────────────────────────────────────────────
-- gold_attribution_credits_flat
--
-- One row per attribution credit (one per touchpoint per attribution run).
-- Enables per-touchpoint, per-channel, per-campaign credit drill-down.
-- NOT a roll-up — raw credit rows for lineage and debugging.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aether_gold.gold_attribution_credits_flat
(
    -- Credit identifiers
    credit_id                   String,
    attribution_run_id          String,
    tenant_id                   String,
    conversion_id               String,
    touchpoint_id               String DEFAULT '',

    -- Campaign dimensions
    campaign_id                 String DEFAULT '',
    ad_group_id                 String DEFAULT '',
    creative_id                 String DEFAULT '',
    ad_id                       String DEFAULT '',
    channel                     String DEFAULT '',
    source                      String DEFAULT '',

    -- Conversion metadata
    conversion_type             String DEFAULT '',
    conversion_date             Date,
    gross_value                 Decimal(18, 6) DEFAULT 0,
    net_value                   Decimal(18, 6) DEFAULT 0,
    currency                    String DEFAULT 'USD',

    -- Credit values
    credit_weight               Decimal(12, 8) DEFAULT 0,
    attributed_gross_revenue    Decimal(18, 6) DEFAULT 0,
    attributed_net_revenue      Decimal(18, 6) DEFAULT 0,

    -- Attribution model context
    model_type                  String DEFAULT 'last_touch',
    model_version               String DEFAULT '1.0',

    -- Agent/Web3 context
    agent_id                    String DEFAULT '',
    wallet_id                   String DEFAULT '',

    -- Housekeeping
    created_at                  DateTime64(3, 'UTC'),
    ingested_at                 DateTime64(3, 'UTC') DEFAULT now64(3),
    schema_version              UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (tenant_id, toYYYYMM(conversion_date))
ORDER BY (tenant_id, conversion_id, credit_id, attribution_run_id)
TTL conversion_date + INTERVAL 13 MONTH
SETTINGS index_granularity = 4096;

-- Projection: efficient campaign-level credit aggregation
ALTER TABLE aether_gold.gold_attribution_credits_flat
    ADD PROJECTION IF NOT EXISTS proj_campaign_credits (
        SELECT
            tenant_id, campaign_id, channel, source, model_type, conversion_date,
            sum(credit_weight) AS credit_weight,
            sum(attributed_net_revenue) AS attributed_net_revenue,
            count() AS credit_count
        GROUP BY tenant_id, campaign_id, channel, source, model_type, conversion_date
    );

ALTER TABLE aether_gold.gold_attribution_credits_flat
    ADD INDEX IF NOT EXISTS idx_conversion_id conversion_id TYPE bloom_filter(0.01) GRANULARITY 4;

ALTER TABLE aether_gold.gold_attribution_credits_flat
    ADD INDEX IF NOT EXISTS idx_campaign_id campaign_id TYPE bloom_filter(0.01) GRANULARITY 4;


-- ─────────────────────────────────────────────────────────────────────────────
-- gold_journey_economics
--
-- One row per journey version (active snapshot).
-- Populated by gold_materializer.materialize_journey_economics().
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aether_gold.gold_journey_economics
(
    -- Journey identifiers
    journey_id                  String,
    journey_version_id          String,
    tenant_id                   String,
    profile_id                  String DEFAULT '',
    cluster_id                  String DEFAULT '',
    account_id                  String DEFAULT '',
    wallet_id                   String DEFAULT '',

    -- Acquisition channel (from first touchpoint)
    acquisition_channel         String DEFAULT '',
    acquisition_source          String DEFAULT '',
    acquisition_campaign_id     String DEFAULT '',

    -- Journey metrics
    touchpoint_count            UInt32 DEFAULT 0,
    session_count               UInt32 DEFAULT 0,
    channel_count               UInt32 DEFAULT 0,
    days_to_conversion          Nullable(UInt32),

    -- Revenue metrics
    total_gross_revenue         Decimal(18, 6) DEFAULT 0,
    total_net_revenue           Decimal(18, 6) DEFAULT 0,
    total_refunds               Decimal(18, 6) DEFAULT 0,
    conversion_count            UInt32 DEFAULT 0,
    currency                    String DEFAULT 'USD',

    -- LTV (subscription journeys)
    subscription_ltv            Decimal(18, 6) DEFAULT 0,
    renewal_count               UInt32 DEFAULT 0,
    is_subscription             UInt8 DEFAULT 0,

    -- Time dimensions
    journey_started_date        Date,
    first_conversion_date       Nullable(Date),
    latest_conversion_date      Nullable(Date),

    -- Housekeeping
    compiled_at                 DateTime64(3, 'UTC'),
    ingested_at                 DateTime64(3, 'UTC') DEFAULT now64(3),
    compiler_version            String DEFAULT '1.0',
    schema_version              UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (tenant_id, toYYYYMM(journey_started_date))
ORDER BY (tenant_id, journey_id, journey_version_id)
TTL journey_started_date + INTERVAL 5 YEAR
SETTINGS index_granularity = 4096;

ALTER TABLE aether_gold.gold_journey_economics
    ADD INDEX IF NOT EXISTS idx_profile_id profile_id TYPE bloom_filter(0.01) GRANULARITY 4;

ALTER TABLE aether_gold.gold_journey_economics
    ADD INDEX IF NOT EXISTS idx_acq_campaign acquisition_campaign_id TYPE bloom_filter(0.01) GRANULARITY 4;


-- ─────────────────────────────────────────────────────────────────────────────
-- gold_spend_daily
--
-- One row per (tenant_id, platform, campaign_id, period_date).
-- Populated directly from spend_records with currency normalization.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aether_gold.gold_spend_daily
(
    tenant_id                   String,
    platform                    String,
    ad_account_id               String DEFAULT '',
    campaign_id                 String DEFAULT '',
    ad_group_id                 String DEFAULT '',

    period_date                 Date,
    billing_currency            String DEFAULT 'USD',

    impressions                 UInt64 DEFAULT 0,
    reach                       UInt64 DEFAULT 0,
    clicks                      UInt64 DEFAULT 0,
    media_spend                 Decimal(18, 6) DEFAULT 0,
    platform_fees               Decimal(18, 6) DEFAULT 0,
    total_cost                  Decimal(18, 6) DEFAULT 0,

    record_count                UInt32 DEFAULT 1,
    source_connector_id         String DEFAULT '',
    ingested_at                 DateTime64(3, 'UTC') DEFAULT now64(3),
    schema_version              UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY (tenant_id, toYYYYMM(period_date))
ORDER BY (tenant_id, platform, campaign_id, period_date, ad_group_id)
TTL period_date + INTERVAL 13 MONTH
SETTINGS index_granularity = 4096;

ALTER TABLE aether_gold.gold_spend_daily
    ADD INDEX IF NOT EXISTS idx_campaign_id campaign_id TYPE bloom_filter(0.01) GRANULARITY 4;


-- ─────────────────────────────────────────────────────────────────────────────
-- gold_incrementality_results
--
-- One row per experiment analysis (idempotent on experiment_id + analyzed_at).
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aether_gold.gold_incrementality_results
(
    experiment_id               String,
    tenant_id                   String,
    experiment_type             String DEFAULT '',
    primary_metric              String DEFAULT '',

    -- Cell sizes
    treatment_assignments       UInt32 DEFAULT 0,
    control_assignments         UInt32 DEFAULT 0,
    treatment_conversions       UInt32 DEFAULT 0,
    control_conversions         UInt32 DEFAULT 0,

    -- Incremental metrics (always labeled incremental_* per anti-conflation rule)
    incremental_lift_pct        Float64 DEFAULT 0,
    incremental_revenue         Decimal(18, 6) DEFAULT 0,
    z_score                     Float64 DEFAULT 0,
    p_value                     Float64 DEFAULT 1,
    statistical_significance_threshold Float64 DEFAULT 0.05,
    is_statistically_significant UInt8 DEFAULT 0,

    -- Period
    experiment_start_date       Nullable(Date),
    experiment_end_date         Nullable(Date),
    analyzed_at                 DateTime64(3, 'UTC'),

    ingested_at                 DateTime64(3, 'UTC') DEFAULT now64(3),
    schema_version              UInt8 DEFAULT 1
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY tenant_id
ORDER BY (tenant_id, experiment_id, analyzed_at)
TTL analyzed_at + INTERVAL 5 YEAR
SETTINGS index_granularity = 4096;
