// =============================================================================
// Aether DATA LAKE — TABLE DEFINITIONS
// Complete schema for all medallion tiers:
//   Bronze: Raw ingested events (append-only, JSONL on S3)
//   Silver: Cleaned, deduplicated, enriched events (Parquet on S3 + ClickHouse)
//   Gold:   Aggregated metrics, materialized views, feature tables
// =============================================================================

import type { TableDefinition, TierConfig, ColumnDefinition } from './types.js';

// =============================================================================
// TIER CONFIGURATION
// =============================================================================

export const TIER_CONFIGS: Record<string, TierConfig> = {
  bronze: {
    tier: 'bronze',
    bucket: process.env.S3_BRONZE_BUCKET ?? 'aether-data-lake-bronze',
    prefix: 'events/',
    format: 'jsonl',
    compression: 'gzip',
    partitionScheme: {
      timeColumn: 'received_at',
      granularity: 'hour',
      extraColumns: ['project_id'],
    },
    retentionDays: 90,
    compactionEnabled: true,
    compactionTargetSizeMb: 128,
    qualityChecksEnabled: true,
  },

  silver: {
    tier: 'silver',
    bucket: process.env.S3_SILVER_BUCKET ?? 'aether-data-lake-silver',
    prefix: 'events/',
    format: 'parquet',
    compression: 'snappy',
    partitionScheme: {
      timeColumn: 'event_timestamp',
      granularity: 'day',
      extraColumns: ['project_id', 'event_type'],
    },
    retentionDays: 365,
    compactionEnabled: true,
    compactionTargetSizeMb: 256,
    qualityChecksEnabled: true,
  },

  gold: {
    tier: 'gold',
    bucket: process.env.S3_GOLD_BUCKET ?? 'aether-data-lake-gold',
    prefix: 'aggregates/',
    format: 'parquet',
    compression: 'zstd',
    partitionScheme: {
      timeColumn: 'period_start',
      granularity: 'day',
      extraColumns: ['project_id'],
    },
    retentionDays: 730,
    compactionEnabled: false,
    compactionTargetSizeMb: 512,
    qualityChecksEnabled: true,
  },
};

// =============================================================================
// BRONZE: RAW EVENTS (mirrors EnrichedEvent exactly)
// =============================================================================

