// =============================================================================
// Aether SDK — Social Intelligence Types
//
// Entity-agnostic: covers any human, organization, brand, creator, or AI agent
// with a presence on Web2 or Web3 social platforms.
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type InfluenceLevel = 'high' | 'medium' | 'low';

/**
 * All platforms supported by the social aggregator.
 * Web2: twitter, youtube, instagram, tiktok, reddit, linkedin, spotify, telegram, discord, github
 * Web3: farcaster, lens
 */
export type SocialPlatform =
  // Primary Web2
  | 'twitter'
  | 'youtube'
  | 'instagram'
  | 'tiktok'
  | 'reddit'
  | 'linkedin'
  | 'spotify'
  | 'telegram'
  // Secondary Web2
  | 'discord'
  | 'github'
  // Web3-native
  | 'farcaster'
  | 'lens';

/**
 * Whether the entity is acting as a content creator/publisher on this platform,
 * a consumer/listener, or both. Determines which metrics are surfaced.
 */
export type PlatformRole = 'creator' | 'consumer' | 'both';

/** YouTube-specific creator metrics */
export interface YouTubeCreatorStats {
  readonly subscribers: number;
  readonly total_views: number;
  readonly video_count: number;
  readonly avg_views_per_video?: number;
}

/** YouTube-specific consumer metrics (requires OAuth scope) */
export interface YouTubeConsumerStats {
  readonly subscriptions_count?: number;
  readonly watch_time_hours_estimate?: number;
}

/** Spotify-specific creator/artist metrics */
export interface SpotifyCreatorStats {
  readonly monthly_listeners: number;
  readonly total_streams_estimate?: number;
  readonly discography_count?: number;
}

/** Spotify-specific consumer metrics (requires OAuth scope) */
export interface SpotifyConsumerStats {
  readonly top_genre?: string;
  readonly listening_hours_estimate?: number;
  readonly saved_tracks_count?: number;
}

/** Reddit-specific metrics */
export interface RedditStats {
  readonly post_karma: number;
  readonly comment_karma: number;
  readonly top_subreddits?: string[];
}

/** Telegram-specific metrics (public channels + groups only) */
export interface TelegramChannelStats {
  readonly subscribers: number;
  readonly avg_post_reach?: number;
  readonly post_count_window?: number;
}

export interface SocialPlatformStats {
  readonly platform: SocialPlatform;
  readonly role: PlatformRole;
  readonly handle?: string;
  readonly platform_user_id?: string;
  readonly display_name?: string;
  /** Unified follower/subscriber/connection count */
  readonly followers: number;
  readonly following?: number;
  readonly verified?: boolean;
  /** Posts / casts / videos in the selected time window */
  readonly post_count_window?: number;
  readonly engagement_rate?: number;
  readonly last_refreshed_at: string;
  /** Platform-specific extended metrics — present only when applicable */
  readonly youtube?: YouTubeCreatorStats & { consumer?: YouTubeConsumerStats };
  readonly spotify?: SpotifyCreatorStats & { consumer?: SpotifyConsumerStats };
  readonly reddit?: RedditStats;
  readonly telegram?: TelegramChannelStats;
}

export interface SocialProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly platforms: SocialPlatformStats[];
  /**
   * Deduplicated follower count.
   * For entities with wallet/ENS identifiers: bridged via on-chain identity.
   * For pure Web2 entities: bridged via email/phone identity where available.
   * Always ≤ sum of individual platform followers.
   */
  readonly total_followers_deduped: number;
  /**
   * High = top 20% of followers AND engagement_rate > P75.
   * Medium = either condition.
   * Low = neither.
   */
  readonly influence_level: InfluenceLevel;
  readonly engagement_rate: number;
  /** Platforms currently connected for this entity */
  readonly platforms_connected: SocialPlatform[];
  readonly computed_at: string;
  readonly last_refreshed_at: string;
}
