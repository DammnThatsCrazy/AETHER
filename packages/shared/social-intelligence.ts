// =============================================================================
// Aether SDK — Social Intelligence Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type InfluenceLevel = 'high' | 'medium' | 'low';

export interface SocialPlatformStats {
  readonly platform: 'twitter' | 'farcaster' | 'lens' | 'discord' | 'github' | 'linkedin' | 'instagram' | 'tiktok';
  readonly handle?: string;
  readonly platform_user_id?: string;
  readonly followers: number;
  readonly following?: number;
  readonly verified?: boolean;
  /** Posts / casts in the selected time window */
  readonly post_count_window?: number;
  readonly engagement_rate?: number;
  readonly last_refreshed_at: string;
}

export interface SocialProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly platforms: SocialPlatformStats[];
  /**
   * Deduplicated follower count — cross-platform followers bridged via ENS/wallet identity.
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
  readonly computed_at: string;
  readonly last_refreshed_at: string;
}