export const BRONZE_EVENTS: TableDefinition = {
  name: 'bronze_events',
  tier: 'bronze',
  description: 'Raw ingested events from all SDKs, append-only with minimal transformation',
  engine: 'MergeTree',
  partitionBy: "toYYYYMM(received_at)",
  orderBy: ['project_id', 'received_at', 'event_id'],
  ttlDays: 90,
  settings: { index_granularity: 8192 },
  columns: [
    { name: 'event_id',         type: 'UUID',                     description: 'SDK-generated unique event ID',               nullable: false, isSortKey: true, sortKeyOrder: 3 },
    { name: 'event_type',       type: 'LowCardinality(String)',   description: 'Event type (track, page, identify, ...)',      nullable: false },
    { name: 'event_name',       type: 'String',                   description: 'Custom event name for track events',           nullable: true },
    { name: 'project_id',       type: 'String',                   description: 'Project/workspace ID from API key',            nullable: false, isPartitionKey: true, isSortKey: true, sortKeyOrder: 1 },
    { name: 'anonymous_id',     type: 'String',                   description: 'SDK-generated anonymous device ID',            nullable: false },
    { name: 'user_id',          type: 'Nullable(String)',         description: 'Authenticated user ID (from identify/hydrate)', nullable: true },
    { name: 'session_id',       type: 'String',                   description: 'Session ID from SDK session manager',          nullable: false },

    // Timestamps
    { name: 'event_timestamp',  type: 'DateTime64',               description: 'Client-side event timestamp (ISO 8601)',       nullable: false },
    { name: 'received_at',      type: 'DateTime64',               description: 'Server receive timestamp',                     nullable: false, isSortKey: true, sortKeyOrder: 2 },
    { name: 'sent_at',          type: 'Nullable(DateTime64)',     description: 'Batch sent timestamp from SDK',                nullable: true },

    // Properties (stored as JSON blob in bronze)
    { name: 'properties',       type: 'String',                   description: 'Event properties JSON',                        nullable: false, defaultExpr: "'{}'" },

    // Context: Page
    { name: 'page_url',         type: 'String',                   description: 'Full page URL',                                nullable: true },
    { name: 'page_path',        type: 'String',                   description: 'URL path component',                           nullable: true },
    { name: 'page_title',       type: 'Nullable(String)',         description: 'Document title',                               nullable: true },
    { name: 'page_referrer',    type: 'String',                   description: 'HTTP referrer',                                nullable: true },
    { name: 'page_search',      type: 'Nullable(String)',         description: 'URL query string',                             nullable: true },

    // Context: Device
    { name: 'device_type',      type: 'LowCardinality(String)',   description: 'desktop | mobile | tablet',                    nullable: true },
    { name: 'browser',          type: 'LowCardinality(String)',   description: 'Browser name',                                 nullable: true },
    { name: 'browser_version',  type: 'Nullable(String)',         description: 'Browser version',                              nullable: true },
    { name: 'os',               type: 'LowCardinality(String)',   description: 'Operating system',                             nullable: true },
    { name: 'os_version',       type: 'Nullable(String)',         description: 'OS version',                                   nullable: true },
    { name: 'screen_width',     type: 'Nullable(UInt16)',         description: 'Screen width px',                              nullable: true },
    { name: 'screen_height',    type: 'Nullable(UInt16)',         description: 'Screen height px',                             nullable: true },
    { name: 'viewport_width',   type: 'Nullable(UInt16)',         description: 'Viewport width px',                            nullable: true },
    { name: 'viewport_height',  type: 'Nullable(UInt16)',         description: 'Viewport height px',                           nullable: true },
    { name: 'pixel_ratio',      type: 'Nullable(Float32)',        description: 'Device pixel ratio',                           nullable: true },
    { name: 'language',         type: 'LowCardinality(String)',   description: 'Browser/device language',                      nullable: true },

    // Context: Campaign / UTM
    { name: 'utm_source',       type: 'Nullable(String)',         description: 'UTM source parameter',                         nullable: true },
    { name: 'utm_medium',       type: 'Nullable(String)',         description: 'UTM medium parameter',                         nullable: true },
    { name: 'utm_campaign',     type: 'Nullable(String)',         description: 'UTM campaign parameter',                       nullable: true },
    { name: 'utm_content',      type: 'Nullable(String)',         description: 'UTM content parameter',                        nullable: true },
    { name: 'utm_term',         type: 'Nullable(String)',         description: 'UTM term parameter',                           nullable: true },
    { name: 'click_id',         type: 'Nullable(String)',         description: 'Ad click ID (gclid, fbclid, msclkid)',         nullable: true },
    { name: 'referrer_domain',  type: 'Nullable(String)',         description: 'Referrer hostname',                            nullable: true },
    { name: 'referrer_type',    type: 'LowCardinality(String)',   description: 'Referrer classification',                      nullable: true },

    // Enrichment: Geo
    { name: 'country_code',     type: 'LowCardinality(String)',   description: 'ISO 3166-1 alpha-2 country code',              nullable: true },
    { name: 'region',           type: 'Nullable(String)',         description: 'State/region name',                            nullable: true },
    { name: 'city',             type: 'Nullable(String)',         description: 'City name',                                    nullable: true },
    { name: 'latitude',         type: 'Nullable(Float64)',        description: 'Approximate latitude',                         nullable: true },
    { name: 'longitude',        type: 'Nullable(Float64)',        description: 'Approximate longitude',                        nullable: true },
    { name: 'timezone',         type: 'Nullable(String)',         description: 'IANA timezone',                                nullable: true },

    // Enrichment: Metadata
    { name: 'ip_anonymized',    type: 'Nullable(String)',         description: 'Anonymized IP address',                        nullable: true },
    { name: 'bot_probability',  type: 'Nullable(Float32)',        description: 'Server-side bot detection score 0-1',          nullable: true },
    { name: 'pipeline_version', type: 'LowCardinality(String)',   description: 'Ingestion pipeline version',                   nullable: true },
    { name: 'sdk_name',         type: 'LowCardinality(String)',   description: 'SDK library name',                             nullable: true },
    { name: 'sdk_version',      type: 'LowCardinality(String)',   description: 'SDK library version',                          nullable: true },

    // Consent
    { name: 'consent_analytics', type: 'Nullable(Bool)',          description: 'Analytics consent granted',                    nullable: true },
    { name: 'consent_marketing', type: 'Nullable(Bool)',          description: 'Marketing consent granted',                    nullable: true },
    { name: 'consent_web3',      type: 'Nullable(Bool)',          description: 'Web3 consent granted',                         nullable: true },

    // Partition key
    { name: 'partition_key',    type: 'String',                   description: 'Hash partition key for Kafka routing',          nullable: false },
  ],
};

