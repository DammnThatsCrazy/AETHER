// =============================================================================
// Aether SDK — Trading Profile Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type GasStrategy = 'fast' | 'normal' | 'slow';

export interface TradingPair {
  /** e.g. "ETH/USDC" */
  readonly pair: string;
  readonly trade_count: number;
  readonly volume_usd: number;
}

export interface ProtocolLoyalty {
  readonly protocol_name: string;
  readonly protocol_id?: string;
  /** Percentage of total volume transacted through this protocol */
  readonly volume_pct: number;
}

export interface TradingProfile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** Top trading pairs by volume, sorted descending */
  readonly favorite_pairs: TradingPair[];
  /** Top-3 protocols by volume share */
  readonly protocol_loyalty: ProtocolLoyalty[];
  /** Gas price preference relative to network P50 */
  readonly gas_strategy: GasStrategy;
  /** Average slippage tolerance as a percentage */
  readonly avg_slippage_pct: number;
  readonly avg_trade_size_usd: number;
  /** Ratio of successful transactions */
  readonly tx_success_rate: number;
  /** Average gas cost in USD per transaction */
  readonly avg_gas_cost_usd: number;
  readonly computed_at: string;
}
