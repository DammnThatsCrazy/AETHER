// =============================================================================
// Aether Derivatives Intelligence — PR1 foundation contracts
// Canonical bounded-domain contracts for read-only derivatives intelligence.
// =============================================================================

import type { EntityRef } from './entities';

export type DerivativesEvidenceClass =
  | 'fact'
  | 'computation'
  | 'inference'
  | 'recommendation'
  | 'insufficient_evidence';

export type DerivativesActorLayerClassification = 'H2H' | 'H2A' | 'A2H' | 'A2A' | 'DOMAIN_EXCLUDED';

export type VenueType = 'centralized_exchange' | 'decentralized_exchange' | 'brokerage' | 'onchain_protocol' | 'indexer' | 'tenant_import' | 'unknown';
export type InstrumentType = 'perpetual_future' | 'dated_future' | 'option' | 'swap' | 'synthetic' | 'unknown';
export type ContractType = 'perpetual' | 'dated_future' | 'inverse_perpetual' | 'linear_perpetual' | 'unknown';
export type LinearInverseType = 'linear' | 'inverse' | 'quanto' | 'unknown';
export type MarginMode = 'cross' | 'isolated' | 'portfolio' | 'unknown';
export type PositionSide = 'long' | 'short' | 'flat' | 'unknown';
export type PositionStatus = 'absent' | 'opening' | 'open' | 'increasing' | 'reducing' | 'closing' | 'closed' | 'liquidating' | 'liquidated' | 'auto_deleveraged' | 'settlement_pending' | 'settled' | 'reconciliation_required' | 'source_stale' | 'unknown';
export type PositionEventType = 'opened' | 'increased' | 'reduced' | 'closed' | 'liquidated' | 'auto_deleveraged' | 'settled' | 'corrected' | 'unknown';
export type OrderType = 'market' | 'limit' | 'stop_market' | 'stop_limit' | 'take_profit_market' | 'take_profit_limit' | 'twap' | 'unknown';
export type OrderSide = 'buy' | 'sell' | 'unknown';
export type OrderStatus = 'pending' | 'open' | 'partially_filled' | 'filled' | 'cancelled' | 'rejected' | 'expired' | 'unknown';
export type TimeInForce = 'gtc' | 'ioc' | 'fok' | 'post_only' | 'reduce_only' | 'unknown';
export type FillLiquidityRole = 'maker' | 'taker' | 'auction' | 'unknown';
export type LiquidationType = 'partial' | 'full' | 'adl' | 'settlement' | 'unknown';
export type FeeType = 'maker' | 'taker' | 'funding' | 'liquidation' | 'borrow' | 'gas' | 'keeper' | 'rebate' | 'unknown';
export type PriceType = 'mark' | 'index' | 'oracle' | 'mid' | 'execution' | 'settlement' | 'unknown';
export type SettlementType = 'cash' | 'physical' | 'coin' | 'stablecoin' | 'unknown';
export type SourceFinality = 'provisional' | 'authoritative' | 'corrected' | 'reorged' | 'unknown';
export type ReconciliationStatus = 'matched' | 'variance_detected' | 'operator_review' | 'resolved' | 'source_stale' | 'unknown';
export type DecisionOrigin = 'human' | 'agent' | 'service' | 'venue' | 'import' | 'unknown';
export type AuthorityType = 'read_only' | 'trade_propose' | 'trade_approve' | 'risk_review' | 'execution_external' | 'unknown';
export type RiskSeverity = 'low' | 'medium' | 'high' | 'critical' | 'unknown';
export type AccountingMethod = 'average_entry' | 'venue_reported' | 'linear_contract' | 'inverse_contract' | 'manual_review' | 'unknown';
export type ConnectorState = 'configured' | 'testing' | 'active' | 'paused' | 'backfilling' | 'stale' | 'error' | 'revoked' | 'unknown';
export type DataQualityState = 'complete' | 'partial' | 'stale' | 'quarantined' | 'schema_drift' | 'unknown';

export interface DerivativesEvidenceEnvelope {
  evidence_class: DerivativesEvidenceClass;
  source_refs: string[];
  source_event_ids: string[];
  calculation_version?: string;
  model_version?: string;
  confidence: string;
  valid_time: string;
  recorded_time: string;
  explanation: string;
  data_freshness_seconds?: number;
}

export interface DerivativesTenantScoped {
  tenant_id: string;
  idempotency_key: string;
  evidence: DerivativesEvidenceEnvelope;
  execution_by_aether: false;
}

export interface TradingVenue {
  venue_id: string;
  venue_type: VenueType;
  display_name: string;
  website_url?: string;
  global_reference: true;
}

export interface VenueDeployment {
  venue_deployment_id: string;
  venue_id: string;
  deployment: string;
  chain_id?: string;
  region?: string;
  global_reference: true;
}

