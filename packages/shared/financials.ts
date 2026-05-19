// =============================================================================
// Aether SDK — Unified Financial Profile Contracts (Web2 + Web3)
// Covers payment history, subscriptions, LTV (Web2) and on-chain flows,
// LP positions, staking, protocol spend, and counterparty flows (Web3).
// Returned by GET /v1/profile/{id}/financials
// =============================================================================

// ── Web2 ──────────────────────────────────────────────────────────────────────

/** A single payment record in the Web2 financial history. */
export interface Web2PaymentRecord {
  readonly payment_id: string;
  readonly amount: number;
  readonly currency: string;
  /** initiated | pending | authorized | captured | completed | failed | refunded | disputed */
  readonly status: string;
  /** stripe | card | bank | invoice | internal */
  readonly method?: string;
  readonly timestamp: string;
  /** Stripe charge ID, invoice number, etc. */
  readonly external_ref?: string;
  readonly metadata?: Record<string, unknown>;
}

/**
 * Web2 financial profile — payment history, subscriptions, and LTV.
 * Covers traditional (fiat) commerce flows.
 */
export interface Web2FinancialProfile {
  readonly user_id: string;
  readonly lifetime_value_usd?: number;
  readonly total_revenue_usd?: number;
  readonly total_refunds_usd?: number;
  readonly payment_count: number;
  readonly refund_count?: number;
  readonly subscription_active?: boolean;
  readonly subscription_plan?: string;
  /** Monthly recurring revenue from this user */
  readonly subscription_mrr_usd?: number;
  readonly average_order_value_usd?: number;
  readonly first_payment_at?: string;
  readonly last_payment_at?: string;
  readonly recent_payments?: Web2PaymentRecord[];
}

// ── Web3 ──────────────────────────────────────────────────────────────────────

/** AMM / liquidity pool position. */
export interface LPPosition {
  readonly protocol: string;
  readonly protocol_id?: string;
  readonly pair: string;
  readonly chain_id?: string;
  readonly value_usd: number;
  /** Fraction of the pool owned by this wallet — 0–1 */
  readonly share?: number;
  readonly entry_at?: string;
}

/** Staking or locking position on a protocol. */
export interface StakingPosition {
  readonly protocol: string;
  readonly protocol_id?: string;
  readonly asset: string;
  readonly chain_id?: string;
  readonly value_usd: number;
  /** Annual percentage yield at time of snapshot */
  readonly apy?: number;
  /** When the stake unlocks, if applicable */
  readonly locked_until?: string;
  readonly entry_at?: string;
}

/** Aggregate spend + volume on a single protocol. */
export interface ProtocolSpend {
  readonly protocol: string;
  readonly protocol_id?: string;
  /** dex | lending | staking | bridge | nft | governance | yield | other */
  readonly category?: string;
  readonly volume_usd: number;
  readonly interaction_count: number;
  readonly first_at?: string;
  readonly last_at?: string;
}

/** Net flow (in or out) with a specific counterparty address. */
export interface CounterpartyFlow {
  readonly address: string;
  readonly label?: string;
  readonly direction: 'in' | 'out';
  readonly volume_usd: number;
  readonly transaction_count: number;
}

/**
 * Web3 on-chain financial summary — aggregated over all linked wallets.
 * Complements Web3WalletProfile (per wallet) with cross-wallet totals.
 */
export interface Web3OnChainFinancials {
  readonly entity_id: string;
  readonly total_inflows_usd?: number;
  readonly total_outflows_usd?: number;
  readonly net_position_usd?: number;
  readonly total_portfolio_usd?: number;
  readonly lp_positions?: LPPosition[];
  readonly staking_positions?: StakingPosition[];
  readonly protocol_spend?: ProtocolSpend[];
  readonly top_counterparties?: CounterpartyFlow[];
  readonly computed_at: string;
}

// ── Unified view ──────────────────────────────────────────────────────────────

/**
 * Unified Web2 + Web3 financial profile for any entity.
 * Returned by GET /v1/profile/{id}/financials.
 * total_value_usd = web2 LTV + web3 portfolio + staking + LP.
 */
export interface UnifiedFinancialProfile {
  readonly entity_id: string;
  readonly web2?: Web2FinancialProfile;
  readonly web3?: Web3OnChainFinancials;
  /** Combined total across both rails */
  readonly total_value_usd?: number;
  /** Dominant activity rail: fiat | onchain | x402 | mixed */
  readonly primary_activity_rail?: string;
  readonly computed_at: string;
}
