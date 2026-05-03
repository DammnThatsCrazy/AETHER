// =============================================================================
// Aether SDK — Economic Observability tests
//
// Covers:
//   • Action economic field validation
//   • Handshake lifecycle transitions
//   • Resource creation + typing
//   • Relationship extension validation
//   • State aggregation logic
//   • Authorization validation
//   • Referential integrity
//   • Integration: H2A → A2A flows, handshake request→pay→resolve,
//     spend → revenue outcome linkage
//   • Edge cases: zero-value, failed payments, missing counterparties,
//     partial flows
// =============================================================================

import { describe, expect, it } from 'vitest';

import {
  aggregateEconomicState,
  assertActionReference,
  assertHandshakeReference,
  assertHandshakeTransition,
  createHandshake,
  createResourceNode,
  EconomicValidationError,
  HandshakeStateError,
  isEconomicPayload,
  RelationshipIntegrityError,
  transitionHandshake,
  validateAuthorization,
  validateEconomicPayload,
  validateHandshake,
  validateRelationshipExtensions,
  validateResourceNode,
} from './economic';
import type {
  EconomicActionLike,
  EconomicPayload,
  Handshake,
  RelationshipExtensions,
  ResourceNode,
} from './economic';

// ---------------------------------------------------------------------------
// Economic payload
// ---------------------------------------------------------------------------

