// =============================================================================
// Aether SDK — Ad Spend Types
// =============================================================================

export type AdPlatform =
  | 'twitter_ads'
  | 'google_ads'
  | 'meta_ads'
  | 'linkedin_ads'
  | 'tiktok_ads'
  | 'other';

export interface AdSpendRecord {
  readonly tenant_id: string;
  readonly campaign_id: string;
  readonly platform: AdPlatform;
  readonly utm_campaign?: string;
  readonly date: string;  // YYYY-MM-DD
  readonly spend_usd: number;
  readonly impressions: number;
  readonly clicks: number;
  readonly cpm: number;   // cost per thousand impressions
  readonly cpc: number;   // cost per click
  readonly ctr: number;   // click-through rate 0–1
  readonly conversions: number;
  readonly revenue_attributed_usd: number;
  readonly ingested_at: string;
}

export interface CampaignMetrics {
  readonly campaign_id: string;
  readonly platform: AdPlatform;
  readonly campaign_name?: string;
  readonly total_spend_usd: number;
  readonly total_impressions: number;
  readonly total_clicks: number;
  readonly total_conversions: number;
  readonly total_revenue_attributed_usd: number;
  readonly roas: number;
  readonly cpa_usd: number;
  readonly period_start: string;
  readonly period_end: string;
}