// =============================================================================
// SILVER: CLEANED, DEDUPLICATED EVENTS
// =============================================================================

export const SILVER_EVENTS: TableDefinition = {
  name: 'silver_events',
  tier: 'silver',
  description: 'Cleaned, deduplicated, and sessionized events with extracted properties',
  engine: 'ReplacingMergeTree',  // Dedup on event_id
  partitionBy: "toYYYYMM(event_timestamp)",
  orderBy: ['project_id', 'event_timestamp', 'event_id'],
  ttlDays: 365,
  settings: { index_granularity: 8192 },
  columns: [
    // Core identifiers (same as bronze but deduplicated)
    { name: 'event_id',          type: 'UUID',                    description: 'Deduplicated event ID',                        nullable: false, isSortKey: true, sortKeyOrder: 3 },
    { name: 'event_type',        type: 'LowCardinality(String)',  description: 'Normalized event type',                        nullable: false },
    { name: 'event_name',        type: 'String',                  description: 'Custom event name',                            nullable: true },
    { name: 'project_id',        type: 'String',                  description: 'Project ID',                                   nullable: false, isSortKey: true, sortKeyOrder: 1 },
    { name: 'anonymous_id',      type: 'String',                  description: 'Anonymous ID',                                 nullable: false },
    { name: 'user_id',           type: 'Nullable(String)',        description: 'Resolved user ID',                             nullable: true },
    { name: 'session_id',        type: 'String',                  description: 'Session ID',                                   nullable: false },

    // Resolved identity (from identity graph)
    { name: 'resolved_user_id',  type: 'Nullable(String)',        description: 'Identity-resolved canonical user ID',          nullable: true },
    { name: 'identity_cluster',  type: 'Nullable(String)',        description: 'Identity cluster hash',                        nullable: true },

    // Timestamps
    { name: 'event_timestamp',   type: 'DateTime64',              description: 'Client event timestamp (validated)',            nullable: false, isSortKey: true, sortKeyOrder: 2 },
    { name: 'received_at',       type: 'DateTime64',              description: 'Server receive timestamp',                     nullable: false },
    { name: 'processed_at',      type: 'DateTime64',              description: 'Silver ETL processing timestamp',              nullable: false },
    { name: 'ingestion_lag_ms',  type: 'UInt32',                  description: 'Delay from event to server receipt (ms)',       nullable: false, defaultExpr: '0' },

    // Extracted typed properties (from JSON → columns)
    { name: 'conversion_value',  type: 'Nullable(Float64)',       description: 'Monetary conversion value',                    nullable: true },
    { name: 'conversion_currency', type: 'Nullable(String)',      description: 'ISO 4217 currency code',                       nullable: true },
    { name: 'order_id',          type: 'Nullable(String)',        description: 'E-commerce order ID',                          nullable: true },
    { name: 'error_message',     type: 'Nullable(String)',        description: 'Error event message',                          nullable: true },
    { name: 'error_type',        type: 'Nullable(String)',        description: 'Error classification',                         nullable: true },

    // Web vitals (extracted from performance events)
    { name: 'lcp_ms',            type: 'Nullable(Float32)',       description: 'Largest Contentful Paint (ms)',                 nullable: true },
    { name: 'fid_ms',            type: 'Nullable(Float32)',       description: 'First Input Delay (ms)',                        nullable: true },
    { name: 'cls',               type: 'Nullable(Float32)',       description: 'Cumulative Layout Shift',                       nullable: true },
    { name: 'ttfb_ms',           type: 'Nullable(Float32)',       description: 'Time to First Byte (ms)',                       nullable: true },
    { name: 'fcp_ms',            type: 'Nullable(Float32)',       description: 'First Contentful Paint (ms)',                   nullable: true },

    // Web3 fields (extracted from wallet/transaction events)
    { name: 'wallet_address',    type: 'Nullable(String)',        description: 'Connected wallet address',                      nullable: true },
    { name: 'wallet_type',       type: 'Nullable(String)',        description: 'Wallet provider (MetaMask, etc)',               nullable: true },
    { name: 'chain_id',          type: 'Nullable(UInt32)',        description: 'Blockchain chain ID',                           nullable: true },
    { name: 'tx_hash',           type: 'Nullable(String)',        description: 'On-chain transaction hash',                     nullable: true },
    { name: 'tx_value',          type: 'Nullable(String)',        description: 'Transaction value (wei/native)',                nullable: true },
    { name: 'tx_status',         type: 'Nullable(String)',        description: 'Transaction status',                            nullable: true },

    // Experiment fields
    { name: 'experiment_id',     type: 'Nullable(String)',        description: 'A/B experiment identifier',                     nullable: true },
    { name: 'variant_id',        type: 'Nullable(String)',        description: 'Assigned experiment variant',                   nullable: true },

    // Remaining properties (overflow JSON)
    { name: 'properties_json',   type: 'String',                  description: 'Non-extracted properties as JSON',              nullable: false, defaultExpr: "'{}'" },

    // Page context (carried forward)
    { name: 'page_url',          type: 'String',                  description: 'Page URL',                                      nullable: true },
    { name: 'page_path',         type: 'String',                  description: 'URL path',                                      nullable: true },
    { name: 'page_title',        type: 'Nullable(String)',        description: 'Page title',                                    nullable: true },
    { name: 'referrer',          type: 'String',                  description: 'Referrer URL',                                  nullable: true },

    // Device (carried forward, normalized)
    { name: 'device_type',       type: 'LowCardinality(String)',  description: 'Device type',                                   nullable: true },
    { name: 'browser',           type: 'LowCardinality(String)',  description: 'Browser',                                       nullable: true },
    { name: 'os',                type: 'LowCardinality(String)',  description: 'Operating system',                              nullable: true },
    { name: 'screen_resolution', type: 'Nullable(String)',        description: 'WxH screen resolution',                         nullable: true },
    { name: 'language',          type: 'LowCardinality(String)',  description: 'Language',                                       nullable: true },

    // Campaign (carried forward)
    { name: 'utm_source',        type: 'Nullable(String)',        description: 'UTM source',                                    nullable: true },
    { name: 'utm_medium',        type: 'Nullable(String)',        description: 'UTM medium',                                    nullable: true },
    { name: 'utm_campaign',      type: 'Nullable(String)',        description: 'UTM campaign',                                  nullable: true },
    { name: 'referrer_type',     type: 'LowCardinality(String)',  description: 'Referrer type',                                 nullable: true },

    // Geo (carried forward)
    { name: 'country_code',      type: 'LowCardinality(String)',  description: 'Country code',                                  nullable: true },
    { name: 'region',            type: 'Nullable(String)',        description: 'Region',                                         nullable: true },
    { name: 'city',              type: 'Nullable(String)',        description: 'City',                                           nullable: true },
    { name: 'timezone',          type: 'Nullable(String)',        description: 'Timezone',                                       nullable: true },

    // Bot filtering
    { name: 'is_bot',            type: 'Bool',                    description: 'Flagged as bot traffic',                         nullable: false, defaultExpr: 'false' },
    { name: 'bot_probability',   type: 'Nullable(Float32)',       description: 'Bot probability score',                          nullable: true },

    // Data quality
    { name: 'dq_flags',          type: 'Array(String)',           description: 'Data quality flags (late_arrival, clock_skew)', nullable: false, defaultExpr: '[]' },
  ],
};