describe('validateEconomicPayload', () => {
  const valid: EconomicPayload = {
    amount: 12.5,
    currency: 'USD',
    direction: 'pay',
    counterparty_type: 'service',
    counterparty_id: 'svc_openai',
    rail: 'stripe',
  };

  it('accepts a fully-valid payload', () => {
    expect(validateEconomicPayload(valid)).toEqual(valid);
  });

  it('accepts amount === 0 (zero-value transaction)', () => {
    expect(validateEconomicPayload({ ...valid, amount: 0 })).toMatchObject({ amount: 0 });
  });

  it('accepts crypto / bank / internal rails', () => {
    for (const rail of ['crypto', 'bank', 'internal'] as const) {
      expect(validateEconomicPayload({ ...valid, rail })).toMatchObject({ rail });
    }
  });

  it('accepts the canonical Aether rails (fiat | invoice | onchain | x402 | internal_credit)', () => {
    for (const rail of ['fiat', 'invoice', 'onchain', 'x402', 'internal_credit'] as const) {
      expect(validateEconomicPayload({ ...valid, rail })).toMatchObject({ rail });
    }
  });

  it('does not hardcode the currency list', () => {
    expect(validateEconomicPayload({ ...valid, currency: 'XBT' })).toMatchObject({ currency: 'XBT' });
    expect(validateEconomicPayload({ ...valid, currency: 'USDC' })).toMatchObject({
      currency: 'USDC',
    });
  });

  it.each([
    ['negative amount', { ...valid, amount: -1 }],
    ['NaN amount', { ...valid, amount: Number.NaN }],
    ['non-number amount', { ...valid, amount: '1' }],
    ['empty currency', { ...valid, currency: '' }],
    ['unknown direction', { ...valid, direction: 'transfer' }],
    ['unknown counterparty_type', { ...valid, counterparty_type: 'wallet' }],
    ['empty counterparty_id', { ...valid, counterparty_id: '' }],
    ['unknown rail', { ...valid, rail: 'paypal' }],
  ])('rejects invalid payload: %s', (_label, bad) => {
    expect(() => validateEconomicPayload(bad)).toThrow(EconomicValidationError);
  });

  it('rejects non-objects', () => {
    expect(() => validateEconomicPayload(null)).toThrow(EconomicValidationError);
    expect(() => validateEconomicPayload('nope')).toThrow(EconomicValidationError);
  });

  it('isEconomicPayload returns boolean without throwing', () => {
    expect(isEconomicPayload(valid)).toBe(true);
    expect(isEconomicPayload({ ...valid, amount: -1 })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Handshake lifecycle
// ---------------------------------------------------------------------------

describe('Handshake lifecycle', () => {
  const base: Handshake = {
    id: 'hs_1',
    request_id: 'req_1',
    required_amount: 1.5,
    status: 'pending',
    timestamp: 1714600000000,
  };

  it('createHandshake defaults to pending', () => {
    const hs = createHandshake({
      id: 'hs_2',
      request_id: 'req_2',
      required_amount: 2,
      timestamp: 1,
    });
    expect(hs.status).toBe('pending');
  });

  it('rejects malformed handshakes', () => {
    expect(() => validateHandshake({ ...base, id: '' })).toThrow(EconomicValidationError);
    expect(() => validateHandshake({ ...base, request_id: '' })).toThrow(EconomicValidationError);
    expect(() => validateHandshake({ ...base, required_amount: -1 })).toThrow(
      EconomicValidationError,
    );
    expect(() => validateHandshake({ ...base, status: 'cancelled' })).toThrow(
      EconomicValidationError,
    );
    expect(() => validateHandshake({ ...base, timestamp: 'now' })).toThrow(
      EconomicValidationError,
    );
    expect(() => validateHandshake(null)).toThrow(EconomicValidationError);
  });

  it('allows pending → paid', () => {
    const next = transitionHandshake(base, 'paid');
    expect(next.status).toBe('paid');
  });

  it('allows pending → failed', () => {
    const next = transitionHandshake(base, 'failed');
    expect(next.status).toBe('failed');
  });

  it('rejects paid → pending', () => {
    expect(() => assertHandshakeTransition('paid', 'pending')).toThrow(HandshakeStateError);
  });

  it('rejects failed → paid (terminal)', () => {
    expect(() => assertHandshakeTransition('failed', 'paid')).toThrow(HandshakeStateError);
  });

  it('rejects same-state transitions', () => {
    expect(() => assertHandshakeTransition('pending', 'pending')).toThrow(HandshakeStateError);
  });
});

// ---------------------------------------------------------------------------
// Resource node
// ---------------------------------------------------------------------------

describe('ResourceNode', () => {
  const valid: ResourceNode = {
    id: 'res_meta_camp_1',
    type: 'campaign',
    platform: 'meta',
    metadata: { objective: 'conversions' },
  };

  it('accepts every supported type', () => {
    for (const type of ['campaign', 'ad_account', 'bank_account', 'api', 'model'] as const) {
      expect(createResourceNode({ ...valid, type, id: `res_${type}` })).toMatchObject({ type });
    }
  });

  it('rejects unknown types', () => {
    expect(() =>
      validateResourceNode({ id: 'r1', type: 'database' } as unknown as ResourceNode),
    ).toThrow(EconomicValidationError);
  });

  it('rejects empty id and bad metadata', () => {
    expect(() => validateResourceNode({ ...valid, id: '' })).toThrow(EconomicValidationError);
    expect(() =>
      validateResourceNode({ ...valid, metadata: 'oops' } as unknown as ResourceNode),
    ).toThrow(EconomicValidationError);
    expect(() =>
      validateResourceNode({ ...valid, platform: '' }),
    ).toThrow(EconomicValidationError);
  });

  it('allows extensible metadata without schema change', () => {
    const r = createResourceNode({
      id: 'res_api_x402_demo',
      type: 'api',
      metadata: { endpoint: 'https://api.example.com/x402', priceCents: 50, tags: ['llm'] },
    });
    expect(r.metadata?.priceCents).toBe(50);
  });
});

// ---------------------------------------------------------------------------
// Relationship extensions
// ---------------------------------------------------------------------------

describe('RelationshipExtensions', () => {
  it('accepts an empty object (all optional)', () => {
    expect(validateRelationshipExtensions({})).toEqual({});
  });

  it('accepts a fully-populated extension', () => {
    const r: RelationshipExtensions = {
      flow_ref: { flow_id: 'flow_1', sequence: 0 },
      interaction_mode: 'A2A',
      economic_involved: true,
      outcome: { metric: 'revenue', value: 250.0 },
    };
    expect(validateRelationshipExtensions(r)).toEqual(r);
  });

  it('rejects non-integer sequence', () => {
    expect(() =>
      validateRelationshipExtensions({ flow_ref: { flow_id: 'f1', sequence: 1.5 } }),
    ).toThrow(EconomicValidationError);
  });

  it('rejects negative sequence', () => {
    expect(() =>
      validateRelationshipExtensions({ flow_ref: { flow_id: 'f1', sequence: -1 } }),
    ).toThrow(EconomicValidationError);
  });

  it('rejects unknown interaction_mode and metric', () => {
    expect(() => validateRelationshipExtensions({ interaction_mode: 'X2X' })).toThrow(
      EconomicValidationError,
    );
    expect(() =>
      validateRelationshipExtensions({ outcome: { metric: 'engagement', value: 1 } }),
    ).toThrow(EconomicValidationError);
  });

  it('rejects non-boolean economic_involved', () => {
    expect(() =>
      validateRelationshipExtensions({ economic_involved: 'yes' as unknown as boolean }),
    ).toThrow(EconomicValidationError);
  });
});

// ---------------------------------------------------------------------------
// Authorization
// ---------------------------------------------------------------------------

describe('Authorization', () => {
  it('accepts each source', () => {
    for (const source of ['human', 'org', 'policy'] as const) {
      expect(validateAuthorization({ source, scope: 'spend:max=100' })).toMatchObject({ source });
    }
  });

  it('accepts an optional limit', () => {
    expect(validateAuthorization({ source: 'human', scope: 'spend', limit: 0 }).limit).toBe(0);
  });

  it('rejects bad input', () => {
    expect(() => validateAuthorization({ source: 'bot', scope: 'x' })).toThrow(
      EconomicValidationError,
    );
    expect(() => validateAuthorization({ source: 'human', scope: '' })).toThrow(
      EconomicValidationError,
    );
    expect(() =>
      validateAuthorization({ source: 'human', scope: 's', limit: -1 }),
    ).toThrow(EconomicValidationError);
  });
});

// ---------------------------------------------------------------------------
// State aggregation
// ---------------------------------------------------------------------------

describe('aggregateEconomicState', () => {
  const a = (econ?: EconomicPayload, id = 'a'): EconomicActionLike => ({ id, economic: econ });

  it('returns {} when no actions carry economic blocks', () => {
    expect(aggregateEconomicState([a(), a()])).toEqual({});
  });

  it('sums spend and revenue separately for a single currency', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 10,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's1',
        rail: 'stripe',
      }),
      a({
        amount: 5,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's1',
        rail: 'stripe',
      }),
      a({
        amount: 50,
        currency: 'USD',
        direction: 'receive',
        counterparty_type: 'platform',
        counterparty_id: 'p1',
        rail: 'stripe',
      }),
    ];
    const state = aggregateEconomicState(actions);
    expect(state.currency).toBe('USD');
    expect(state.total_spend).toBe(15);
    expect(state.total_revenue).toBe(50);
    expect(state.byCurrency).toEqual({ USD: { total_spend: 15, total_revenue: 50 } });
  });

  it('keeps mixed-currency totals separate and omits flat scalars', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 10,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's1',
        rail: 'stripe',
      }),
      a({
        amount: 8,
        currency: 'EUR',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's2',
        rail: 'stripe',
      }),
      a({
        amount: 50,
        currency: 'EUR',
        direction: 'receive',
        counterparty_type: 'platform',
        counterparty_id: 'p1',
        rail: 'stripe',
      }),
    ];
    const state = aggregateEconomicState(actions);
    expect(state.currency).toBeUndefined();
    expect(state.total_spend).toBeUndefined();
    expect(state.total_revenue).toBeUndefined();
    expect(state.spend_rate).toBeUndefined();
    expect(state.unit_cost).toBeUndefined();
    expect(state.byCurrency).toEqual({
      USD: { total_spend: 10, total_revenue: 0 },
      EUR: { total_spend: 8, total_revenue: 50 },
    });
  });

  it('computes per-currency spend_rate and unit_cost in the byCurrency slice', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 60,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's1',
        rail: 'stripe',
      }),
      a({
        amount: 30,
        currency: 'EUR',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's2',
        rail: 'stripe',
      }),
    ];
    const state = aggregateEconomicState(actions, { windowMs: 60_000, units: 3 });
    expect(state.byCurrency?.['USD']).toEqual({
      total_spend: 60,
      total_revenue: 0,
      spend_rate: 1, // 60 / 60s
      unit_cost: 20, // 60 / 3
    });
    expect(state.byCurrency?.['EUR']).toEqual({
      total_spend: 30,
      total_revenue: 0,
      spend_rate: 0.5,
      unit_cost: 10,
    });
    // Flat scalars are absent on mixed-currency input.
    expect(state.spend_rate).toBeUndefined();
    expect(state.unit_cost).toBeUndefined();
  });

  it('computes spend_rate when windowMs is provided', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 60,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's',
        rail: 'stripe',
      }),
    ];
    const state = aggregateEconomicState(actions, { windowMs: 60_000 });
    expect(state.spend_rate).toBe(1); // 60 USD / 60 s = 1 USD/s
  });

  it('computes unit_cost when units > 0', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 100,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's',
        rail: 'stripe',
      }),
    ];
    expect(aggregateEconomicState(actions, { units: 4 }).unit_cost).toBe(25);
  });

  it('omits derived fields when inputs are not provided', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 100,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's',
        rail: 'stripe',
      }),
    ];
    const state = aggregateEconomicState(actions, { windowMs: 0, units: 0 });
    expect(state.spend_rate).toBeUndefined();
    expect(state.unit_cost).toBeUndefined();
  });

  it('handles zero-value transactions cleanly', () => {
    const actions: EconomicActionLike[] = [
      a({
        amount: 0,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 's',
        rail: 'stripe',
      }),
    ];
    const state = aggregateEconomicState(actions);
    expect(state.currency).toBe('USD');
    expect(state.total_spend).toBe(0);
    expect(state.total_revenue).toBe(0);
    expect(state.byCurrency).toEqual({ USD: { total_spend: 0, total_revenue: 0 } });
  });

  it('runs in O(n) — sanity check on 10k actions', () => {
    const actions: EconomicActionLike[] = Array.from({ length: 10_000 }, (_, i) => ({
      id: `a_${i}`,
      economic: {
        amount: 1,
        currency: 'USD',
        direction: i % 2 === 0 ? 'pay' : 'receive',
        counterparty_type: 'service',
        counterparty_id: 's',
        rail: 'internal',
      },
    }));
    const start = Date.now();
    const state = aggregateEconomicState(actions);
    const elapsed = Date.now() - start;
    expect(state.total_spend).toBe(5_000);
    expect(state.total_revenue).toBe(5_000);
    expect(elapsed).toBeLessThan(250);
  });
});

