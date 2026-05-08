// =============================================================================
// Aether Data Lake — event_extension table descriptor
// Sidecar to silver_events carrying the 18 mandatory event-completeness
// fields introduced by multi-actor journey v1. Sidecar (vs. ALTER TABLE)
// keeps existing dashboards working unchanged.
//
// Note: declared with a local descriptor type — `types.ts:ColumnType` is
// a constrained union that does not include UUID/Map/Tuple/FixedString,
// which are needed here. The DDL is also generated from the sibling
// `migrations/2026_05_event_extension.sql` and that file is the source
// of truth for production CREATE TABLE.
// =============================================================================

interface EventExtensionColumn {
  name: string;
  type: string;            // raw ClickHouse type string
  default?: string;
}

interface EventExtensionTable {
  name: string;
  database: string;
  engine: string;
  partitionBy: string;
  orderBy: string[];
  columns: EventExtensionColumn[];
}

export const EVENT_EXTENSION: EventExtensionTable = {
  name: 'event_extension',
  database: 'aether',
  engine: 'ReplacingMergeTree(ingested_at)',
  partitionBy: 'toYYYYMM(event_date)',
  orderBy: ['project_id', 'actor_id', 'event_date', 'event_id'],
  columns: [
    { name: 'event_id',                 type: 'UUID' },
    { name: 'event_date',               type: 'Date' },
    { name: 'project_id',               type: 'String' },
    { name: 'actor_id',                 type: 'UUID' },
    { name: 'actor_kind',               type: 'LowCardinality(String)' },
    { name: 'beneficiary_actor_id',     type: 'Nullable(UUID)' },
    { name: 'journey_id',               type: 'UUID' },
    { name: 'journey_sequence',         type: 'UInt32' },
    { name: 'attribution_first_touch',  type: 'Tuple(source LowCardinality(String), campaign String, ts DateTime64(3))' },
    { name: 'attribution_last_touch',   type: 'Tuple(source LowCardinality(String), campaign String, ts DateTime64(3))' },
    { name: 'attribution_multi_touch',  type: 'Map(LowCardinality(String), Float32)' },
    { name: 'attribution_actor_weighted', type: 'Map(LowCardinality(String), Float32)' },
    { name: 'snapshot_ref',             type: 'String' },
    { name: 'snapshot_hash',            type: 'FixedString(64)' },
    { name: 'ts_relative_journey_ms',   type: 'Int64' },
    { name: 'ts_relative_session_ms',   type: 'Int64' },
    { name: 'ts_relative_prev_ms',      type: 'Int64' },
    { name: 'triggered_by_event_id',    type: 'Nullable(UUID)' },
    { name: 'influencing_event_ids',    type: 'Array(UUID)' },
    { name: 'causal_score',             type: 'Float32' },
    { name: 'decision_options',         type: 'String' },
    { name: 'exposure_ref',             type: 'String' },
    { name: 'friction',                 type: 'Map(LowCardinality(String), String)' },
    { name: 'engagement',               type: 'Map(LowCardinality(String), Float32)' },
    { name: 'intent',                   type: 'Tuple(predicted_goal LowCardinality(String), confidence Float32)' },
    { name: 'environment',              type: 'Map(LowCardinality(String), String)' },
    { name: 'identity_confidence',      type: 'Float32' },
    { name: 'identity_signals',         type: 'Array(LowCardinality(String))' },
    { name: 'delegation_id',            type: 'Nullable(UUID)' },
    { name: 'delegation_scope',         type: 'Array(LowCardinality(String))' },
    { name: 'agent_reasoning_ref',      type: 'String' },
    { name: 'agent_confidence',         type: 'Float32' },
    { name: 'agent_policy_logs',        type: 'Array(String)' },
    { name: 'economic',                 type: 'Map(LowCardinality(String), String)' },
    { name: 'system_actions',           type: 'String' },
    { name: 'consent',                  type: 'Map(LowCardinality(String), UInt8)' },
    { name: 'data_quality',             type: 'Map(LowCardinality(String), Float32)' },
    { name: 'as_of',                    type: 'LowCardinality(String)', default: "'stream'" },
    { name: 'ingested_at',              type: 'DateTime64(3)', default: 'now64(3)' },
  ],
};