export interface DerivativeInstrument {
  canonical_instrument_id: string;
  instrument_type: InstrumentType;
  underlying_asset_id: string;
  quote_asset_id: string;
  settlement_asset_id: string;
  contract_type: ContractType;
  contract_multiplier: string;
  inverse_or_linear: LinearInverseType;
  expiry_at?: string;
  global_reference: true;
}

export interface DerivativeMarket {
  canonical_market_id: string;
  canonical_instrument_id: string;
  venue_id: string;
  venue_deployment_id: string;
  venue_market_id: string;
  underlying_asset_id: string;
  quote_asset_id: string;
  settlement_asset_id: string;
  instrument_type: InstrumentType;
  contract_type: ContractType;
  contract_multiplier: string;
  inverse_or_linear: LinearInverseType;
  expiry_at?: string;
  price_precision: string;
  size_precision: string;
  margin_modes: MarginMode[];
  status: 'active' | 'inactive' | 'delisted' | 'review_required' | 'unknown';
  first_seen_at: string;
  last_seen_at: string;
  global_reference: true;
}

export interface TradingAccount extends DerivativesTenantScoped {
  trading_account_id: string;
  venue_id: string;
  venue_deployment_id?: string;
  external_account_ref: string;
  owner_ref?: EntityRef;
  credential_reference_id?: string;
  connector_state: ConnectorState;
  data_quality_state: DataQualityState;
}

export interface TradingSubaccount extends DerivativesTenantScoped { trading_subaccount_id: string; trading_account_id: string; external_subaccount_ref: string; }
export interface TradingVault extends DerivativesTenantScoped { trading_vault_id: string; venue_id: string; vault_ref: string; participant_refs: EntityRef[]; }
export interface CollateralAccount extends DerivativesTenantScoped { collateral_account_id: string; trading_account_id: string; asset_id: string; balance: string; }
export interface MarginSnapshot extends DerivativesTenantScoped { margin_snapshot_id: string; trading_account_id: string; margin_mode: MarginMode; maintenance_margin: string; initial_margin: string; margin_utilization: string; observed_at: string; }
export interface DerivativesOrder extends DerivativesTenantScoped { order_id: string; trading_account_id: string; canonical_market_id: string; order_type: OrderType; order_side: OrderSide; order_status: OrderStatus; time_in_force: TimeInForce; quantity: string; limit_price?: string; origin: DecisionOrigin; }
export interface TradeFill extends DerivativesTenantScoped { fill_id: string; order_id?: string; trading_account_id: string; canonical_market_id: string; side: OrderSide; liquidity_role: FillLiquidityRole; price: string; quantity: string; fee_amount?: string; fee_asset_id?: string; executed_at: string; }
export interface Position extends DerivativesTenantScoped { position_id: string; position_epoch_id: string; trading_account_id: string; canonical_market_id: string; side: PositionSide; status: PositionStatus; size: string; entry_price?: string; realized_pnl?: string; unrealized_pnl?: string; accounting_method: AccountingMethod; }
export interface PositionEpoch extends DerivativesTenantScoped { position_epoch_id: string; position_id: string; opened_at: string; closed_at?: string; open_size: string; close_size?: string; }
export interface FundingPayment extends DerivativesTenantScoped { funding_payment_id: string; position_id?: string; trading_account_id: string; canonical_market_id: string; amount: string; asset_id: string; settled_at: string; }
export interface TradingFee extends DerivativesTenantScoped { trading_fee_id: string; fee_type: FeeType; amount: string; asset_id: string; related_ref?: EntityRef; charged_at: string; }
export interface LiquidationEvent extends DerivativesTenantScoped { liquidation_event_id: string; position_id: string; liquidation_type: LiquidationType; size: string; price: string; occurred_at: string; }
export interface PriceObservation extends DerivativesTenantScoped { price_observation_id: string; canonical_market_id: string; price_type: PriceType; price: string; source_finality: SourceFinality; observed_at: string; }
export interface RiskPolicy extends DerivativesTenantScoped { risk_policy_id: string; subject_ref: EntityRef; severity: RiskSeverity; max_leverage?: string; max_notional?: string; loss_limit?: string; authority_type: AuthorityType; }
export interface TradingStrategy extends DerivativesTenantScoped { trading_strategy_id: string; owner_ref?: EntityRef; name: string; }
export interface StrategyVersion extends DerivativesTenantScoped { strategy_version_id: string; trading_strategy_id: string; version: string; created_at: string; }
export interface ExecutionDecision extends DerivativesTenantScoped { execution_decision_id: string; origin: DecisionOrigin; strategy_version_id?: string; order_id?: string; decision_at: string; }
export interface ReconciliationVariance extends DerivativesTenantScoped { reconciliation_variance_id: string; variance_type: string; expected_value: string; observed_value: string; difference: string; severity: RiskSeverity; status: ReconciliationStatus; }
export interface ConnectorCheckpoint extends DerivativesTenantScoped { connector_checkpoint_id: string; connector_id: string; state: ConnectorState; checkpoint_value: string; advanced_at: string; }
export interface VenueCredentialReference extends DerivativesTenantScoped { venue_credential_reference_id: string; trading_account_id: string; secret_reference: string; authority_type: 'read_only'; }

