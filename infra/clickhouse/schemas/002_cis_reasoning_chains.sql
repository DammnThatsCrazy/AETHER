-- CIS Reasoning Chains
-- Stores reasoning chain telemetry for contradiction and recursion detection.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_reasoning_chains
(
    event_id               String,
    tenant_id              String,
    timestamp              DateTime64(3, 'UTC'),
    chain_id               String,
    generation_id          String DEFAULT '',
    steps                  Array(String),
    step_count             UInt16,
    contradiction_detected UInt8,
    recursion_detected     UInt8,
    recursion_depth        UInt8,
    confidence_start       Float32,
    confidence_end         Float32,
    confidence_inflation   Float32,
    agent_id               String DEFAULT '',
    source_service         String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, chain_id, timestamp)
SETTINGS index_granularity = 8192;
