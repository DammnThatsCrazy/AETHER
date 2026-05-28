// =============================================================================
// Aether SDK — Retarget Recommendation Types
// =============================================================================

import type { AdPlatform } from './ad-spend';

export type RecommendationStatus =
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'executed'
  | 'expired';

export interface RetargetRecommendation {
  readonly recommendation_id: string;
  readonly entity_id: string;
  readonly journey_id: string;
  /** 0–10 — drives whether this recommendation surfaces to the analyst */
  readonly retarget_score: number;
  readonly recommended_platform: AdPlatform;
  /** Creative theme derived from protocol affinity + behavioral signals */
  readonly recommended_creative_theme: string;
  /** Bid price based on CPA target × expected conversion rate */
  readonly recommended_bid_usd: number;
  readonly recommended_audience_segment: string;
  /** 0–1 — model confidence in this recommendation */
  readonly confidence: number;
  /** Human-readable evidence list shown to the analyst in the review UI */
  readonly reasoning: string[];
  readonly status: RecommendationStatus;
  readonly created_at: string;
  readonly reviewed_by?: string;
  readonly review_notes?: string;
  readonly executed_at?: string;
}
