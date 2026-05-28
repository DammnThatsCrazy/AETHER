-- CIS Semantic Drift Metrics
-- Time-series drift scores per tenant/cluster computed by SemanticDriftEngine.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_semantic_drift_metrics
(
    event_id                  String,
    tenant_id                 String,
    cluster_id                String,
    timestamp                 DateTime64(3, 'UTC'),
    centroid_migration        Float32,
    neighborhood_instability  Float32,
    semantic_radius           Float32,
    graph_entropy_delta       Float32,
    composite_drift_score     Float32,
    triggered_alert           UInt8,
    node_count                UInt32 DEFAULT 0,
    source_service            String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, cluster_id, timestamp)
SETTINGS index_granularity = 8192;
