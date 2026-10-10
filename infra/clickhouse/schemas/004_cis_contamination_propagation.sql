-- CIS Contamination Propagation
-- Records contamination events and propagation paths through the graph.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_contamination_propagation
(
    event_id             String,
    tenant_id            String,
    timestamp            DateTime64(3, 'UTC'),
    origin_node_id       String,
    affected_node_ids    Array(String),
    affected_node_count  UInt32,
    propagation_depth    UInt8,
    contamination_score  Float32,
    contamination_type   String DEFAULT 'unknown',
    causality_chain      Array(String),
    source_agent_id      String DEFAULT '',
    resolved             UInt8 DEFAULT 0,
    source_service       String DEFAULT ''
) ENGINE = MergeTree()
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, origin_node_id, timestamp)
SETTINGS index_granularity = 8192;
