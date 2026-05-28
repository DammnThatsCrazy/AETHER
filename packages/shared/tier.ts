// =============================================================================
// Aether SDK — Tier Intelligence Types
// =============================================================================

/** Entity tier name — ordered from highest (1) to lowest (9). */
export type TierName =
  | 'Whale'    // top 0.1%
  | 'Shark'    // top 1%
  | 'Dolphin'  // top 5%
  | 'Fish'     // top 20%
  | 'Shrimp';  // remainder

export interface TierProfile {
  readonly entity_id: string;
  readonly tier_name: TierName;
  /** Numeric level 1 (Whale) – 5 (Shrimp) */
  readonly tier_level: 1 | 2 | 3 | 4 | 5;
  /** 0–100 percentile rank within the tenant's entity population */
  readonly percentile: number;
  /** Portfolio value driving tier assignment */
  readonly tvl_usd: number;
  /** ISO8601 — when this tier assignment was last computed */
  readonly computed_at: string;
  readonly valid_from: string;
  readonly valid_until?: string;
}

/** Tier boundary thresholds (configurable per tenant via admin API). */
export interface TierBoundary {
  readonly tier_name: TierName;
  readonly min_percentile: number;
  readonly max_percentile: number;
  readonly min_tvl_usd?: number;
}
