// =============================================================================
// Web bridge tests — envelope + payload projection parity, pass-through
// behavior, string-amount payloads, and the "provider is metadata, never a
// mapping key" invariant. Mirrors Python `envelope_bridge` / `payload_bridge`
// (DECISION 1): both bridges are projections — `confirmed=false`,
// `confirmation_state="not_found"` always.
// =============================================================================

import { describe, expect, it } from 'vitest';

import { envelopeBridge } from '../src/bridges/envelope-bridge';
import { payloadBridge } from '../src/bridges/payload-bridge';
import {
  SDK_SIGNAL_SCHEMA_VERSION,
  type AetherEvent,
  type OrderSnapshot,
} from '@aether/shared/commerce-bridge';

function makeEvent(overrides: Partial<AetherEvent> = {}): AetherEvent {
  return {
    id: 'evt-1',
    event_type: 'commerce.order.confirmed',
    event_family: 'commerce',
    provider: 'shopify',
    provider_identity: 'shopify.order.confirmed',
    source_record_id: 'ORD-1001',
    occurred_at: '2026-08-08T12:00:00.000Z',
    data: {
      order_id: 'ORD-1001',
      total: '59.96',
      currency: 'USD',
    },
    context: {},
    ...overrides,
  };
}

function makeSnapshot(overrides: Partial<OrderSnapshot> = {}): OrderSnapshot {
  return {
    order_id: 'ORD-1001',
    status: 'paid',
    currency: 'USD',
    total: { amount: '59.96', currency: 'USD' },
    created_at: '2026-08-08T12:00:00.000Z',
    updated_at: null,
    account_id: 'acct-1',
    ...overrides,
  };
}

describe('envelopeBridge — canonical envelope → BridgeResult', () => {
  it('projects each of the 4 canonical dotted event types to its BARE SDK signal', () => {
    const cases: Array<[string, string]> = [
      ['commerce.product.viewed', 'product_view'],
      ['commerce.cart.updated', 'cart_updated'],
      ['commerce.checkout.started', 'checkout_started'],
      ['commerce.order.confirmed', 'order_confirmed'],
    ];
    for (const [canonical, sdk] of cases) {
      const result = envelopeBridge(makeEvent({ event_type: canonical }));
      expect(result.sdk_event_type).toBe(sdk);
      expect(result.canonical_event_type).toBe(canonical);
    }
  });

  it('is a projection: always confirmed=false and confirmation_state=not_found', () => {
    const result = envelopeBridge(makeEvent());
    expect(result.confirmed).toBe(false);
    expect(result.confirmation_state).toBe('not_found');
  });

  it('passes UNMAPPED canonical types through as their own sdk_event_type (no throw)', () => {
    const result = envelopeBridge(makeEvent({ event_type: 'navigation_intent' }));
    expect(result.sdk_event_type).toBe('navigation_intent');
    expect(result.canonical_event_type).toBe('navigation_intent');
    expect(result.confirmed).toBe(false);
    expect(result.confirmation_state).toBe('not_found');
  });

  it('reads event.event_type + event.data (NOT type/properties)', () => {
    const result = envelopeBridge(
      makeEvent({
        event_type: 'commerce.cart.updated',
        data: { cart_id: 'C-1', line_count: 2 },
      }),
    );
    expect(result.sdk_event_type).toBe('cart_updated');
    expect(result.payload).toEqual({ cart_id: 'C-1', line_count: 2 });
  });

  it('never invents a payload field — data is copied through verbatim', () => {
    const result = envelopeBridge(
      makeEvent({ event_type: 'commerce.order.confirmed', data: { order_id: 'O-1' } }),
    );
    expect(result.payload).toEqual({ order_id: 'O-1' });
    expect(result.payload.amount_cents).toBeUndefined();
    expect(result.payload.total_cents).toBeUndefined();
  });

  it('carries provider through as metadata only — never as a mapping key', () => {
    const result = envelopeBridge(makeEvent({ provider: 'stripe' }));
    expect(result.provider).toBe('stripe');
    // provider is NOT injected into the payload.
    expect(result.payload.provider).toBeUndefined();
    expect(result.sdk_event_type).toBe('order_confirmed');
    expect(result.canonical_event_type).toBe('commerce.order.confirmed');
  });
});

describe('payloadBridge — canonical OrderSnapshot → BridgeResult', () => {
  it('emits the canonical OrderSnapshot payload with STRING amounts', () => {
    const result = payloadBridge(makeSnapshot());
    expect(result.sdk_event_type).toBe('order_confirmed');
    expect(result.canonical_event_type).toBe('commerce.order.confirmed');
    expect(result.payload).toEqual({
      order_id: 'ORD-1001',
      status: 'paid',
      currency: 'USD',
      total: { amount: '59.96', currency: 'USD' },
      created_at: '2026-08-08T12:00:00.000Z',
      updated_at: null,
      account_id: 'acct-1',
    });
  });

  it('does NOT crash on the canonical wire shape (no flat-field access)', () => {
    // A canonical snapshot has no subtotal/tax/shipping/items — payloadBridge
    // must never reach for them (E-2 MoneyParseError foot-gun regression).
    const result = payloadBridge(makeSnapshot());
    expect(result.payload.total).toEqual({ amount: '59.96', currency: 'USD' });
    expect(result.payload).not.toHaveProperty('subtotal');
    expect(result.payload).not.toHaveProperty('items');
  });

  it('is a projection: always confirmed=false and confirmation_state=not_found', () => {
    const result = payloadBridge(makeSnapshot());
    expect(result.confirmed).toBe(false);
    expect(result.confirmation_state).toBe('not_found');
  });

  it('carries no provider lineage (empty metadata, never a payload key)', () => {
    const result = payloadBridge(makeSnapshot());
    expect(result.provider).toBe('');
    expect(result.payload.provider).toBeUndefined();
  });

  it('preserves updated_at null and string amounts exactly', () => {
    const result = payloadBridge(
      makeSnapshot({ updated_at: '2026-08-08T12:05:00.000Z' }),
    );
    expect(result.payload.updated_at).toBe('2026-08-08T12:05:00.000Z');
    expect(result.payload.total).toEqual({ amount: '59.96', currency: 'USD' });
  });
});

describe('bridge contract invariants', () => {
  it('the schema version constant is exported and pinned', () => {
    expect(SDK_SIGNAL_SCHEMA_VERSION).toBe('1');
  });

  it('provider is never consulted to pick the mapping (mapping is type/event_type keyed)', () => {
    // Same canonical event_type, wildly different providers → identical mapping.
    const a = envelopeBridge(makeEvent({ provider: 'stripe' }));
    const b = envelopeBridge(makeEvent({ provider: 'paypal' }));
    expect(a.sdk_event_type).toBe(b.sdk_event_type);
    expect(a.canonical_event_type).toBe(b.canonical_event_type);
  });
});
