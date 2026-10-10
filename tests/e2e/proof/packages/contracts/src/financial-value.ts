import type { SourceClassification } from './source-classification';

/** A financial value event (e.g., revenue, LTV, subscription value). */
export interface FinancialValue {
  readonly event_id: string;
  readonly event_type: string;
  readonly timestamp: string;
  readonly user_id: string;
  readonly value_type: ValueType;
  readonly amount: number;
  readonly currency: string;
  readonly interval?: string;
  readonly lifetime_value?: number;
  readonly conversion_id?: string;
  readonly campaign_id?: string;
  readonly workspace_id?: string;
  readonly device_id?: string;
  readonly session_id?: string;
  readonly items?: readonly FinancialValueItem[];
  readonly properties?: Record<string, unknown>;
  readonly source?: SourceClassification;
}

/** Type of financial value event. */
export type ValueType =
  | 'revenue'
  | 'purchase'
  | 'subscription'
  | 'refund'
  | 'credit'
  | 'debit'
  | 'upgrade'
  | 'downgrade'
  | 'trial_conversion'
  | 'renewal'
  | 'cancellation'
  | 'loyalty'
  | 'coupon'
  | 'discount'
  | 'shipping'
  | 'tax'
  | 'custom';

/** Currency unit for financial values. */
export type ValueUnit =
  | 'USD'
  | 'EUR'
  | 'GBP'
  | 'JPY'
  | 'CNY'
  | 'KRW'
  | 'BTC'
  | 'ETH'
  | 'USDT'
  | 'USDC'
  | 'custom';

/** A line item breakdown of a financial value event. */
export interface FinancialValueItem {
  readonly item_id: string;
  readonly name: string;
  readonly quantity?: number;
  readonly unit_price?: number;
  readonly total_amount?: number;
  readonly currency?: string;
  readonly category?: string;
  readonly properties?: Record<string, unknown>;
}

/** A value record — the canonical persisted form. */
export interface ValueRecord extends FinancialValue {
  readonly id: string;
  readonly workspace_id: string;
  readonly tenant_id?: string;
  readonly created_at: string;
  readonly updated_at?: string;
}
