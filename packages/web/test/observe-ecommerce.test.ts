/**
 * PR2 — canonical ecommerce emission, registry-derived consent map, and the
 * observe() canonical-type guard. Module/queue level (no DOM), matching the
 * repo's existing test philosophy.
 */
import { describe, expect, it, vi } from 'vitest';

import { EcommerceModule } from '../src/modules/ecommerce';
import {
  EVENT_CONSENT_PURPOSE as WEB_MAP,
  CANONICAL_EVENT_TYPES,
  isCanonicalEventType,
} from '../src/core/generated-consent-map';
import { EVENT_CONSENT_PURPOSE as SHARED_MAP } from '../../shared/events';

// ---------------------------------------------------------------------------
// Ecommerce helpers emit CANONICAL top-level types (not legacy names)
// ---------------------------------------------------------------------------
describe('EcommerceModule — canonical emission', () => {
  function moduleWithSpy() {
    const onObserve = vi.fn();
    return { mod: new EcommerceModule({ onObserve }), onObserve };
  }

  it('add-to-cart emits cart_item_added (not product_added)', () => {
    const { mod, onObserve } = moduleWithSpy();
    mod.trackAddToCart({ sku: 'A1' });
    expect(onObserve).toHaveBeenCalledWith('cart_item_added', { sku: 'A1' });
  });

  it('remove-from-cart emits cart_item_removed (not product_removed)', () => {
    const { mod, onObserve } = moduleWithSpy();
    mod.trackRemoveFromCart({ sku: 'A1' });
    expect(onObserve).toHaveBeenCalledWith('cart_item_removed', { sku: 'A1' });
  });

  it('product view / checkout / purchase emit canonical types', () => {
    const { mod, onObserve } = moduleWithSpy();
    mod.trackProductView({ sku: 'A1' });
    mod.trackCheckout([{ sku: 'A1' }], 2);
    mod.trackPurchase({ orderId: 'O1' });
    expect(onObserve).toHaveBeenNthCalledWith(1, 'product_viewed', { sku: 'A1' });
    expect(onObserve).toHaveBeenNthCalledWith(2, 'checkout_started', { items: [{ sku: 'A1' }], step: 2 });
    expect(onObserve).toHaveBeenNthCalledWith(3, 'order_completed', { orderId: 'O1' });
  });

  it('legacy productAdded/productRemoved aliases emit CANONICAL payloads', () => {
    const { mod, onObserve } = moduleWithSpy();
    mod.productAdded({ sku: 'A1' });
    mod.productRemoved({ sku: 'A1' });
    expect(onObserve).toHaveBeenNthCalledWith(1, 'cart_item_added', { sku: 'A1' });
    expect(onObserve).toHaveBeenNthCalledWith(2, 'cart_item_removed', { sku: 'A1' });
    // The retired legacy names must never reach the wire.
    for (const call of onObserve.mock.calls) {
      expect(call[0]).not.toBe('product_added');
      expect(call[0]).not.toBe('product_removed');
    }
  });
});

// ---------------------------------------------------------------------------
// The web consent map is registry-derived and in lockstep with shared
// ---------------------------------------------------------------------------
describe('generated-consent-map — registry-derived, no drift', () => {
  it('is byte-for-byte consistent with the shared EVENT_CONSENT_PURPOSE', () => {
    // Every canonical event type maps to the same primary purpose in both.
    for (const [type, purpose] of Object.entries(WEB_MAP)) {
      expect(SHARED_MAP[type as keyof typeof SHARED_MAP]).toBe(purpose);
    }
    expect(Object.keys(WEB_MAP).length).toBe(Object.keys(SHARED_MAP).length);
  });

  it('canonical ecommerce types are commerce-gated', () => {
    expect(WEB_MAP['cart_item_added']).toBe('commerce');
    expect(WEB_MAP['cart_item_removed']).toBe('commerce');
    expect(WEB_MAP['order_completed']).toBe('commerce');
  });

  it('retired legacy names are NOT canonical event types', () => {
    expect(isCanonicalEventType('product_added')).toBe(false);
    expect(isCanonicalEventType('product_removed')).toBe(false);
    expect(isCanonicalEventType('definitely_not_a_real_event')).toBe(false);
    expect(CANONICAL_EVENT_TYPES.has('cart_item_added')).toBe(true);
  });
});