// =============================================================================
// SILVER: SESSION TABLE (sessionized from events)
// =============================================================================

export const SILVER_SESSIONS: TableDefinition = {
  name: 'silver_sessions',
  tier: 'silver',
  description: 'Sessionized aggregates: one row per session with engagement metrics',
  engine: 'ReplacingMergeTree',
  partitionBy: "toYYYYMM(session_start)",
  orderBy: ['project_id', 'session_start', 'session_id'],
  ttlDays: 365,
  columns: [
    { name: 'session_id',         type: 'String',                  description: 'Session ID',                           nullable: false, isSortKey: true, sortKeyOrder: 3 },
    { name: 'project_id',         type: 'String',                  description: 'Project ID',                           nullable: false, isSortKey: true, sortKeyOrder: 1 },
    { name: 'anonymous_id',       type: 'String',                  description: 'Anonymous ID',                         nullable: false },
    { name: 'user_id',            type: 'Nullable(String)',        description: 'User ID (if identified)',              nullable: true },
    { name: 'resolved_user_id',   type: 'Nullable(String)',        description: 'Identity-resolved user ID',           nullable: true },

    // Session boundaries
    { name: 'session_start',      type: 'DateTime64',              description: 'First event timestamp',                nullable: false, isSortKey: true, sortKeyOrder: 2 },
    { name: 'session_end',        type: 'DateTime64',              description: 'Last event timestamp',                 nullable: false },
    { name: 'duration_seconds',   type: 'UInt32',                  description: 'Session duration in seconds',          nullable: false },

    // Engagement metrics
    { name: 'event_count',        type: 'UInt32',                  description: 'Total events in session',              nullable: false },
    { name: 'page_view_count',    type: 'UInt16',                  description: 'Page views',                           nullable: false },
    { name: 'track_event_count',  type: 'UInt16',                  description: 'Custom track events',                  nullable: false },
    { name: 'conversion_count',   type: 'UInt16',                  description: 'Conversion events',                    nullable: false },
    { name: 'error_count',        type: 'UInt16',                  description: 'Error events',                         nullable: false },
    { name: 'total_revenue',      type: 'Float64',                 description: 'Sum of conversion values',             nullable: false, defaultExpr: '0' },

    // Navigation
    { name: 'landing_page',       type: 'String',                  description: 'First page URL',                       nullable: true },
    { name: 'exit_page',          type: 'String',                  description: 'Last page URL',                        nullable: true },
    { name: 'unique_pages',       type: 'UInt16',                  description: 'Distinct pages visited',               nullable: false },
    { name: 'bounce',             type: 'Bool',                    description: 'Single page session',                  nullable: false },

    // Attribution
    { name: 'utm_source',         type: 'Nullable(String)',        description: 'Session UTM source',                   nullable: true },
    { name: 'utm_medium',         type: 'Nullable(String)',        description: 'Session UTM medium',                   nullable: true },
    { name: 'utm_campaign',       type: 'Nullable(String)',        description: 'Session UTM campaign',                 nullable: true },
    { name: 'referrer_type',      type: 'LowCardinality(String)',  description: 'How user arrived',                     nullable: true },
    { name: 'referrer_domain',    type: 'Nullable(String)',        description: 'Referrer hostname',                    nullable: true },

    // Device / Geo
    { name: 'device_type',        type: 'LowCardinality(String)',  description: 'Device type',                          nullable: true },
    { name: 'browser',            type: 'LowCardinality(String)',  description: 'Browser',                              nullable: true },
    { name: 'os',                 type: 'LowCardinality(String)',  description: 'OS',                                   nullable: true },
    { name: 'country_code',       type: 'LowCardinality(String)',  description: 'Country',                              nullable: true },
    { name: 'city',               type: 'Nullable(String)',        description: 'City',                                 nullable: true },

    // Performance (session-level averages)
    { name: 'avg_lcp_ms',         type: 'Nullable(Float32)',       description: 'Average LCP across session pages',     nullable: true },
    { name: 'avg_cls',            type: 'Nullable(Float32)',       description: 'Average CLS across session pages',     nullable: true },

    // Web3
    { name: 'has_wallet',         type: 'Bool',                    description: 'Wallet connected during session',      nullable: false, defaultExpr: 'false' },
    { name: 'wallet_address',     type: 'Nullable(String)',        description: 'Connected wallet address',             nullable: true },
    { name: 'transaction_count',  type: 'UInt16',                  description: 'On-chain transactions',                nullable: false, defaultExpr: '0' },

    // Bot
    { name: 'is_bot',             type: 'Bool',                    description: 'Session flagged as bot',               nullable: false, defaultExpr: 'false' },

    // ETL metadata
    { name: 'processed_at',       type: 'DateTime64',              description: 'Session table build timestamp',        nullable: false },
  ],
};