export const DERIVATIVES_ENTITY_KINDS = [
  'trading_venue', 'venue_deployment', 'derivative_instrument', 'derivative_market', 'market_index',
  'trading_account', 'trading_subaccount', 'trading_vault', 'derivatives_order', 'derivatives_fill',
  'derivatives_position', 'position_epoch', 'collateral_account', 'margin_snapshot', 'funding_payment',
  'trading_fee', 'liquidation_event', 'price_observation', 'risk_policy', 'trading_strategy',
  'strategy_version', 'execution_decision', 'reconciliation_variance', 'connector_checkpoint',
  'venue_credential_reference',
] as const;

export type DerivativesEntityKind = typeof DERIVATIVES_ENTITY_KINDS[number];

export const DERIVATIVES_ACTOR_EDGE_LAYER_MAP = {
  REFERRED_TO_VENUE: 'H2H', FUNDED: 'H2H', SHARES_TRADING_ACCOUNT_WITH: 'H2H', AUTHORIZED: 'H2H', COPIES_STRATEGY_FROM: 'H2H', PARTICIPATES_IN_VAULT_WITH: 'H2H', MEMBER_OF_TRADING_ORG_WITH: 'H2H', POSSIBLY_COORDINATED_WITH: 'H2H', POSSIBLY_MIRRORS: 'H2H',
  DELEGATES_TRADING_TO: 'H2A', AUTHORIZES_MARKETS_FOR: 'H2A', SETS_RISK_POLICY_FOR: 'H2A', APPROVES_TRADE_FROM: 'H2A', FUNDS_AGENT: 'H2A', OVERRIDES_AGENT: 'H2A', REVOKES_TRADING_AUTHORITY: 'H2A',
  RECOMMENDS_TRADE_TO: 'A2H', REQUESTS_APPROVAL_FROM: 'A2H', WARNS: 'A2H', REQUESTS_MARGIN_FROM: 'A2H', REPORTS_PNL_TO: 'A2H', ESCALATES_RISK_TO: 'A2H', EXPLAINS_DECISION_TO: 'A2H',
  PROPOSES_TRADE_TO: 'A2A', REQUESTS_RISK_REVIEW_FROM: 'A2A', APPROVES_EXECUTION_FOR: 'A2A', VETOES_EXECUTION_FOR: 'A2A', ROUTES_ORDER_TO: 'A2A', VERIFIES_FILL_FROM: 'A2A', RECONCILES_POSITION_FOR: 'A2A',
} as const satisfies Record<string, Exclude<DerivativesActorLayerClassification, 'DOMAIN_EXCLUDED'>>;

export const DERIVATIVES_DOMAIN_EDGE_LAYER_MAP = {
  CONTROLS: 'DOMAIN_EXCLUDED', AUTHENTICATES: 'DOMAIN_EXCLUDED', HAS_SUBACCOUNT: 'DOMAIN_EXCLUDED', PARTICIPATES_IN_VAULT: 'DOMAIN_EXCLUDED', HOLDS_POSITION: 'DOMAIN_EXCLUDED', CREATED_ORDER: 'DOMAIN_EXCLUDED', CONTAINS_FILL: 'DOMAIN_EXCLUDED', EXECUTED_ON: 'DOMAIN_EXCLUDED', ON_MARKET: 'DOMAIN_EXCLUDED', LISTED_ON: 'DOMAIN_EXCLUDED', SETTLES_IN: 'DOMAIN_EXCLUDED', MARGINED_BY: 'DOMAIN_EXCLUDED', BACKED_BY: 'DOMAIN_EXCLUDED', PRICED_BY: 'DOMAIN_EXCLUDED', INCURRED_FEE: 'DOMAIN_EXCLUDED', PAID_FUNDING: 'DOMAIN_EXCLUDED', RECEIVED_FUNDING: 'DOMAIN_EXCLUDED', LIQUIDATED_BY: 'DOMAIN_EXCLUDED', GENERATED_PNL: 'DOMAIN_EXCLUDED', GOVERNED_BY_POLICY: 'DOMAIN_EXCLUDED', ATTRIBUTED_TO_CAMPAIGN: 'DOMAIN_EXCLUDED', PART_OF_JOURNEY: 'DOMAIN_EXCLUDED', DERIVED_FROM_EVENT: 'DOMAIN_EXCLUDED',
} as const satisfies Record<string, 'DOMAIN_EXCLUDED'>;

export const DERIVATIVES_EDGE_LAYER_MAP = {
  ...DERIVATIVES_ACTOR_EDGE_LAYER_MAP,
  ...DERIVATIVES_DOMAIN_EDGE_LAYER_MAP,
} as const;
