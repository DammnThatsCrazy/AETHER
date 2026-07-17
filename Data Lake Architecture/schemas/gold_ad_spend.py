"""
Aether — Gold Tier: Ad Spend Schema
Campaign spend data ingested from ad platform connectors
(Twitter Ads, Google Ads, Meta, LinkedIn, TikTok).
One row per campaign per date per platform.
"""

from __future__ import annotations

GOLD_AD_SPEND_DDL = """
CREATE TABLE IF NOT EXISTS gold_ad_spend (
    tenant_id               String,
    campaign_id             String,
    platform                LowCardinality(String),   -- twitter_ads, google_ads, meta_ads, linkedin_ads, tiktok_ads, other
    utm_campaign            Nullable(String),
    date                    Date,
    spend_usd               Decimal(18, 6),
    impressions             UInt64,
    clicks                  UInt64,
    cpm                     Float32,   -- cost per thousand impressions
    cpc                     Float32,   -- cost per click
    ctr                     Float32,   -- click-through rate (0-1)
    conversions             UInt32,
    revenue_attributed_usd  Decimal(18, 6),
    ingested_at             DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(date)
ORDER BY (tenant_id, platform, campaign_id, date)
TTL date + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""

# Inferred impressions strategy:
# When utm_source is present in campaign_context of an event but no ad platform
# connector is live, an impression row is synthesized with impressions=1, spend_usd=0.
# When ad platform connectors are active, real impression data replaces the inferred record
# via ReplacingMergeTree(ingested_at) deduplication on (tenant_id, platform, campaign_id, date).
