-- CIS Retrieval Traces
-- Stores per-request retrieval telemetry from ml-serving / RAG pipelines.
CREATE DATABASE IF NOT EXISTS aether_cis;

CREATE TABLE IF NOT EXISTS aether_cis.cis_retrieval_traces
(
    event_id          String,
    tenant_id         String,
    timestamp         DateTime64(3, 'UTC'),
    query_hash        String,
    model_name        String,
    retrieved_node_ids Array(String),
    embedding_model   String,
    reasoning_trace   String,
    citations         Array(String),
    -- Nullable: an unknown model confidence is NULL, never a fabricated 0.0.
    confidence_score  Nullable(Float32),
    generation_hash   String,
    latency_ms        Float32,
    -- Nullable: grounding is NULL (unknown) when the model returns no evidence
    -- signal — never coerced to 1 (grounded) or 0 (ungrounded).
    grounded          Nullable(UInt8),
    synthetic_ratio   Float32,
    source_service    String DEFAULT ''
) ENGINE = ReplacingMergeTree(timestamp)
PARTITION BY (tenant_id, toYYYYMM(timestamp))
ORDER BY (tenant_id, timestamp, event_id)
SETTINGS index_granularity = 8192;