// =============================================================================
// GOLD: DAILY PROJECT METRICS
// =============================================================================

export const GOLD_DAILY_METRICS: TableDefinition = {
  name: 'gold_daily_metrics',
  tier: 'gold',
  description: 'Daily aggregated KPIs per project — dashboard primary data source',
  engine: 'SummingMergeTree',
  partitionBy: "toYYYYMM(metric_date)",
  orderBy: ['project_id', 'metric_date'],
  ttlDays: 730,
  columns: [
    { name: 'project_id',          type: 'String',   description: 'Project ID',                         nullable: false, isSortKey: true, sortKeyOrder: 1 },
    { name: 'metric_date',         type: 'Date',     description: 'Metric date (UTC)',                  nullable: false, isSortKey: true, sortKeyOrder: 2 },

    // Traffic
    { name: 'unique_visitors',     type: 'UInt32',   description: 'Unique anonymous IDs',               nullable: false },
    { name: 'unique_users',        type: 'UInt32',   description: 'Unique identified users',            nullable: false },
    { name: 'total_sessions',      type: 'UInt32',   description: 'Total sessions',                     nullable: false },
    { name: 'new_visitors',        type: 'UInt32',   description: 'First-time anonymous IDs',           nullable: false },
    { name: 'returning_visitors',  type: 'UInt32',   description: 'Returning anonymous IDs',            nullable: false },

    // Engagement
    { name: 'total_events',        type: 'UInt64',   description: 'Total events ingested',              nullable: false },
    { name: 'total_page_views',    type: 'UInt32',   description: 'Total page views',                   nullable: false },
    { name: 'total_track_events',  type: 'UInt32',   description: 'Custom track events',                nullable: false },
    { name: 'avg_session_duration_s', type: 'Float32', description: 'Average session duration seconds', nullable: false },
    { name: 'avg_pages_per_session',  type: 'Float32', description: 'Average pages per session',        nullable: false },
    { name: 'bounce_rate',         type: 'Float32',  description: 'Bounce rate (0-1)',                  nullable: false },

    // Conversions
    { name: 'total_conversions',   type: 'UInt32',   description: 'Total conversion events',            nullable: false },
    { name: 'total_revenue',       type: 'Float64',  description: 'Total conversion revenue',           nullable: false },
    { name: 'conversion_rate',     type: 'Float32',  description: 'Session conversion rate (0-1)',      nullable: false },
    { name: 'avg_order_value',     type: 'Float64',  description: 'Average order value',                nullable: false },

    // Performance
    { name: 'avg_lcp_ms',          type: 'Float32',  description: 'Average LCP (ms)',                   nullable: false },
    { name: 'avg_fid_ms',          type: 'Float32',  description: 'Average FID (ms)',                   nullable: false },
    { name: 'avg_cls',             type: 'Float32',  description: 'Average CLS',                        nullable: false },
    { name: 'avg_ttfb_ms',        type: 'Float32',  description: 'Average TTFB (ms)',                  nullable: false },

    // Errors
    { name: 'total_errors',        type: 'UInt32',   description: 'Total error events',                 nullable: false },
    { name: 'error_rate',          type: 'Float32',  description: 'Errors per session',                 nullable: false },

    // Web3
    { name: 'wallet_connections',  type: 'UInt32',   description: 'Unique wallets connected',           nullable: false },
    { name: 'on_chain_txs',       type: 'UInt32',   description: 'On-chain transactions tracked',      nullable: false },
    { name: 'on_chain_volume',    type: 'Float64',  description: 'Total on-chain value (USD est.)',    nullable: false },

    // Bot
    { name: 'bot_sessions',        type: 'UInt32',   description: 'Sessions flagged as bot',            nullable: false },
    { name: 'bot_rate',            type: 'Float32',  description: 'Bot traffic ratio',                  nullable: false },

    // ETL
    { name: 'processed_at',        type: 'DateTime64', description: 'Gold table build timestamp',       nullable: false },
  ],
};

