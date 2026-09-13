"""
Aether — Gold Tier: Credit Signal Schema
Tri-bureau credit signals per entity.
Requires 'credit' consent purpose before any data can be fetched.
PII handling: SSN is never stored — it is hashed with a tenant-specific
pepper and passed at query time only, then discarded.
"""

from __future__ import annotations

GOLD_CREDIT_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS gold_credit_signals (
    entity_id               String,
    tenant_id               String,
    bureau                  LowCardinality(String),  -- experian, equifax, transunion
    -- Credit score stored as a range string (e.g. "720-760") not exact value
    credit_score_range      Nullable(String),
    -- Income stored as a range string (e.g. "$75k-$100k")
    income_estimate_range   Nullable(String),
    has_derogatory_marks    UInt8,   -- 0 or 1
    -- Number of derogatory items (no details stored)
    derogatory_item_count   Nullable(UInt16),
    debt_to_income_ratio    Nullable(Float32),
    last_refreshed_at       DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(last_refreshed_at)
ORDER BY (tenant_id, entity_id, bureau)
TTL last_refreshed_at + INTERVAL 1 YEAR
SETTINGS index_granularity = 8192;
"""

# Retention is shorter (1 year) than other gold tables because credit data
# changes frequently and expired credit signals should not influence decisions.
