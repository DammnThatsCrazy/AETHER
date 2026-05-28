// =============================================================================
// Aether SDK — Asset Composition Types
// =============================================================================

export type AssetCategory =
  | 'stablecoin'
  | 'eth_lst'    // ETH liquid staking tokens (stETH, rETH, etc.)
  | 'btc'
  | 'altcoin'
  | 'nft'
  | 'other';

export type TimeWindow = '30d' | '60d' | '90d' | 'lifetime';

export interface AssetBreakdown {
  readonly symbol: string;
  readonly contract_address?: string;
  readonly chain_id: string;
  readonly category: AssetCategory;
  readonly value_usd: number;
  readonly pct: number;
}

export interface AssetComposition {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly stablecoin_pct: number;
  readonly eth_lst_pct: number;
  readonly btc_pct: number;
  readonly altcoin_pct: number;
  readonly nft_pct: number;
  readonly other_pct: number;
  readonly total_portfolio_usd: number;
  /** Per-asset breakdown; tokens < 1% of portfolio are collapsed into 'other' */
  readonly asset_breakdown: AssetBreakdown[];
  readonly computed_at: string;
}