// =============================================================================
// GOLD: FUNNEL STAGE METRICS
// =============================================================================

export const GOLD_FUNNEL_METRICS: TableDefinition = {
  name: 'gold_funnel_metrics',
  tier: 'gold',
  description: 'Daily funnel conversion metrics by step, for funnel analysis dashboards',
  engine: 'SummingMergeTree',
  partitionBy: "toYYYYMM(metric_date)",
  orderBy: ['project_id', 'funnel_id', 'metric_date', 'step_index'],
  columns: [
    { name: 'project_id',     type: 'String',                  description: 'Project ID',             nullable: false, isSortKey: true, sortKeyOrder: 1 },
    { name: 'funnel_id',      type: 'String',                  description: 'Funnel definition ID',   nullable: false, isSortKey: true, sortKeyOrder: 2 },
    { name: 'metric_date',    type: 'Date',                    description: 'Metric date',            nullable: false, isSortKey: true, sortKeyOrder: 3 },
    { name: 'step_index',     type: 'UInt8',                   description: 'Funnel step position',   nullable: false, isSortKey: true, sortKeyOrder: 4 },
    { name: 'step_name',      type: 'String',                  description: 'Funnel step name',       nullable: false },
    { name: 'entered_count',  type: 'UInt32',                  description: 'Users entering step',    nullable: false },
    { name: 'completed_count', type: 'UInt32',                 description: 'Users completing step',  nullable: false },
    { name: 'drop_off_count', type: 'UInt32',                  description: 'Users dropping off',     nullable: false },
    { name: 'avg_time_to_complete_s', type: 'Float32',         description: 'Average time in step',   nullable: false },
    { name: 'conversion_rate', type: 'Float32',                description: 'Step conversion rate',   nullable: false },
    { name: 'processed_at',   type: 'DateTime64',              description: 'Build timestamp',        nullable: false },
  ],
};

