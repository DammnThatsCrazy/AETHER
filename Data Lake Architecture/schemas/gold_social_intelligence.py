"""
Aether — Gold Tier: Social Intelligence Schema
Aggregated cross-platform social data per entity.
Phase 1 platforms: Twitter, Farcaster, Lens, Discord, GitHub.
Phase 2: LinkedIn, Instagram, TikTok.

Influence level:
  high   = top_20_pct(followers) AND engagement_rate > P75
  medium = either condition
  low    = neither
"""

from __future__ import annotations

GOLD_SOCIAL_INTELLIGENCE_DDL = """
CREATE TABLE IF NOT EXISTS gold_social_intelligence (
    entity_id               String,
    tenant_id               String,
    -- Time window: 30, 60, 90, or NULL for lifetime
    window_days             Nullable(UInt16),
    -- Twitter / X
    twitter_handle          Nullable(String),
    twitter_followers       Nullable(UInt32),
    twitter_verified        UInt8,
    -- Farcaster
    farcaster_fid           Nullable(UInt32),
    farcaster_followers     Nullable(UInt32),
    -- Lens Protocol
    lens_profile_id         Nullable(String),
    lens_followers          Nullable(UInt32),
    -- Discord
    discord_user_id         Nullable(String),
    discord_guilds          Nullable(UInt32),
    -- GitHub
    github_login            Nullable(String),
    github_followers        Nullable(UInt32),
    github_public_repos     Nullable(UInt16),
    -- Aggregated metrics
    -- Deduplicated across platforms via ENS/wallet bridge identity
    total_followers_deduped UInt32,
    influence_level         LowCardinality(String),  -- high, medium, low
    engagement_rate         Float32,
    computed_at             DateTime64(3, 'UTC'),
    last_refreshed_at       DateTime64(3, 'UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(computed_at)
ORDER BY (tenant_id, entity_id, window_days)
TTL computed_at + INTERVAL 2 YEAR
SETTINGS index_granularity = 8192;
"""
