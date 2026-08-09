import { describe, expect, it } from 'vitest';
import {
  SDK_SIGNAL_SCHEMA_VERSION,
  CONFIRMED_SIGNAL_IDS_KEY,
  canonicalEventToSdkSignal,
  confirmInteraction,
  decimalSumToCents,
  decimalToCents,
  isCanonicalCommerceEvent,
  multiplyCents,
  numberToCents,
  sdkSignalToCanonicalEvent,
  subtractCents,
  sumCents,
  toCents,
  validateOrderTotals,
  type AetherEvent,
  type OrderSnapshot,
  type OrderTotalsDetail,
  type SDKCommerceSignal,
} from './commerce-bridge';

const makeSignal = (overrides: Partial<SDKCommerceSignal> = {}): SDKCommerceSignal => ({
  signal_id: 'sig-1',
  signal_type: 'order_confirmed',
  occurred_at: '2026-08-08T12:00:00.000Z',
  source_url: 'https://shop.example/order/confirmation',
  lineage: { source_record_id: 'ORD-1001' },
  payload: { order_id: 'ORD-1001' },
  ...overrides,
});

const makeCanonical = (overrides: Partial<AetherEvent> = {}): AetherEvent => ({
  id: 'evt-1',
  event_type: 'commerce.order.confirmed',
  event_family: 'commerce',
  provider: 'shopify',
  provider_identity: 'shopify.order.confirmed',
  source_record_id: 'ORD-1001',
  occurred_at: '2026-08-08T12:00:00.000Z',
  data: { order_id: 'ORD-1001' },
  context: {},
  ...overrides,
});

const makeDetail = (overrides: Partial<OrderTotalsDetail> = {}): OrderTotalsDetail => ({
  order_id: 'ORD-1001',
  signal_type: 'order_confirmed',
  occurred_at: '2026-08-08T12:00:00.000Z',
  currency: 'USD',
  subtotal: '59.97',
  tax: '5.00',
  shipping: '4.99',
  discount: '10.00',
  total: '59.96',
  provider: 'stripe',
  items: [
    {
      line_id: 'L1',
      product_id: 'P-1',
      name: 'Widget',
      quantity: 3,
      unit_price: '19.99',
      line_total: '59.97',
      currency: 'USD',
    },
  ],
  ...overrides,
});

describe('SDK_SIGNAL_SCHEMA_VERSION', () => {
  it('is the versioned schema constant "1"', () => {
    expect(SDK_SIGNAL_SCHEMA_VERSION).toBe('1');
  });
});

describe('SDKCommerceSignal shape', () => {
  it('constructs the exact S2 contract shape', () => {
    const signal: SDKCommerceSignal = {
      signal_id: 'sig-1',
      signal_type: 'product_view',
      occurred_at: '2026-08-08T12:00:00.000Z',
      source_url: 'https://shop.example/p/abc',
      lineage: { source_record_id: 'P-1' },
      payload: { product_id: 'P-1', price: '19.99' },
    };
    expect(signal.signal_type).toBe('product_view');
    expect(signal.lineage.source_record_id).toBe('P-1');
  });
});

describe('signal ↔ canonical event mapping (DECISION 1 vocabulary)', () => {
  it('maps BARE SDK signal types to DOTTED canonical event types', () => {
    expect(sdkSignalToCanonicalEvent('product_view')).toBe('commerce.product.viewed');
    expect(sdkSignalToCanonicalEvent('cart_updated')).toBe('commerce.cart.updated');
    expect(sdkSignalToCanonicalEvent('checkout_started')).toBe('commerce.checkout.started');
    expect(sdkSignalToCanonicalEvent('order_confirmed')).toBe('commerce.order.confirmed');
  });

  it('is a bijection over the 4 valid pairs', () => {
    const pairs: Array<[string, string]> = [
      ['commerce.product.viewed', 'product_view'],
      ['commerce.cart.updated', 'cart_updated'],
      ['commerce.checkout.started', 'checkout_started'],
      ['commerce.order.confirmed', 'order_confirmed'],
    ];
    for (const [canonical, sdk] of pairs) {
      expect(canonicalEventToSdkSignal(canonical)).toBe(sdk);
      expect(sdkSignalToCanonicalEvent(sdk as SDKCommerceSignal['signal_type'])).toBe(canonical);
    }
  });

  it('does NOT map commerce.order.created to order_confirmed (false-positive rule)', () => {
    expect(canonicalEventToSdkSignal('commerce.order.created')).toBeNull();
    expect(isCanonicalCommerceEvent('commerce.order.created')).toBe(false);
  });

  it('treats the registry underscore names as NOT canonical (WS4-deferred)', () => {
    expect(isCanonicalCommerceEvent('product_viewed')).toBe(false);
    expect(isCanonicalCommerceEvent('order_completed')).toBe(false);
    expect(canonicalEventToSdkSignal('product_viewed')).toBeNull();
    expect(canonicalEventToSdkSignal('order_completed')).toBeNull();
  });

  it('accepts the 4 canonical dotted event types', () => {
    for (const type of [
      'commerce.product.viewed',
      'commerce.cart.updated',
      'commerce.checkout.started',
      'commerce.order.confirmed',
    ]) {
      expect(isCanonicalCommerceEvent(type)).toBe(true);
    }
    expect(isCanonicalCommerceEvent('navigation_intent')).toBe(false);
  });
});