// =============================================================================
// GOLD: ATTRIBUTION TABLE
// =============================================================================

export const GOLD_ATTRIBUTION: TableDefinition = {
  name: 'gold_attribution',
  tier: 'gold',
  description: 'Multi-touch campaign attribution results per project per day',
  engine: 'ReplacingMergeTree',
  partitionBy: "toYYYYMM(metric_date)",
  orderBy: ['project_id', 'metric_date', 'channel', 'campaign'],
  columns: [
    { name: 'project_id',          type: 'String',                  description: 'Project ID',                     nullable: false, isSortKey: true, sortKeyOrder: 1 },
    { name: 'metric_date',         type: 'Date',                    description: 'Metric date',                    nullable: false, isSortKey: true, sortKeyOrder: 2 },
    { name: 'channel',             type: 'LowCardinality(String)',  description: 'Marketing channel',              nullable: false, isSortKey: true, sortKeyOrder: 3 },
    { name: 'campaign',            type: 'String',                  description: 'Campaign name',                  nullable: false, isSortKey: true, sortKeyOrder: 4 },
    { name: 'source',              type: 'Nullable(String)',        description: 'UTM source',                     nullable: true },
    { name: 'medium',              type: 'Nullable(String)',        description: 'UTM medium',                     nullable: true },

    // Attribution models
    { name: 'first_touch_conversions',  type: 'UInt32',   description: 'First-touch conversions',       nullable: false },
    { name: 'first_touch_revenue',      type: 'Float64',  description: 'First-touch revenue',           nullable: false },
    { name: 'last_touch_conversions',   type: 'UInt32',   description: 'Last-touch conversions',        nullable: false },
    { name: 'last_touch_revenue',       type: 'Float64',  description: 'Last-touch revenue',            nullable: false },
    { name: 'linear_conversions',       type: 'Float64',  description: 'Linear attribution fractional', nullable: false },
    { name: 'linear_revenue',           type: 'Float64',  description: 'Linear attribution revenue',    nullable: false },
    { name: 'shapley_conversions',      type: 'Float64',  description: 'Shapley value conversions',     nullable: false },
    { name: 'shapley_revenue',          type: 'Float64',  description: 'Shapley value revenue',         nullable: false },

    // Volume
    { name: 'touchpoint_count',    type: 'UInt32',   description: 'Total touchpoints',              nullable: false },
    { name: 'unique_users',        type: 'UInt32',   description: 'Unique users in channel',        nullable: false },

    { name: 'processed_at',        type: 'DateTime64', description: 'Build timestamp',              nullable: false },
  ],
};

// =============================================================================
// GOLD: USER FEATURE TABLE (for ML model serving)
// =============================================================================

