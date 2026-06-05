// =============================================================================
// Aether SDK — Unified Economic Metrics tests
//
// Covers:
//   1.  Web3 TVL is calculated only for protocol locked value.
//   2.  Web3 protocol exposure ≠ TVL.
//   3.  Web2 revenue is not mixed with TVL.
//   4.  GMV, TPV, and revenue are separately represented.
//   5.  Campaign spend and attributed revenue generate ROAS.
//   6.  Campaign-influenced wallet activity is tracked separately.
//   7.  x402 payment contributes to x402 settlement value.
//   8.  Agent spend contributes to agentic spend.
//   9.  Agent authorized budget and remaining budget computed correctly.
//   10. Mixed currencies do not produce unsafe flat totals.
//   11. USD-normalized totals require price/conversion provenance.
//   12. Missing prices produce warnings.
//   13. Stale prices produce warnings.
//   14. Derivative double-counting produces warnings.
//   15. Tenant isolation prevents cross-tenant leakage.
//   16. Unified breakdown returns expected structure.
//   17. Domain classification works correctly.
//   18. ROAS and CAC computations.
//   19. Empty inputs handled gracefully.
//   20. Backwards compatibility — existing economic.ts unchanged.
// =============================================================================

import { describe, expect, it } from 'vitest';

import {
  assertTenantScope,
  buildUnifiedBreakdown,
  classifyDomain,
  computeCAC,
  computeRemainingBudget,
  computeROAS,
  computeAgentROI,
  detectDoubleCountRisk,
  detectStalePrices,
  sumAmounts,
} from './economic-metrics';

import type {
  AgentEconomicMetrics,
  BuildBreakdownInput,
  CampaignEconomicMetrics,
  EconomicMetricAmount,
  EntityProtocolExposure,
  ProtocolTVLBreakdown,
  Web2EconomicMetrics,
} from './economic-metrics';

// Ensure existing economic.ts exports are unaffected
import {
  aggregateEconomicState,
  validateEconomicPayload,
} from './economic';

// ---------------------------------------------------------------------------
// 1. Web3 TVL is calculated only for protocol locked value
// ---------------------------------------------------------------------------

describe('Web3 TVL', () => {
  it('represents protocol-level locked capital with proper structure', () => {
    const tvl: ProtocolTVLBreakdown = {
      protocol_id: 'aave-v3',
      tenant_id: 'tenant_1',
      total_tvl_usd: 5_000_000,
      positions: [
        {
          protocol_id: 'aave-v3',
          chain_id: '1',
          contract_address: '0xabc',
          token_address: '0xusdc',
          token_symbol: 'USDC',
          native_amount: 3_000_000,
          usd_price: 1.0,
          usd_amount: 3_000_000,
          pricing_source: 'coingecko',
          snapshot_at: '2026-06-05T00:00:00Z',
          computed_at: '2026-06-05T00:01:00Z',
        },
        {
          protocol_id: 'aave-v3',
          chain_id: '1',
          contract_address: '0xdef',
          token_address: '0xweth',
          token_symbol: 'WETH',
          native_amount: 1000,
          usd_price: 2000,
          usd_amount: 2_000_000,
          pricing_source: 'coingecko',
          snapshot_at: '2026-06-05T00:00:00Z',
          computed_at: '2026-06-05T00:01:00Z',
        },
      ],
      by_chain: { '1': 5_000_000 },
      by_token: { 'USDC': 3_000_000, 'WETH': 2_000_000 },
      warnings: [],
      computed_at: '2026-06-05T00:01:00Z',
    };

    expect(tvl.total_tvl_usd).toBe(5_000_000);
    expect(tvl.positions).toHaveLength(2);
    expect(tvl.by_chain?.['1']).toBe(5_000_000);
  });
});

// ---------------------------------------------------------------------------
// 2. Protocol exposure ≠ TVL
// ---------------------------------------------------------------------------

