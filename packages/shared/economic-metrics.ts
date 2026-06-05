// =============================================================================
// Aether SDK — Unified Economic Metrics (additive extension)
//
// Provides the taxonomy and aggregation logic for Aether's unified economic
// intelligence layer. Distinguishes Web3 TVL, Web3 protocol exposure, Web2
// GMV/TPV/revenue, campaign spend, attributed revenue, x402 settlement value,
// and agentic economic activity — then presents all of it through one
// decomposable "Total Value Observed" metric.
//
// NON-NEGOTIABLE RULES:
//   1. TVL means protocol-level locked/committed capital only.
//   2. Entity-level wallet value is "protocol exposure", not TVL.
//   3. Web2 GMV/TPV/revenue are never labeled TVL.
//   4. Mixed currencies never produce unsafe flat totals.
//   5. Tenant isolation is always preserved.
//
// See docs/ECONOMIC-VALUE-FRAMING.md for the full business distinction.
// =============================================================================

import type { EconomicRail } from './economic';
import type { Rail } from './provenance';

// ---------------------------------------------------------------------------
// 1. Metric family taxonomy
// ---------------------------------------------------------------------------

export type EconomicMetricFamily =
  | 'web3_tvl'
  | 'web3_protocol_exposure'
  | 'web3_transaction_volume'
  | 'web3_protocol_fees'
  | 'web3_rewards'
  | 'web2_gmv'
  | 'web2_tpv'
  | 'web2_revenue'
  | 'web2_net_revenue'
  | 'saas_arr'
  | 'saas_mrr'
  | 'saas_nrr'
  | 'subscription_value'
  | 'invoice_volume'
  | 'campaign_spend'
  | 'attributed_revenue'
  | 'campaign_roas'
  | 'campaign_cac'
  | 'campaign_ltv'
  | 'agent_authorized_budget'
  | 'agent_spend'
  | 'agent_revenue'
  | 'agent_controlled_balance'
  | 'x402_settlement_value'
  | 'internal_credit_flow'
  | 'economic_exposure'
  | 'total_value_observed';

export type EconomicEntityType =
  | 'tenant'
  | 'org'
  | 'human'
  | 'user'
  | 'wallet'
  | 'agent'
  | 'protocol'
  | 'campaign'
  | 'contract'
  | 'resource'
  | 'service'
  | 'system';

export type EconomicWindow =
  | 'realtime'
  | '24h'
  | '7d'
  | '30d'
  | '90d'
  | 'lifetime'
  | 'custom';

export type EconomicValueDomain =
  | 'web2'
  | 'web3'
  | 'agentic'
  | 'campaign'
  | 'hybrid'
  | 'internal';

export type AttributionModel =
  | 'first_touch'
  | 'last_touch'
  | 'linear'
  | 'position_based'
  | 'algorithmic'
  | 'manual'
  | 'unknown';

export type AttributionWindow =
  | 'same_session'
  | '24h'
  | '7d'
  | '30d'
  | 'custom';

// ---------------------------------------------------------------------------
// 2. Amount, provenance, and warning types
// ---------------------------------------------------------------------------

export interface EconomicMetricAmount {
  native_amount?: number;
  native_currency?: string;
  normalized_amount?: number;
  normalized_currency?: string;
  usd_amount?: number;
  price_source?: string;
  price_timestamp?: string;
  conversion_rate?: number;
}

export interface EconomicMetricProvenance {
  source: string;
  source_event_ids?: string[];
  source_action_ids?: string[];
  source_table?: string;
  source_provider?: string;
  chain_id?: string | number;
  block_number?: number;
  transaction_hash?: string;
  pricing_source?: string;
  attribution_model?: AttributionModel;
  confidence?: number;
  computed_at: string;
}

export type EconomicWarningCode =
  | 'MIXED_CURRENCY'
  | 'MISSING_PRICE'
  | 'LOW_CONFIDENCE_ATTRIBUTION'
  | 'POSSIBLE_DOUBLE_COUNT'
  | 'STALE_PRICE'
  | 'PARTIAL_SOURCE_COVERAGE'
  | 'TENANT_SCOPE_FILTERED'
  | 'UNSUPPORTED_RAIL';