export const GOLD_USER_FEATURES: TableDefinition = {
  name: 'gold_user_features',
  tier: 'gold',
  description: 'Pre-computed user feature vectors for ML model serving (churn, LTV, intent)',
  engine: 'ReplacingMergeTree',
  partitionBy: "toYYYYMM(computed_at)",
  orderBy: ['project_id', 'anonymous_id'],
  columns: [
    { name: 'project_id',              type: 'String',            description: 'Project ID',                     nullable: false, isSortKey: true, sortKeyOrder: 1 },
    { name: 'anonymous_id',            type: 'String',            description: 'Anonymous ID',                   nullable: false, isSortKey: true, sortKeyOrder: 2 },
    { name: 'user_id',                 type: 'Nullable(String)',  description: 'Identified user ID',             nullable: true },
    { name: 'computed_at',             type: 'DateTime64',        description: 'Feature computation timestamp',  nullable: false },

    // Behavioral features
    { name: 'total_sessions',          type: 'UInt32',            description: 'Lifetime session count',         nullable: false },
    { name: 'days_since_first_visit',  type: 'UInt16',            description: 'Tenure in days',                 nullable: false },
    { name: 'days_since_last_visit',   type: 'UInt16',            description: 'Recency in days',                nullable: false },
    { name: 'avg_session_duration',    type: 'Float32',           description: 'Avg session seconds',            nullable: false },
    { name: 'visit_frequency_7d',      type: 'Float32',           description: 'Sessions per day (7d window)',   nullable: false },
    { name: 'visit_frequency_30d',     type: 'Float32',           description: 'Sessions per day (30d window)',  nullable: false },
    { name: 'visit_frequency_trend',   type: 'Float32',           description: '30d vs 7d frequency ratio',      nullable: false },
    { name: 'feature_usage_breadth',   type: 'Float32',           description: 'Distinct events / total types',  nullable: false },
    { name: 'engagement_percentile',   type: 'Float32',           description: 'Engagement score (0-1)',         nullable: false },

    // Conversion features
    { name: 'total_conversions',       type: 'UInt16',            description: 'Lifetime conversions',           nullable: false },
    { name: 'conversion_rate',         type: 'Float32',           description: 'Session conversion rate',        nullable: false },
    { name: 'purchase_frequency',      type: 'Float32',           description: 'Purchases per 30 days',          nullable: false },
    { name: 'monetary_total',          type: 'Float64',           description: 'Lifetime revenue',               nullable: false },
    { name: 'monetary_mean',           type: 'Float64',           description: 'Average order value',            nullable: false },
    { name: 'recency_days',            type: 'UInt16',            description: 'Days since last purchase',        nullable: false },

    // Web3 features
    { name: 'web3_tx_count',           type: 'UInt16',            description: 'On-chain transaction count',      nullable: false, defaultExpr: '0' },
    { name: 'web3_total_value',        type: 'Float64',           description: 'Cumulative on-chain value',       nullable: false, defaultExpr: '0' },
    { name: 'has_wallet',              type: 'Bool',              description: 'Has connected wallet',             nullable: false, defaultExpr: 'false' },

    // Acquisition
    { name: 'acquisition_channel',     type: 'LowCardinality(String)', description: 'First session channel',    nullable: true },
    { name: 'acquisition_channel_score', type: 'Float32',         description: 'Channel quality score',           nullable: false, defaultExpr: '0' },

    // ML predictions (cached)
    { name: 'churn_probability',       type: 'Nullable(Float32)', description: 'Latest churn model prediction',  nullable: true },
    { name: 'ltv_30d',                 type: 'Nullable(Float64)', description: 'Predicted 30d LTV',              nullable: true },
    { name: 'ltv_365d',               type: 'Nullable(Float64)', description: 'Predicted 365d LTV',             nullable: true },
  ],
};

// =============================================================================
// ALL TABLES REGISTRY
// =============================================================================

export const ALL_TABLES: TableDefinition[] = [
  BRONZE_EVENTS,
  SILVER_EVENTS,
  SILVER_SESSIONS,
  GOLD_DAILY_METRICS,
  GOLD_FUNNEL_METRICS,
  GOLD_ATTRIBUTION,
  GOLD_USER_FEATURES,
];

/** Get all tables for a given tier */
export function getTablesByTier(tier: string): TableDefinition[] {
  return ALL_TABLES.filter(t => t.tier === tier);
}
