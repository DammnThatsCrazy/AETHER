import { describe, expect, it } from 'vitest';

import { isRollupEligible } from './value';
import type { AetherValue } from './value';

function val(overrides: Partial<AetherValue> = {}): AetherValue {
  return {
    id: 'v1',
    metric: 'balance',
    metric_kind: 'balance',
    native: { amount: '1.5', currency: 'ETH' },
    valuation: {
      usd_value: '3000',
      computed_at: '2026-07-01T00:00:00Z',
      freshness: 'live',
      confidence: 'high',
      valuation_method: 'market_price',
    },
    ownership: { relationship: 'owned', confidence: 'high' },
    status: {
      metric_kind: 'balance',
      reconciliation_state: 'matched',
      data_freshness: 'live',
      include_in_rollups: true,
    },
    display: { primary: '$3,000.00 USD', secondary: '1.5 ETH' },
    source: { source_system: 'test', computed_at: '2026-07-01T00:00:00Z' },
    ...overrides,
  };
}

describe('value contract — isRollupEligible', () => {
  it('includes a priced, rollup-eligible value', () => {
    expect(isRollupEligible(val())).toBe(true);
  });

  it('excludes a value with no USD price (unknown != rollup)', () => {
    const v = val();
    v.valuation.usd_value = null;
    expect(isRollupEligible(v)).toBe(false);
  });

  it('excludes a value explicitly marked out of rollups', () => {
    const v = val();
    v.status.include_in_rollups = false;
    v.status.exclusion_reason = 'testnet_asset';
    expect(isRollupEligible(v)).toBe(false);
  });

  it('a null usd_value is distinct from a "0" usd_value', () => {
    const unavailable = val();
    unavailable.valuation.usd_value = null;
    const zero = val();
    zero.valuation.usd_value = '0';
    // A genuine zero is eligible; an unknown/unavailable value is not.
    expect(isRollupEligible(zero)).toBe(true);
    expect(isRollupEligible(unavailable)).toBe(false);
  });
});