// ---------------------------------------------------------------------------
// Referential integrity
// ---------------------------------------------------------------------------

describe('referential integrity', () => {
  const handshakes: Handshake[] = [
    { id: 'hs_a', request_id: 'r_a', required_amount: 1, status: 'pending', timestamp: 1 },
  ];
  const actions: EconomicActionLike[] = [{ id: 'act_1' }, { id: 'act_2' }];

  it('passes for known references (array form)', () => {
    expect(() => assertHandshakeReference('hs_a', handshakes)).not.toThrow();
    expect(() => assertActionReference('act_1', actions)).not.toThrow();
  });

  it('passes for known references (map form)', () => {
    const hsMap = new Map(handshakes.map((h) => [h.id, h]));
    const actMap = new Map(actions.map((a) => [a.id as string, a]));
    expect(() => assertHandshakeReference('hs_a', hsMap)).not.toThrow();
    expect(() => assertActionReference('act_1', actMap)).not.toThrow();
  });

  it('throws RelationshipIntegrityError on unknown handshake id', () => {
    expect(() => assertHandshakeReference('hs_missing', handshakes)).toThrow(
      RelationshipIntegrityError,
    );
  });

  it('throws RelationshipIntegrityError on unknown action id', () => {
    expect(() => assertActionReference('act_missing', actions)).toThrow(
      RelationshipIntegrityError,
    );
  });
});

