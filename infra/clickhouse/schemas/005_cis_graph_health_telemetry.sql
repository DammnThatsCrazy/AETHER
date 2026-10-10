-- CIS Graph Health Telemetry
-- Time-series health index scores per tenant computed by GraphHealthEngine.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_graph_health_telemetry
(
    event_id               String,
    tenant_id              String,
    timestamp              DateTime64(3, 'UTC'),
    composite_score        Float32,
    structural_integrity   Float32,
    semantic_stability     Float32,
    retrieval_integrity    Float32,
    provenance_quality     Float32,
    contamination_risk     Float32,
    temporal_volatility    Float32,
    source_service         String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, timestamp)
SETTINGS index_granularity = 8192;
