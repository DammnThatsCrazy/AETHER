// =============================================================================
// Aether SDK — Web2 / TradFi Profile Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type AccountType =
  | 'checking'
  | 'savings'
  | 'credit_card'
  | 'mortgage'
  | 'student_loan'
  | 'brokerage'
  | 'ira'
  | '401k'
  | 'other';

export interface FinancialAccountSummary {
  readonly account_id: string;
  readonly institution_name: string;
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

export interface Web2Profile {
  readonly entity_id: string;
  readonly window: TimeWindow;
  readonly kpis: Web2KPIs;
  readonly accounts: FinancialAccountSummary[];
  readonly recent_transactions: Web2Transaction[];
  readonly tradfi_positions: TradFiPosition[];
  readonly total_assets_usd: number;
  readonly total_liabilities_usd: number;
  readonly net_worth_usd: number;
  readonly computed_at: string;
  readonly last_refreshed_at: string;
  /** Which data sources are connected for this entity */
  readonly connected_sources: Array<'plaid' | 'experian' | 'equifax' | 'transunion' | 'alpaca' | 'ibkr' | 'schwab' | 'fidelity'>;
}