// ---------------------------------------------------------------------------
// Integration: full flows
// ---------------------------------------------------------------------------

describe('integration: full flows', () => {
  it('H2A authorized spend → A2A execution', () => {
    const auth = validateAuthorization({
      source: 'human',
      scope: 'spend:campaign=acme',
      limit: 200,
    });

    const h2aAction: EconomicActionLike = {
      id: 'act_h2a_1',
      authorization: auth,
    };

    const a2aAction: EconomicActionLike = {
      id: 'act_a2a_1',
      authorization: auth,
      economic: validateEconomicPayload({
        amount: 50,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'agent',
        counterparty_id: 'agent_buyer',
        rail: 'internal',
      }),
    };

    const rel = validateRelationshipExtensions({
      flow_ref: { flow_id: 'flow_h2a_a2a_1', sequence: 0 },
      interaction_mode: 'H2A',
      economic_involved: false,
    });
    const rel2 = validateRelationshipExtensions({
      flow_ref: { flow_id: 'flow_h2a_a2a_1', sequence: 1 },
      interaction_mode: 'A2A',
      economic_involved: true,
    });

    expect(rel.flow_ref?.flow_id).toBe(rel2.flow_ref?.flow_id);
    expect(a2aAction.economic?.amount).toBeLessThanOrEqual(auth.limit ?? Infinity);
    expect(h2aAction.authorization?.source).toBe('human');
  });

  it('A2A payment flow: handshake request → pay → resolve', () => {
    // Service agent emits a handshake request
    let hs = createHandshake({
      id: 'hs_x402_1',
      request_id: 'req_x402_1',
      required_amount: 0.05,
      timestamp: 1_700_000_000_000,
    });
    expect(hs.status).toBe('pending');

    // Buyer agent initiates payment Action that points at the handshake
    const payAction: EconomicActionLike = {
      id: 'act_pay_1',
      economic: {
        amount: 0.05,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'service',
        counterparty_id: 'svc_x402_1',
        rail: 'internal',
      },
    };
    assertHandshakeReference(hs.id, [hs]);

    // Handshake resolves, pointing to the payment action
    hs = transitionHandshake(hs, 'paid');
    assertActionReference(payAction.id as string, [payAction]);

    expect(hs.status).toBe('paid');
  });

  it('outcome linkage: spend → revenue', () => {
    const spend: EconomicActionLike = {
      id: 'act_spend_1',
      economic: {
        amount: 100,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'platform',
        counterparty_id: 'meta_ads',
        rail: 'stripe',
      },
    };
    const revenue: EconomicActionLike = {
      id: 'act_rev_1',
      economic: {
        amount: 350,
        currency: 'USD',
        direction: 'receive',
        counterparty_type: 'platform',
        counterparty_id: 'shopify',
        rail: 'stripe',
      },
    };

    const causal = validateRelationshipExtensions({
      flow_ref: { flow_id: 'campaign_acme_2026Q1', sequence: 1 },
      interaction_mode: 'A2A',
      outcome: { metric: 'revenue', value: 350 },
    });

    const state = aggregateEconomicState([spend, revenue], { units: 7 });
    expect(state.total_spend).toBe(100);
    expect(state.total_revenue).toBe(350);
    expect(state.unit_cost).toBeCloseTo(14.285714, 5);
    expect(causal.outcome?.metric).toBe('revenue');
  });

  it('handles failed payment gracefully', () => {
    let hs = createHandshake({
      id: 'hs_fail',
      request_id: 'req_fail',
      required_amount: 1,
      timestamp: 1,
    });
    hs = transitionHandshake(hs, 'failed');
    expect(hs.status).toBe('failed');
    // No further transitions allowed
    expect(() => transitionHandshake(hs, 'paid')).toThrow(HandshakeStateError);
  });

  it('handles partial flows: handshake without resolving action', () => {
    const hs = createHandshake({
      id: 'hs_partial',
      request_id: 'req_partial',
      required_amount: 1,
      timestamp: 1,
    });
    expect(() => assertActionReference('act_missing', [])).toThrow(RelationshipIntegrityError);
    expect(hs.status).toBe('pending');
  });

  it('handles missing counterparty by rejecting at validation time', () => {
    expect(() =>
      validateEconomicPayload({
        amount: 1,
        currency: 'USD',
        direction: 'pay',
        counterparty_type: 'agent',
        counterparty_id: '',
        rail: 'internal',
      }),
    ).toThrow(EconomicValidationError);
  });
});