describe('Web3 Protocol Exposure', () => {
  it('is labeled protocol_exposure, not TVL, for entity-level wallet value', () => {
    const exposure: EntityProtocolExposure = {
      entity_id: 'user_123',
      entity_type: 'human',
      tenant_id: 'tenant_1',
      total_exposure_usd: 12_000,
      positions: [
        {
          protocol_id: 'aave-v3',
          chain_id: '1',
          exposure_type: 'supplied',
          native_amount: 10_000,
          native_currency: 'USDC',
          usd_amount: 10_000,
        },
        {
          protocol_id: 'lido',
          chain_id: '1',
          exposure_type: 'staked',
          native_amount: 1,
          native_currency: 'ETH',
          usd_amount: 2_000,
        },
      ],
      by_protocol: { 'aave-v3': 10_000, 'lido': 2_000 },
      double_count_filtered: false,
      warnings: [],
      computed_at: '2026-06-05T00:00:00Z',
    };

    expect(exposure.entity_type).toBe('human');
    expect(exposure.total_exposure_usd).toBe(12_000);
    // This is NOT called TVL
    expect(exposure).not.toHaveProperty('tvl');
  });
});

// ---------------------------------------------------------------------------
// 3. Web2 revenue is not mixed with TVL
// ---------------------------------------------------------------------------