export interface EconomicMetricWarning {
  code: EconomicWarningCode;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  details?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// 3. Core metric record
// ---------------------------------------------------------------------------

export interface EconomicMetric {
  id: string;
  tenant_id: string;
  entity_id: string;
  entity_type: EconomicEntityType;
  metric_family: EconomicMetricFamily;
  domain: EconomicValueDomain;
  rail?: EconomicRail | Rail;
  window: EconomicWindow;
  amount: EconomicMetricAmount;
  dimensions?: Record<string, unknown>;
  provenance: EconomicMetricProvenance;
}

// ---------------------------------------------------------------------------
// 4. Web3 TVL types
// ---------------------------------------------------------------------------

export interface TVLPosition {
  protocol_id: string;
  chain_id: string;
  contract_address: string;
  token_address: string;
  token_symbol: string;
  native_amount: number;
  decimals?: number;
  usd_price?: number;
  usd_amount?: number;
  pricing_source?: string;
  price_timestamp?: string;
  block_number?: number;
  snapshot_at: string;
  computed_at: string;
  is_derivative?: boolean;
  is_bridge_asset?: boolean;
}

export interface ProtocolTVLBreakdown {
  protocol_id: string;
  tenant_id: string;
  total_tvl_usd?: number;
  positions: TVLPosition[];
  by_chain?: Record<string, number>;
  by_token?: Record<string, number>;
  warnings: EconomicMetricWarning[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// 5. Web3 protocol exposure (entity-level, NOT TVL)
// ---------------------------------------------------------------------------

export type ProtocolExposureType =
  | 'supplied'
  | 'staked'
  | 'lp'
  | 'escrowed'
  | 'bridged'
  | 'borrowed'
  | 'rewards'
  | 'other';

export interface ProtocolExposurePosition {
  protocol_id: string;
  chain_id: string;
  exposure_type: ProtocolExposureType;
  native_amount: number;
  native_currency: string;
  usd_amount?: number;
  pricing_source?: string;
  is_derivative_receipt?: boolean;
  underlying_position_id?: string;
}

export interface EntityProtocolExposure {
  entity_id: string;
  entity_type: EconomicEntityType;
  tenant_id: string;
  total_exposure_usd?: number;
  positions: ProtocolExposurePosition[];
  by_protocol?: Record<string, number>;
  double_count_filtered: boolean;
  warnings: EconomicMetricWarning[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// 6. Web2 economic metrics
// ---------------------------------------------------------------------------

export interface Web2EconomicMetrics {
  entity_id: string;
  tenant_id: string;
  window: EconomicWindow;
  gmv?: EconomicMetricAmount;
  tpv?: EconomicMetricAmount;
  revenue?: EconomicMetricAmount;
  net_revenue?: EconomicMetricAmount;
  refunds?: EconomicMetricAmount;
  chargebacks?: EconomicMetricAmount;
  aov?: EconomicMetricAmount;
  ltv?: EconomicMetricAmount;
  order_count?: number;
  repeat_purchase_rate?: number;
  conversion_rate?: number;
  mrr?: EconomicMetricAmount;
  arr?: EconomicMetricAmount;
  subscription_count?: number;
  churn_rate?: number;
  nrr?: number;
  warnings: EconomicMetricWarning[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// 7. Campaign economics
// ---------------------------------------------------------------------------

export interface CampaignEconomicMetrics {
  campaign_id: string;
  tenant_id: string;
  window: EconomicWindow;
  spend: EconomicMetricAmount;
  attributed_revenue?: EconomicMetricAmount;
  net_attributed_revenue?: EconomicMetricAmount;
  conversions?: number;
  acquired_customers?: number;
  roas?: number;
  cac?: EconomicMetricAmount;
  ltv?: EconomicMetricAmount;
  payback_period_days?: number;
  attribution_model: AttributionModel;
  attribution_window: AttributionWindow;
  attribution_confidence?: number;
  influenced_wallet_connects?: number;
  influenced_protocol_deposits?: EconomicMetricAmount;
  influenced_onchain_volume?: EconomicMetricAmount;
  influenced_x402_payments?: EconomicMetricAmount;
  influenced_agent_spend?: EconomicMetricAmount;
  warnings: EconomicMetricWarning[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// 8. Agentic / x402 economics
// ---------------------------------------------------------------------------

export interface AgentEconomicMetrics {
  agent_id: string;
  tenant_id: string;
  window: EconomicWindow;
  authorized_budget?: EconomicMetricAmount;
  spend?: EconomicMetricAmount;
  remaining_budget?: EconomicMetricAmount;
  revenue_generated?: EconomicMetricAmount;
  x402_settlement_value?: EconomicMetricAmount;
  internal_credit_flow?: EconomicMetricAmount;
  service_call_count?: number;
  unit_cost?: EconomicMetricAmount;
  roi?: number;
  roas?: number;
  settlement_success_rate?: number;
  settlement_failure_rate?: number;
  average_settlement_latency_ms?: number;
  controlled_wallet_count?: number;
  protocol_exposure?: EconomicMetricAmount;
  warnings: EconomicMetricWarning[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// 9. Unified Economic Breakdown (the decomposable derived metric)
// ---------------------------------------------------------------------------

export interface UnifiedEconomicBreakdown {
  entity_id: string;
  entity_type: EconomicEntityType;
  tenant_id: string;
  window: EconomicWindow;
  total_value_observed?: EconomicMetricAmount;
  web2?: {
    gmv?: EconomicMetricAmount;
    tpv?: EconomicMetricAmount;
    revenue?: EconomicMetricAmount;
    net_revenue?: EconomicMetricAmount;
    arr?: EconomicMetricAmount;
    mrr?: EconomicMetricAmount;
  };
  web3?: {
    tvl?: EconomicMetricAmount;
    protocol_exposure?: EconomicMetricAmount;
    transaction_volume?: EconomicMetricAmount;
    protocol_fees?: EconomicMetricAmount;
    rewards?: EconomicMetricAmount;
  };
  agentic?: {
    authorized_budget?: EconomicMetricAmount;
    spend?: EconomicMetricAmount;
    remaining_budget?: EconomicMetricAmount;
    revenue_generated?: EconomicMetricAmount;
    x402_settlement_value?: EconomicMetricAmount;
    internal_credit_flow?: EconomicMetricAmount;
  };
  campaigns?: {
    spend?: EconomicMetricAmount;
    attributed_revenue?: EconomicMetricAmount;
    roas?: number;
    cac?: EconomicMetricAmount;
    ltv?: EconomicMetricAmount;
    conversions?: number;
  };
  byCurrency?: Record<string, EconomicMetricAmount>;
  warnings: EconomicMetricWarning[];
  provenance?: EconomicMetricProvenance;
  computed_at: string;
}

// ---------------------------------------------------------------------------
// 10. Domain classification
// ---------------------------------------------------------------------------

const WEB2_RAILS: ReadonlySet<string> = new Set([
  'stripe', 'fiat', 'invoice', 'bank',
]);
const WEB3_RAILS: ReadonlySet<string> = new Set([
  'onchain', 'crypto',
]);
const AGENTIC_RAILS: ReadonlySet<string> = new Set([
  'x402', 'internal_credit', 'internal',
]);

export function classifyDomain(rail?: string, actorKind?: string): EconomicValueDomain {
  if (!rail) return 'hybrid';
  if (WEB2_RAILS.has(rail)) return 'web2';
  if (WEB3_RAILS.has(rail)) return 'web3';
  if (AGENTIC_RAILS.has(rail)) {
    if (actorKind === 'agent') return 'agentic';
    return 'agentic';
  }
  return 'hybrid';
}

// ---------------------------------------------------------------------------
// 11. Aggregation utilities
// ---------------------------------------------------------------------------

export function sumAmounts(
  amounts: ReadonlyArray<EconomicMetricAmount>,
): { total: EconomicMetricAmount; byCurrency: Record<string, number>; warnings: EconomicMetricWarning[] } {
  const byCurrency: Record<string, number> = {};
  const warnings: EconomicMetricWarning[] = [];
  let totalUsd = 0;
  let hasUsd = false;
  let missingPrice = false;

  for (const amt of amounts) {
    if (amt.native_currency && amt.native_amount !== undefined) {
      byCurrency[amt.native_currency] = (byCurrency[amt.native_currency] ?? 0) + amt.native_amount;
    }
    if (amt.usd_amount !== undefined) {
      totalUsd += amt.usd_amount;
      hasUsd = true;
    } else if (amt.native_amount !== undefined && amt.native_amount > 0) {
      missingPrice = true;
    }
  }

  if (missingPrice) {
    warnings.push({
      code: 'MISSING_PRICE',
      message: 'One or more amounts lack USD conversion; total_value_observed may be understated.',
      severity: 'warning',
    });
  }

  const currencies = Object.keys(byCurrency);
  if (currencies.length > 1) {
    warnings.push({
      code: 'MIXED_CURRENCY',
      message: `Multiple native currencies detected: ${currencies.join(', ')}. Flat totals use USD conversion only.`,
      severity: 'warning',
    });
  }

  const total: EconomicMetricAmount = {};
  if (hasUsd) {
    total.usd_amount = totalUsd;
    total.normalized_amount = totalUsd;
    total.normalized_currency = 'USD';
  }
  if (currencies.length === 1) {
    total.native_currency = currencies[0];
    total.native_amount = byCurrency[currencies[0]];
  }

  return { total, byCurrency, warnings };
}

export function computeROAS(
  attributedRevenue?: EconomicMetricAmount,
  spend?: EconomicMetricAmount,
): number | undefined {
  const rev = attributedRevenue?.usd_amount;
  const cost = spend?.usd_amount;
  if (rev === undefined || cost === undefined || cost === 0) return undefined;
  return rev / cost;
}

export function computeCAC(
  spend?: EconomicMetricAmount,
  acquiredCustomers?: number,
): EconomicMetricAmount | undefined {
  if (!spend?.usd_amount || !acquiredCustomers || acquiredCustomers === 0) return undefined;
  return {
    usd_amount: spend.usd_amount / acquiredCustomers,
    normalized_amount: spend.usd_amount / acquiredCustomers,
    normalized_currency: 'USD',
  };
}

export function computeRemainingBudget(
  authorized?: EconomicMetricAmount,
  spent?: EconomicMetricAmount,
): EconomicMetricAmount | undefined {
  if (authorized?.usd_amount === undefined) return undefined;
  const spentAmt = spent?.usd_amount ?? 0;
  return {
    usd_amount: authorized.usd_amount - spentAmt,
    normalized_amount: authorized.usd_amount - spentAmt,
    normalized_currency: 'USD',
  };
}

export function computeAgentROI(
  revenue?: EconomicMetricAmount,
  spend?: EconomicMetricAmount,
): number | undefined {
  const rev = revenue?.usd_amount;
  const cost = spend?.usd_amount;
  if (rev === undefined || cost === undefined || cost === 0) return undefined;
  return rev / cost;
}

// ---------------------------------------------------------------------------
// 12. Double-counting detection
// ---------------------------------------------------------------------------

export function detectDoubleCountRisk(
  positions: ReadonlyArray<{ is_derivative_receipt?: boolean; underlying_position_id?: string }>,
): EconomicMetricWarning[] {
  const warnings: EconomicMetricWarning[] = [];
  const underlyingIds = new Set<string>();
  const derivativeUnderlyings = new Set<string>();

  for (const pos of positions) {
    if (pos.is_derivative_receipt && pos.underlying_position_id) {
      derivativeUnderlyings.add(pos.underlying_position_id);
    }
    if (pos.underlying_position_id) {
      underlyingIds.add(pos.underlying_position_id);
    }
  }

  for (const id of derivativeUnderlyings) {
    if (underlyingIds.has(id)) {
      warnings.push({
        code: 'POSSIBLE_DOUBLE_COUNT',
        message: `Derivative receipt token and underlying position both present for position ${id}. Value may be double-counted.`,
        severity: 'warning',
        details: { position_id: id },
      });
    }
  }

  return warnings;
}

// ---------------------------------------------------------------------------
// 13. Stale price detection
// ---------------------------------------------------------------------------

const STALE_PRICE_THRESHOLD_MS = 60 * 60 * 1000; // 1 hour

export function detectStalePrices(
  positions: ReadonlyArray<{ price_timestamp?: string; token_symbol?: string }>,
  nowMs: number = Date.now(),
): EconomicMetricWarning[] {
  const warnings: EconomicMetricWarning[] = [];
  for (const pos of positions) {
    if (!pos.price_timestamp) continue;
    const priceAge = nowMs - new Date(pos.price_timestamp).getTime();
    if (priceAge > STALE_PRICE_THRESHOLD_MS) {
      warnings.push({
        code: 'STALE_PRICE',
        message: `Price for ${pos.token_symbol ?? 'unknown'} is ${Math.round(priceAge / 60000)}min old.`,
        severity: 'warning',
        details: { price_timestamp: pos.price_timestamp, age_ms: priceAge },
      });
    }
  }
  return warnings;
}

// ---------------------------------------------------------------------------
// 14. Unified breakdown builder
// ---------------------------------------------------------------------------

export interface BuildBreakdownInput {
  entity_id: string;
  entity_type: EconomicEntityType;
  tenant_id: string;
  window: EconomicWindow;
  web2?: Web2EconomicMetrics;
  web3_tvl?: ProtocolTVLBreakdown;
  web3_exposure?: EntityProtocolExposure;
  agent?: AgentEconomicMetrics;
  campaigns?: CampaignEconomicMetrics[];
  computed_at?: string;
}

export function buildUnifiedBreakdown(input: BuildBreakdownInput): UnifiedEconomicBreakdown {
  const warnings: EconomicMetricWarning[] = [];
  const tvoComponents: EconomicMetricAmount[] = [];

  const web2 = input.web2 ? {
    gmv: input.web2.gmv,
    tpv: input.web2.tpv,
    revenue: input.web2.revenue,
    net_revenue: input.web2.net_revenue,
    arr: input.web2.arr,
    mrr: input.web2.mrr,
  } : undefined;

  if (input.web2?.revenue) tvoComponents.push(input.web2.revenue);
  if (input.web2) warnings.push(...input.web2.warnings);

  const web3: UnifiedEconomicBreakdown['web3'] = {};
  if (input.web3_tvl) {
    web3.tvl = { usd_amount: input.web3_tvl.total_tvl_usd, normalized_currency: 'USD' };
    tvoComponents.push(web3.tvl);
    warnings.push(...input.web3_tvl.warnings);
  }
  if (input.web3_exposure) {
    web3.protocol_exposure = { usd_amount: input.web3_exposure.total_exposure_usd, normalized_currency: 'USD' };
    tvoComponents.push(web3.protocol_exposure);
    warnings.push(...input.web3_exposure.warnings);
  }

  const agentic = input.agent ? {
    authorized_budget: input.agent.authorized_budget,
    spend: input.agent.spend,
    remaining_budget: input.agent.remaining_budget,
    revenue_generated: input.agent.revenue_generated,
    x402_settlement_value: input.agent.x402_settlement_value,
    internal_credit_flow: input.agent.internal_credit_flow,
  } : undefined;

  if (input.agent?.spend) tvoComponents.push(input.agent.spend);
  if (input.agent?.x402_settlement_value) tvoComponents.push(input.agent.x402_settlement_value);
  if (input.agent) warnings.push(...input.agent.warnings);

  let campaignSummary: UnifiedEconomicBreakdown['campaigns'] | undefined;
  if (input.campaigns && input.campaigns.length > 0) {
    const allSpends = input.campaigns.map(c => c.spend).filter(Boolean);
    const allRevenues = input.campaigns.map(c => c.attributed_revenue).filter((a): a is EconomicMetricAmount => !!a);
    const totalConversions = input.campaigns.reduce((sum, c) => sum + (c.conversions ?? 0), 0);
    const spendResult = sumAmounts(allSpends);
    const revenueResult = sumAmounts(allRevenues);
    campaignSummary = {
      spend: spendResult.total,
      attributed_revenue: revenueResult.total,
      roas: computeROAS(revenueResult.total, spendResult.total),
      conversions: totalConversions || undefined,
    };
    if (spendResult.total) tvoComponents.push(spendResult.total);
    for (const c of input.campaigns) warnings.push(...c.warnings);
  }

  const { total: tvo, byCurrency, warnings: sumWarnings } = sumAmounts(tvoComponents);

  return {
    entity_id: input.entity_id,
    entity_type: input.entity_type,
    tenant_id: input.tenant_id,
    window: input.window,
    total_value_observed: tvo,
    web2,
    web3: (web3.tvl || web3.protocol_exposure) ? web3 : undefined,
    agentic,
    campaigns: campaignSummary,
    byCurrency: Object.keys(byCurrency).length > 0
      ? Object.fromEntries(Object.entries(byCurrency).map(([k, v]) => [k, { native_amount: v, native_currency: k }]))
      : undefined,
    warnings: [...warnings, ...sumWarnings],
    computed_at: input.computed_at ?? new Date().toISOString(),
  };
}

// ---------------------------------------------------------------------------
// 15. Tenant scope guard
// ---------------------------------------------------------------------------

export function assertTenantScope(
  requestTenantId: string,
  resourceTenantId: string,
): void {
  if (requestTenantId !== resourceTenantId) {
    throw new Error(
      `Tenant isolation violation: request tenant ${requestTenantId} cannot access resource owned by ${resourceTenantId}`,
    );
  }
}
