// =============================================================================
// Aether SDK — PNL (Profit & Loss) Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type CostBasisMethod = 'FIFO' | 'LIFO';

/** Data confidence when not all cost basis history is available. */
export type PNLDataConfidence = 'exact' | 'estimated';

export interface DailyPNL {
  readonly date: string;        // YYYY-MM-DD
  readonly realized_pnl_usd: number;
  readonly unrealized_pnl_usd: number;
  readonly tvl_usd: number;
}

export interface PNLSummary {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly realized_pnl_usd: number;
  readonly unrealized_pnl_usd: number;
  /** Change in total portfolio value over the window */
  readonly tvl_delta_usd: number;
  readonly tvl_delta_pct: number;
  readonly best_day_pnl_usd?: number;
  readonly best_day_date?: string;
  readonly worst_day_pnl_usd?: number;
  readonly worst_day_date?: string;
  readonly cost_basis_method: CostBasisMethod;
  /** 'estimated' when partial tx history prevents exact FIFO cost basis */
  readonly data_confidence: PNLDataConfidence;
  readonly daily_series?: DailyPNL[];
  readonly computed_at: string;
}