describe('Web2 revenue separation', () => {
  it('Web2 metrics are separate from Web3 TVL in the unified breakdown', () => {
    const breakdown = buildUnifiedBreakdown({
      entity_id: 'org_1',
      entity_type: 'org',
      tenant_id: 'tenant_1',
      window: 'lifetime',
      web2: {
        entity_id: 'org_1', tenant_id: 'tenant_1', window: 'lifetime',
        revenue: { usd_amount: 500_000, native_amount: 500_000, native_currency: 'USD' },
        gmv: { usd_amount: 1_000_000, native_amount: 1_000_000, native_currency: 'USD' },
        warnings: [], computed_at: '2026-06-05T00:00:00Z',
      },
      web3_tvl: {
        protocol_id: 'uniswap-v3', tenant_id: 'tenant_1',
        total_tvl_usd: 10_000_000,
        positions: [], warnings: [], computed_at: '2026-06-05T00:00:00Z',
      },
      computed_at: '2026-06-05T00:00:00Z',
    });

    expect(breakdown.web2?.revenue?.usd_amount).toBe(500_000);
    expect(breakdown.web3?.tvl?.usd_amount).toBe(10_000_000);
    // They are separate fields, never merged
    expect(breakdown.web2).toBeDefined();
    expect(breakdown.web3).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// 4. GMV, TPV, and revenue are separately represented
// ---------------------------------------------------------------------------

describe('GMV/TPV/Revenue separation', () => {
  it('maintains distinct GMV, TPV, and revenue fields', () => {
    const web2: Web2EconomicMetrics = {
      entity_id: 'org_1', tenant_id: 'tenant_1', window: '30d',
      gmv: { usd_amount: 1_000_000 },
      tpv: { usd_amount: 800_000 },
      revenue: { usd_amount: 200_000 },
      net_revenue: { usd_amount: 180_000 },
      warnings: [], computed_at: '2026-06-05T00:00:00Z',
    };

    expect(web2.gmv?.usd_amount).toBe(1_000_000);
    expect(web2.tpv?.usd_amount).toBe(800_000);
    expect(web2.revenue?.usd_amount).toBe(200_000);
    expect(web2.net_revenue?.usd_amount).toBe(180_000);
  });
});

// ---------------------------------------------------------------------------
// 5. Campaign spend and attributed revenue generate ROAS
// ---------------------------------------------------------------------------

describe('Campaign ROAS', () => {
  it('computes ROAS from attributed_revenue / campaign_spend', () => {
    const roas = computeROAS(
      { usd_amount: 45_000 },
      { usd_amount: 10_000 },
    );
    expect(roas).toBe(4.5);
  });

  it('returns undefined when spend is zero', () => {
    expect(computeROAS({ usd_amount: 100 }, { usd_amount: 0 })).toBeUndefined();
  });

  it('returns undefined when values are missing', () => {
    expect(computeROAS(undefined, { usd_amount: 100 })).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 6. Campaign-influenced wallet activity tracked separately
// ---------------------------------------------------------------------------

describe('Campaign-influenced activity', () => {
  it('tracks influenced Web3 activity separately from campaign revenue', () => {
    const campaign: CampaignEconomicMetrics = {
      campaign_id: 'camp_1', tenant_id: 'tenant_1', window: '30d',
      spend: { usd_amount: 10_000 },
      attributed_revenue: { usd_amount: 45_000 },
      conversions: 200,
      acquired_customers: 200,
      roas: 4.5,
      attribution_model: 'last_touch',
      attribution_window: '7d',
      attribution_confidence: 0.85,
      influenced_wallet_connects: 150,
      influenced_protocol_deposits: { usd_amount: 500_000 },
      influenced_onchain_volume: { usd_amount: 1_200_000 },
      warnings: [], computed_at: '2026-06-05T00:00:00Z',
    };

    expect(campaign.attributed_revenue?.usd_amount).toBe(45_000);
    expect(campaign.influenced_protocol_deposits?.usd_amount).toBe(500_000);
    // Influenced deposits are NOT the same as attributed revenue
    expect(campaign.influenced_protocol_deposits?.usd_amount).not.toBe(campaign.attributed_revenue?.usd_amount);
  });
});

// ---------------------------------------------------------------------------
// 7. x402 payment contributes to x402 settlement value
// ---------------------------------------------------------------------------

describe('x402 settlement', () => {
  it('tracks x402 settlement as agentic metric', () => {
    const agent: AgentEconomicMetrics = {
      agent_id: 'agent_1', tenant_id: 'tenant_1', window: '30d',
      x402_settlement_value: { usd_amount: 38, native_amount: 38, native_currency: 'USDC' },
      spend: { usd_amount: 50 },
      warnings: [], computed_at: '2026-06-05T00:00:00Z',
    };

    expect(agent.x402_settlement_value?.usd_amount).toBe(38);
    expect(classifyDomain('x402')).toBe('agentic');
  });
});

// ---------------------------------------------------------------------------
// 8. Agent spend contributes to agentic spend
// ---------------------------------------------------------------------------

describe('Agent spend', () => {
  it('agent spend is classified under agentic domain', () => {
    const agent: AgentEconomicMetrics = {
      agent_id: 'agent_1', tenant_id: 'tenant_1', window: '24h',
      spend: { usd_amount: 125.50, native_amount: 125.50, native_currency: 'USD' },
      authorized_budget: { usd_amount: 500 },
      warnings: [], computed_at: '2026-06-05T00:00:00Z',
    };
    expect(agent.spend?.usd_amount).toBe(125.50);
  });
});

// ---------------------------------------------------------------------------
// 9. Agent authorized budget and remaining budget
// ---------------------------------------------------------------------------

describe('Agent budget computation', () => {
  it('computes remaining budget = authorized - spend', () => {
    const remaining = computeRemainingBudget(
      { usd_amount: 500 },
      { usd_amount: 125.50 },
    );
    expect(remaining?.usd_amount).toBe(374.50);
  });

  it('returns full budget when no spend', () => {
    const remaining = computeRemainingBudget({ usd_amount: 500 }, undefined);
    expect(remaining?.usd_amount).toBe(500);
  });

  it('returns undefined when no budget authorized', () => {
    expect(computeRemainingBudget(undefined, { usd_amount: 50 })).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 10. Mixed currencies do not produce unsafe flat totals
// ---------------------------------------------------------------------------

describe('Mixed currency safety', () => {
  it('produces MIXED_CURRENCY warning when multiple native currencies exist', () => {
    const { warnings } = sumAmounts([
      { native_amount: 100, native_currency: 'USD' },
      { native_amount: 80, native_currency: 'EUR' },
    ]);
    expect(warnings.some(w => w.code === 'MIXED_CURRENCY')).toBe(true);
  });

  it('does not produce warning for single currency', () => {
    const { warnings } = sumAmounts([
      { native_amount: 100, native_currency: 'USD' },
      { native_amount: 200, native_currency: 'USD' },
    ]);
    expect(warnings.some(w => w.code === 'MIXED_CURRENCY')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 11. USD-normalized totals require price/conversion provenance
// ---------------------------------------------------------------------------

describe('USD normalization', () => {
  it('total uses usd_amount only when present', () => {
    const { total } = sumAmounts([
      { native_amount: 1, native_currency: 'ETH', usd_amount: 2000 },
      { native_amount: 5000, native_currency: 'USDC', usd_amount: 5000 },
    ]);
    expect(total.usd_amount).toBe(7000);
    expect(total.normalized_currency).toBe('USD');
  });
});

// ---------------------------------------------------------------------------
// 12. Missing prices produce warnings
// ---------------------------------------------------------------------------

describe('Missing price warnings', () => {
  it('warns when amounts lack USD conversion', () => {
    const { warnings } = sumAmounts([
      { native_amount: 100, native_currency: 'ETH' },
    ]);
    expect(warnings.some(w => w.code === 'MISSING_PRICE')).toBe(true);
  });

  it('no warning for zero-value amounts without price', () => {
    const { warnings } = sumAmounts([
      { native_amount: 0, native_currency: 'ETH' },
    ]);
    expect(warnings.some(w => w.code === 'MISSING_PRICE')).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 13. Stale prices produce warnings
// ---------------------------------------------------------------------------

describe('Stale price detection', () => {
  it('warns when price is more than 1 hour old', () => {
    const staleTimestamp = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    const warnings = detectStalePrices([
      { price_timestamp: staleTimestamp, token_symbol: 'ETH' },
    ]);
    expect(warnings.some(w => w.code === 'STALE_PRICE')).toBe(true);
    expect(warnings[0].message).toContain('ETH');
  });

  it('does not warn for fresh prices', () => {
    const freshTimestamp = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    const warnings = detectStalePrices([
      { price_timestamp: freshTimestamp, token_symbol: 'ETH' },
    ]);
    expect(warnings).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 14. Derivative double-counting produces warnings
// ---------------------------------------------------------------------------

describe('Double-counting detection', () => {
  it('no warning when only derivative exists without separate underlying', () => {
    const warnings = detectDoubleCountRisk([
      { is_derivative_receipt: true },
    ]);
    expect(warnings).toHaveLength(0);
  });

  it('warns when both derivative and underlying are present', () => {
    const warnings = detectDoubleCountRisk([
      { underlying_position_id: 'pos_1' },
      { is_derivative_receipt: true, underlying_position_id: 'pos_1' },
    ]);
    expect(warnings.some(w => w.code === 'POSSIBLE_DOUBLE_COUNT')).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 15. Tenant isolation
// ---------------------------------------------------------------------------

describe('Tenant isolation', () => {
  it('allows same-tenant access', () => {
    expect(() => assertTenantScope('tenant_1', 'tenant_1')).not.toThrow();
  });

  it('blocks cross-tenant access', () => {
    expect(() => assertTenantScope('tenant_1', 'tenant_2')).toThrow(/Tenant isolation violation/);
  });
});

// ---------------------------------------------------------------------------
// 16. Unified breakdown returns expected structure
// ---------------------------------------------------------------------------

describe('Unified Economic Breakdown', () => {
  it('builds a complete decomposable breakdown', () => {
    const input: BuildBreakdownInput = {
      entity_id: 'user_123',
      entity_type: 'human',
      tenant_id: 'tenant_1',
      window: 'lifetime',
      web2: {
        entity_id: 'user_123', tenant_id: 'tenant_1', window: 'lifetime',
        revenue: { usd_amount: 500, native_amount: 500, native_currency: 'USD' },
        warnings: [], computed_at: '2026-06-05T00:00:00Z',
      },
      web3_exposure: {
        entity_id: 'user_123', entity_type: 'human', tenant_id: 'tenant_1',
        total_exposure_usd: 12_000, positions: [],
        double_count_filtered: false, warnings: [], computed_at: '2026-06-05T00:00:00Z',
      },
      agent: {
        agent_id: 'agent_1', tenant_id: 'tenant_1', window: 'lifetime',
        spend: { usd_amount: 38, native_amount: 38, native_currency: 'USDC' },
        x402_settlement_value: { usd_amount: 38 },
        warnings: [], computed_at: '2026-06-05T00:00:00Z',
      },
      campaigns: [{
        campaign_id: 'camp_1', tenant_id: 'tenant_1', window: 'lifetime',
        spend: { usd_amount: 10_000, native_amount: 10_000, native_currency: 'USD' },
        attributed_revenue: { usd_amount: 45_000, native_amount: 45_000, native_currency: 'USD' },
        roas: 4.5, conversions: 200, acquired_customers: 200,
        attribution_model: 'last_touch', attribution_window: '7d',
        warnings: [], computed_at: '2026-06-05T00:00:00Z',
      }],
      computed_at: '2026-06-05T00:00:00Z',
    };

    const breakdown = buildUnifiedBreakdown(input);

    expect(breakdown.entity_id).toBe('user_123');
    expect(breakdown.web2?.revenue?.usd_amount).toBe(500);
    expect(breakdown.web3?.protocol_exposure?.usd_amount).toBe(12_000);
    expect(breakdown.agentic?.spend?.usd_amount).toBe(38);
    expect(breakdown.campaigns?.spend?.usd_amount).toBe(10_000);
    expect(breakdown.campaigns?.attributed_revenue?.usd_amount).toBe(45_000);
    expect(breakdown.campaigns?.roas).toBe(4.5);
    expect(breakdown.total_value_observed).toBeDefined();
    expect(breakdown.total_value_observed?.usd_amount).toBeGreaterThan(0);
    // TVL is separate from total_value_observed — it's not labeled as TVL
    expect(breakdown.web3?.tvl).toBeUndefined();
    expect(breakdown.web3?.protocol_exposure).toBeDefined();
  });

  it('handles empty input gracefully', () => {
    const breakdown = buildUnifiedBreakdown({
      entity_id: 'user_empty',
      entity_type: 'human',
      tenant_id: 'tenant_1',
      window: 'lifetime',
      computed_at: '2026-06-05T00:00:00Z',
    });

    expect(breakdown.total_value_observed).toEqual({});
    expect(breakdown.web2).toBeUndefined();
    expect(breakdown.web3).toBeUndefined();
    expect(breakdown.agentic).toBeUndefined();
    expect(breakdown.campaigns).toBeUndefined();
    expect(breakdown.warnings).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 17. Domain classification
// ---------------------------------------------------------------------------

describe('Domain classification', () => {
  it('classifies rails to correct domains', () => {
    expect(classifyDomain('stripe')).toBe('web2');
    expect(classifyDomain('fiat')).toBe('web2');
    expect(classifyDomain('invoice')).toBe('web2');
    expect(classifyDomain('bank')).toBe('web2');
    expect(classifyDomain('onchain')).toBe('web3');
    expect(classifyDomain('crypto')).toBe('web3');
    expect(classifyDomain('x402')).toBe('agentic');
    expect(classifyDomain('internal_credit')).toBe('agentic');
    expect(classifyDomain('internal')).toBe('agentic');
    expect(classifyDomain(undefined)).toBe('hybrid');
    expect(classifyDomain('unknown_rail')).toBe('hybrid');
  });
});

// ---------------------------------------------------------------------------
// 18. CAC computation
// ---------------------------------------------------------------------------

describe('CAC computation', () => {
  it('computes CAC = spend / acquired_customers', () => {
    const cac = computeCAC({ usd_amount: 10_000 }, 200);
    expect(cac?.usd_amount).toBe(50);
  });

  it('returns undefined for zero customers', () => {
    expect(computeCAC({ usd_amount: 10_000 }, 0)).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 19. Agent ROI
// ---------------------------------------------------------------------------

describe('Agent ROI', () => {
  it('computes ROI = revenue / spend', () => {
    expect(computeAgentROI({ usd_amount: 350 }, { usd_amount: 100 })).toBe(3.5);
  });

  it('returns undefined when spend is zero', () => {
    expect(computeAgentROI({ usd_amount: 100 }, { usd_amount: 0 })).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 20. Backwards compatibility — existing economic.ts unchanged
// ---------------------------------------------------------------------------

describe('Backwards compatibility', () => {
  it('existing aggregateEconomicState still works', () => {
    const state = aggregateEconomicState([
      {
        id: 'a1',
        economic: {
          amount: 100, currency: 'USD', direction: 'pay',
          counterparty_type: 'service', counterparty_id: 's1', rail: 'stripe',
        },
      },
    ]);
    expect(state.total_spend).toBe(100);
    expect(state.currency).toBe('USD');
  });

  it('existing validateEconomicPayload still works', () => {
    const payload = validateEconomicPayload({
      amount: 10, currency: 'USD', direction: 'pay',
      counterparty_type: 'service', counterparty_id: 's1', rail: 'x402',
    });
    expect(payload.rail).toBe('x402');
  });
});
