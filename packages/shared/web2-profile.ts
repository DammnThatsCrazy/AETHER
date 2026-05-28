// =============================================================================
// Aether SDK — Financial Profile Types (Web2 / TradFi)
//
// Entity-agnostic: covers any human, household, business, or organization
// with bank accounts, brokerage positions, or credit data.
//
// Two data tiers:
//   1. Holdings — account balances and portfolio positions (requires consent)
//   2. Signals  — behaviorally derived indicators without raw balances
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type AccountType =
  | 'checking'
  | 'savings'
  | 'money_market'
  | 'credit_card'
  | 'mortgage'
  | 'auto_loan'
  | 'student_loan'
  | 'personal_loan'
  | 'brokerage'
  | 'ira'
  | 'roth_ira'
  | '401k'
  | '529'
  | 'hsa'
  | 'crypto_exchange'
  | 'other';

/** Supported financial data source connectors */
export type FinancialDataSource =
  // Open banking
  | 'plaid'
  // Credit bureaus
  | 'experian' | 'equifax' | 'transunion'
  // Traditional brokerages
  | 'fidelity' | 'schwab' | 'vanguard' | 'etrade' | 'tdameritrade'
  // Retail investing / neo-brokerages
  | 'robinhood' | 'alpaca' | 'ibkr' | 'webull' | 'public'
  // Banking / fintech
  | 'sofi' | 'betterment' | 'wealthfront' | 'acorns' | 'chime'
  // Crypto exchanges acting as brokerages
  | 'coinbase' | 'kraken' | 'gemini';

export interface FinancialAccountSummary {
  readonly account_id: string;
  readonly institution_name: string;
  readonly data_source: FinancialDataSource;
  readonly account_type: AccountType;
  readonly balance_usd: number;
  readonly last_sync_at: string;
}

export interface Web2Transaction {
  readonly transaction_id: string;
  readonly account_id: string;
  readonly date: string;
  readonly amount_usd: number;
  /** Positive = credit (inflow), negative = debit (outflow) */
  readonly direction: 'credit' | 'debit';
  readonly category?: string;
  readonly merchant_name?: string;
}

export interface TradFiPosition {
  readonly broker: string;
  readonly data_source: FinancialDataSource;
  readonly asset_class: 'equity' | 'bond' | 'etf' | 'option' | 'crypto' | 'cash' | 'other';
  readonly symbol?: string;
  readonly quantity?: number;
  readonly value_usd: number;
  readonly last_sync_at: string;
}

export interface Web2KPIs {
  /** FICO-style credit score 300–850; null if consent not granted */
  readonly credit_score_range?: string;       // e.g. "720–760"
  readonly income_estimate_range?: string;    // e.g. "$75k–$100k"
  readonly net_worth_estimate_usd?: number;
  readonly has_derogatory_marks?: boolean;
  readonly debt_to_income_ratio?: number;
}

// ── Tier 2: Behavioral Signals (no raw balances) ─────────────────────────────

/** Spend tier — relative classification within cohort */
export type SpendTier = 'low' | 'moderate' | 'high' | 'ultra_high';

/** Savings behavioral pattern */
export type SavingsBehavior = 'saver' | 'spender' | 'balanced' | 'variable';

/** Risk tolerance classification derived from portfolio composition */
export type InvestmentRiskProfile = 'conservative' | 'moderate' | 'aggressive' | 'speculative';

/**
 * FinancialSignals — behaviorally derived indicators derived from account
 * and transaction patterns. Never exposes raw balances or positions.
 * Appropriate for use cases where holdings consent is not granted.
 */
export interface FinancialSignals {
  readonly spend_tier?: SpendTier;
  readonly savings_behavior?: SavingsBehavior;
  readonly investment_risk_profile?: InvestmentRiskProfile;
  /** Net worth band — e.g. "$100k–$500k" */
  readonly net_worth_band?: string;
  /** Liquidity indicator: proportion of assets in liquid instruments */
  readonly liquidity_ratio?: number;
  /** Whether entity shows recurring investment pattern (DCA, auto-invest) */
  readonly has_recurring_investment?: boolean;
  /** Primary spending categories derived from transaction patterns */
  readonly top_spend_categories?: string[];
  readonly computed_at: string;
}

export interface Web2Profile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly kpis: Web2KPIs;
  /** Tier 1: Raw holdings — requires financial_holdings consent */
  readonly accounts: FinancialAccountSummary[];
  readonly recent_transactions: Web2Transaction[];
  readonly tradfi_positions: TradFiPosition[];
  readonly total_assets_usd: number;
  readonly total_liabilities_usd: number;
  readonly net_worth_usd: number;
  /** Tier 2: Behavioral signals — requires financial_signals consent (lower bar) */
  readonly signals?: FinancialSignals;
  readonly computed_at: string;
  readonly last_refreshed_at: string;
  /** Which data sources are connected for this entity */
  readonly connected_sources: FinancialDataSource[];
}
