-- =============================================================================
-- Aether Multi-Actor Journey v1 — ClickHouse migration
-- Strictly additive. silver_events / silver_sessions / gold_attribution
-- are NOT modified. Three new tables sit alongside.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- event_extension — sidecar carrying the 18 mandatory event-completeness
-- fields. Joined to silver_events on (event_date, event_id).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aether.event_extension
(
    event_id              UUID,
    event_date            Date,
    project_id            String,

    -- 1. actor + 2. beneficiary
    actor_id              UUID,
    actor_kind            LowCardinality(String),
    beneficiary_actor_id  Nullable(UUID),

    -- journey linkage
    journey_id            UUID,
    journey_sequence      UInt32,

    -- 3. attribution
    attribution_first_touch     Tuple(source LowCardinality(String),
                                      campaign String,
                                      ts DateTime64(3)),
    attribution_last_touch      Tuple(source LowCardinality(String),
                                      campaign String,
                                      ts DateTime64(3)),
    attribution_multi_touch     Map(LowCardinality(String), Float32),
    attribution_actor_weighted  Map(LowCardinality(String), Float32),

    -- 4. state_snapshot pointer (Iceberg)
    snapshot_ref          String,
    snapshot_hash         FixedString(64),

    -- 5. temporal_context
    ts_relative_journey_ms  Int64,
    ts_relative_session_ms  Int64,
    ts_relative_prev_ms     Int64,

    -- 6. causality
    triggered_by_event_id Nullable(UUID),
    influencing_event_ids Array(UUID),
    causal_score          Float32,

    -- 7. decision_context
    decision_options      String,                       -- JSON

    -- 8. exposure
    exposure_ref          String,                       -- iceberg pointer

    -- 9. friction
    friction              Map(LowCardinality(String), String),

    -- 10. engagement
    engagement            Map(LowCardinality(String), Float32),

    -- 11. intent
    intent                Tuple(predicted_goal LowCardinality(String),
                                confidence Float32),

    -- 12. environment
    environment           Map(LowCardinality(String), String),

    -- 13. identity_confidence + signals
    identity_confidence   Float32,
    identity_signals      Array(LowCardinality(String)),

    -- 14. delegation
    delegation_id         Nullable(UUID),
    delegation_scope      Array(LowCardinality(String)),

    -- 15. agent_intelligence
    agent_reasoning_ref   String,                       -- iceberg pointer
    agent_confidence      Float32,
    agent_policy_logs     Array(String),

    -- 16. economic_context
    economic              Map(LowCardinality(String), String),

    -- 17. system_actions
    system_actions        String,                       -- JSON

    -- 18. consent + data_quality
    consent               Map(LowCardinality(String), UInt8),
    data_quality          Map(LowCardinality(String), Float32),

    -- reconciliation
    as_of                 LowCardinality(String) DEFAULT 'stream', -- stream|batch
    ingested_at           DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (project_id, actor_id, event_date, event_id)
SETTINGS index_granularity = 8192;

-- Skipping indexes for actor- and journey-centric queries.
ALTER TABLE aether.event_extension
    ADD INDEX IF NOT EXISTS idx_journey journey_id TYPE bloom_filter GRANULARITY 4;
ALTER TABLE aether.event_extension
    ADD INDEX IF NOT EXISTS idx_delegation delegation_id TYPE bloom_filter GRANULARITY 4;

-- -----------------------------------------------------------------------------
-- gold_actor_history — lifetime rollup per actor. Cross-journey memory.
-- ReplacingMergeTree resolves stream vs nightly-batch writes by last_seen_at.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aether.gold_actor_history
(
    project_id              String,
    actor_id                UUID,
    actor_kind              LowCardinality(String),

    journeys_total          UInt64,
    journeys_converted      UInt64,
    journeys_abandoned      UInt64,

    last_journey_id         UUID,
    last_journey_started_at DateTime64(3),

    lifetime_event_count    UInt64,
    lifetime_revenue        Decimal(18, 6),

    top_channels            Array(LowCardinality(String)),
    last_seen_at            DateTime64(3),
    as_of                   LowCardinality(String) DEFAULT 'stream'
)
ENGINE = ReplacingMergeTree(last_seen_at)
PARTITION BY project_id
ORDER BY (project_id, actor_id);

-- -----------------------------------------------------------------------------
-- gold_attribution_actor_weighted — sibling of gold_attribution
-- Adds actor_kind dimension and human/agent revenue splits.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aether.gold_attribution_actor_weighted
(
    project_id            String,
    metric_date           Date,
    channel               LowCardinality(String),
    campaign              String,
    actor_kind            LowCardinality(String),

    first_touch_conversions  UInt64,
    last_touch_conversions   UInt64,
    linear_conversions       Float64,
    shapley_conversions      Float64,
    actor_weighted_conversions Float64,
    exposure_weighted_conversions Float64,

    first_touch_revenue   Decimal(18,6),
    last_touch_revenue    Decimal(18,6),
    linear_revenue        Decimal(18,6),
    shapley_revenue       Decimal(18,6),
    actor_weighted_revenue Decimal(18,6),

    touchpoint_count      UInt64,
    unique_actors         UInt64,
    computed_at           DateTime64(3) DEFAULT now64(3)
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(metric_date)
ORDER BY (project_id, metric_date, channel, campaign, actor_kind);

-- -----------------------------------------------------------------------------
-- late_event_extension — rows that arrive after the nightly batch closes
-- the day's partition. Reconciled by the next batch.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS aether.late_event_extension AS aether.event_extension
ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (project_id, event_date, event_id);
