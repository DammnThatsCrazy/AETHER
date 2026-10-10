-- CIS Generation Telemetry
-- Stores per-generation claim extraction and grounding analytics.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_generation_telemetry
(
    event_id           String,
    tenant_id          String,
    timestamp          DateTime64(3, 'UTC'),
    generation_id      String,
    model_name         String DEFAULT '',
    claim_count        UInt16,
    grounded_claims    UInt16,
    ungrounded_claims  UInt16,
    grounding_ratio    Float32,
    confidence_curve   Array(Float32),
    generation_hash    String DEFAULT '',
    latency_ms         Float32 DEFAULT 0,
    source_service     String DEFAULT ''
) ENGINE = ReplacingMergeTree(timestamp)
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, generation_id, timestamp)
SETTINGS index_granularity = 8192;