describe('exact money — HALF-UP quantization parity with Python', () => {
  it('parses decimal strings to integer cents exactly', () => {
    expect(decimalToCents('19.99')).toBe('1999');
    expect(decimalToCents('10')).toBe('1000');
    expect(decimalToCents('0.01')).toBe('1');
    expect(decimalToCents('-2.50')).toBe('-250');
    expect(decimalToCents('59.97')).toBe('5997');
  });

  it('accepts sub-cent strings with ROUND_HALF_UP like Python Decimal', () => {
    expect(decimalToCents('0.005')).toBe('1');
    expect(decimalToCents('-0.005')).toBe('-1');
    expect(decimalToCents('19.999')).toBe('2000');
    expect(decimalToCents('19.995')).toBe('2000');
    expect(decimalToCents('19.994')).toBe('1999');
    expect(decimalToCents('1.005')).toBe('101');
  });

  it('expands scientific notation to exact cents', () => {
    expect(decimalToCents('1.5e2')).toBe('15000');
    expect(decimalToCents('0.1e2')).toBe('1000');
    expect(decimalToCents('1e-3')).toBe('0');
  });

  it('converts numbers through the same HALF-UP path (no toFixed artifacts)', () => {
    // 0.1 + 0.2 === 0.30000000000000004 → exactly 30 cents.
    expect(numberToCents(0.1 + 0.2)).toBe('30');
    expect(numberToCents(19.999)).toBe('2000');
    // 1.005 must round HALF-UP to 101¢ — toFixed(2) would give 100¢.
    expect(numberToCents(1.005)).toBe('101');
  });

  it('a number and its decimal-string form yield the same result', () => {
    expect(toCents(19.999)).toBe(toCents('19.999'));
    expect(toCents(1.005)).toBe(toCents('1.005'));
    expect(toCents(0.1 + 0.2)).toBe('30');
    expect(numberToCents(19.999)).toBe('2000');
  });

  it('sums cents with BigInt arithmetic (no drift)', () => {
    expect(sumCents(['1999', '1999', '1999'])).toBe('5997');
    expect(decimalSumToCents(['19.99', '19.99', '19.99'])).toBe('5997');
    expect(sumCents(['1', '2', '3'])).toBe('6');
  });

  it('subtracts and multiplies exactly', () => {
    expect(subtractCents('5997', '499')).toBe('5498');
    expect(multiplyCents('1999', 3)).toBe('5997');
  });

  it('rejects malformed money strings and non-finite numbers', () => {
    expect(() => decimalToCents('abc')).toThrow();
    expect(() => decimalToCents('')).toThrow();
    expect(() => decimalToCents('--1')).toThrow();
    expect(() => toCents(Number.NaN)).toThrow();
    expect(() => toCents(Number.POSITIVE_INFINITY)).toThrow();
  });
});

describe('OrderSnapshot — canonical Python shape', () => {
  it('is the exact canonical projection {order_id, status, currency, total:{amount,currency}, created_at, updated_at, account_id}', () => {
    const snapshot: OrderSnapshot = {
      order_id: 'ORD-1001',
      status: 'paid',
      currency: 'USD',
      total: { amount: '59.96', currency: 'USD' },
      created_at: '2026-08-08T12:00:00.000Z',
      updated_at: null,
      account_id: 'acct-1',
    };
    expect(snapshot).toEqual({
      order_id: 'ORD-1001',
      status: 'paid',
      currency: 'USD',
      total: { amount: '59.96', currency: 'USD' },
      created_at: '2026-08-08T12:00:00.000Z',
      updated_at: null,
      account_id: 'acct-1',
    });
    // The canonical payload carries only `total` — never the flat client view.
    expect(snapshot).not.toHaveProperty('subtotal');
    expect(snapshot).not.toHaveProperty('items');
    expect(snapshot).not.toHaveProperty('signal_type');
  });
});

