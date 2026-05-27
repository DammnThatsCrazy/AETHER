// =============================================================================
// Aether SDK — Journey Economics, Funnel & Conversion Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export interface JourneyEconomics {
  readonly entity_id: string;
  readonly journey_id: string;
  readonly window: TimeWindow;
  readonly campaign_id?: string;
  readonly channel?: string;
  readonly platform?: string;
  readonly revenue_attributed_usd: number;
  readonly ad_spend_usd: number;
  /** Return on ad spend = revenue_attributed_usd / ad_spend_usd */
  readonly roas: number;
  /** Cost per acquisition = ad_spend_usd / conversions */
  readonly cpa_usd: number;
  readonly ltv_predicted_usd: number;
  readonly ltv_actual_usd: number;
  /** Average order / conversion value */
  readonly aov_usd: number;
  /** Number of repeat conversions in window */
  readonly repeat_count: number;
  /**
   * Score 0–10 indicating how valuable retargeting this entity would be.
   * Derived from: intent_signal × ltv_score × recency_decay × (1 − stage_depth).
   */
  readonly retarget_score: number;
  readonly retarget_recommendation_id?: string;
  readonly computed_at: string;
}

/** Median time (ms) between each funnel stage conversion. */
export interface TimeToConversion {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** Impression → first click */
  readonly impression_to_click_ms?: number;
  /** Click → first site/app visit */
  readonly click_to_visit_ms?: number;
  /** Visit → wallet connect */
  readonly visit_to_connect_ms?: number;
  /** Wallet connect → first swap */
  readonly connect_to_swap_ms?: number;
  /** First swap → liquidity provision */
  readonly swap_to_liquidity_ms?: number;
  readonly computed_at: string;
}

export interface DeviceConversionStats {
  readonly device_type: 'desktop' | 'mobile' | 'tablet' | 'unknown';
  readonly session_count: number;
  readonly conversion_count: number;
  readonly conversion_rate: number;
  readonly avg_conversion_value_usd: number;
}

export interface DevicePerformance {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly by_device: DeviceConversionStats[];
  readonly computed_at: string;
}

export interface ConversionFunnelStage {
  readonly stage_name: string;
  /** e.g. 'impression', 'click', 'visit', 'connect', 'swap', 'liquidity' */
  readonly stage_key: string;
  readonly stage_index: number;
  readonly entered: number;
  readonly completed: number;
  readonly dropped: number;
  readonly drop_off_rate: number;
  readonly avg_time_ms?: number;
}

export interface ConversionFunnel {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly campaign_id?: string;
  readonly stages: ConversionFunnelStage[];
  readonly overall_conversion_rate: number;
  readonly computed_at: string;
}
