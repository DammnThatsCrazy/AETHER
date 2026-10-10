-- CIS Mutation Analytics
-- Records all mutation gateway decisions for analytics and agent instability detection.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_mutation_analytics
(
    event_id       String,
    tenant_id      String,
    mutation_id    String,
    timestamp      DateTime64(3, 'UTC'),
    mutation_class UInt8,
    risk_score     Float32,
    risk_band      String,
    agent_id       String DEFAULT '',
    entity_id      String,
    entity_type    String,
    action         String,
    latency_ms     Float32 DEFAULT 0,
    source_service String DEFAULT ''
) ENGINE = ReplacingMergeTree(timestamp)
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, mutation_id, timestamp)
SETTINGS index_granularity = 8192;