describe('confirmInteraction — exact mirror of Python confirm_interaction', () => {
  it('is not_found when canonical is null (confirmed=false)', () => {
    const result = confirmInteraction(makeSignal(), null);
    expect(result.confirmation_state).toBe('not_found');
    expect(result.confirmed).toBe(false);
    expect(result.sdk_event_type).toBe('order_confirmed');
    expect(result.canonical_event_type).toBe('');
    expect(result.provider).toBe('');
    expect(result.payload).toEqual({ order_id: 'ORD-1001' });
  });

  it('is unconfirmed on a lineage mismatch (never auto-confirms)', () => {
    const signal = makeSignal({ lineage: { source_record_id: 'OTHER' } });
    const result = confirmInteraction(signal, makeCanonical());
    expect(result.confirmation_state).toBe('unconfirmed');
    expect(result.confirmed).toBe(false);
    expect(result.canonical_event_type).toBe('commerce.order.confirmed');
  });

  it('is unconfirmed when the signal carries no source_record_id', () => {
    const signal = makeSignal({ lineage: { source_record_id: null } });
    const result = confirmInteraction(signal, makeCanonical());
    expect(result.confirmation_state).toBe('unconfirmed');
    expect(result.confirmed).toBe(false);
  });

  it('is replay when the signal_id is already in the confirmed ledger', () => {
    const canonical = makeCanonical({
      context: { [CONFIRMED_SIGNAL_IDS_KEY]: ['sig-1'] },
    });
    const result = confirmInteraction(makeSignal(), canonical);
    expect(result.confirmation_state).toBe('replay');
    expect(result.confirmed).toBe(false);
  });

  it('is matched (confirmed=true) on a fresh lineage match', () => {
    const canonical = makeCanonical({
      context: { [CONFIRMED_SIGNAL_IDS_KEY]: ['sig-other'] },
    });
    const result = confirmInteraction(makeSignal(), canonical);
    expect(result.confirmation_state).toBe('matched');
    expect(result.confirmed).toBe(true);
  });

  it('fails CLOSED when the replay ledger is a non-list (never matched)', () => {
    const canonical = makeCanonical({
      context: { [CONFIRMED_SIGNAL_IDS_KEY]: '["sig-1"]' },
    });
    const result = confirmInteraction(makeSignal(), canonical);
    expect(result.confirmation_state).toBe('unconfirmed');
    expect(result.confirmed).toBe(false);
  });
});

describe('validateOrderTotals — exact cents on the flat client view', () => {
  it('accepts a balanced detail (subtotal+tax+shipping-discount === total)', () => {
    expect(validateOrderTotals(makeDetail())).toEqual([]);
  });

  it('detects a total mismatch without silently correcting it', () => {
    const issues = validateOrderTotals(makeDetail({ total: '1.00' }));
    expect(issues.length).toBe(1);
    expect(issues[0]).toContain('total mismatch');
  });

  it('detects a line-total mismatch', () => {
    const issues = validateOrderTotals(
      makeDetail({
        items: [
          {
            line_id: 'L1',
            product_id: 'P-1',
            name: 'Widget',
            quantity: 3,
            unit_price: '19.99',
            line_total: '20.00', // 3 × 19.99 = 59.97, not 20.00
            currency: 'USD',
          },
        ],
      }),
    );
    expect(issues.some((i) => i.includes('line L1'))).toBe(true);
  });

  it('surfaces a negative discount as a sign-convention violation, not a false total mismatch', () => {
    const issues = validateOrderTotals(makeDetail({ discount: '-10.00' }));
    expect(issues.length).toBe(1);
    expect(issues[0]).toContain('discount must be a non-negative magnitude');
    expect(issues[0]).not.toContain('total mismatch');
  });

  it('handles fractional-unit arithmetic exactly', () => {
    const issues = validateOrderTotals(
      makeDetail({
        subtotal: '0.30',
        tax: '0',
        shipping: '0',
        discount: '0',
        total: '0.30',
        items: [
          {
            line_id: 'L1',
            product_id: 'P-1',
            name: 'item',
            quantity: 3,
            unit_price: '0.10',
            line_total: '0.30',
            currency: 'USD',
          },
        ],
      }),
    );
    expect(issues).toEqual([]);
  });
});
