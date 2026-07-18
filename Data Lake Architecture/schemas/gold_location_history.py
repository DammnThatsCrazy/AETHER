"""
Aether — Gold Tier: Location History Schema
Per-entity city-level location data with window support.
IP-level GeoIP is a legitimate interest enrichment (no consent required).
GPS/precise location requires 'location' consent purpose.

Classification thresholds:
  primary   > 50% of sessions
  secondary   5-50% of sessions
  rare        1-5% of sessions
  one_time  < 1% of sessions

Anomaly flag: new primary location appearing in last 7d triggers
LOCATION_ANOMALY behavioral signal.
"""

from __future__ import annotations

GOLD_LOCATION_HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS gold_location_history (
    entity_id               String,
    tenant_id               String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days             Nullable(UInt16),
    -- Location fields (city-level, from GeoIP enrichment in event-enricher.ts)
    city                    String,
    region                  String,
    country                 String,
    country_code            LowCardinality(String),
    latitude                Nullable(Float32),
    longitude               Nullable(Float32),
    -- Session statistics
    session_count           UInt32,
    session_pct             Float32,    -- fraction of total sessions (0-1)
    -- Connection type from ASN lookup (enriched by event-enricher.ts)
    connection_type_dominant LowCardinality(String), -- broadband, mobile, datacenter, unknown
    -- Classification based on session_pct thresholds
    classification          LowCardinality(String),  -- primary, secondary, rare, one_time
    first_seen_at           DateTime64(3, 'UTC'),
    last_seen_at            DateTime64(3, 'UTC'),
    -- Anomaly detection flag
    is_new_primary          UInt8,   -- 1 if classification=primary AND first_seen_at > now()-7d
    computed_at             DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, window_days, country_code, city)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""
