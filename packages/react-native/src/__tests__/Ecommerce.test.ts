import { describe, it, expect, vi } from 'vitest';
import { EVENT_CONSENT_PURPOSE } from '../../../shared/events';

const nativeEcom = {
  initialize: vi.fn(),
  trackProductView: vi.fn(),
  trackAddToCart: vi.fn(),
  trackCheckout: vi.fn(),
  trackPurchase: vi.fn(),
};

vi.mock('react-native', () => ({
  NativeModules: { AetherEcommerce: nativeEcom },
  NativeEventEmitter: class {},
  Platform: { OS: 'ios' },
}));

describe('RNEcommerce (RN thin bridge) — module loads', () => {
  it('module can be imported without throwing when NativeModules are present', async () => {
    const mod = await import('../modules/Ecommerce');
    expect(mod).toBeDefined();
  });

  it('module can be imported when the native side is missing (null-safe)', async () => {
    vi.resetModules();
    vi.doMock('react-native', () => ({
      NativeModules: {},
      NativeEventEmitter: class {},
      Platform: { OS: 'android' },
    }));
    const mod = await import('../modules/Ecommerce');
    expect(mod).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Canonical cart events — the RN bridge delegates add/remove-to-cart to the
// native SDKs (trackAddToCart / trackRemoveFromCart), which emit the CANONICAL
// event types. The legacy `product_added` / `product_removed` names must never
// appear on the wire, so they are absent from the shared consent registry.
// ---------------------------------------------------------------------------
describe('Ecommerce — canonical cart event names', () => {
  it('registers canonical cart_item_added / cart_item_removed', () => {
    expect('cart_item_added' in EVENT_CONSENT_PURPOSE).toBe(true);
    expect('cart_item_removed' in EVENT_CONSENT_PURPOSE).toBe(true);
  });

  it('does not register legacy product_added / product_removed', () => {
    expect('product_added' in EVENT_CONSENT_PURPOSE).toBe(false);
    expect('product_removed' in EVENT_CONSENT_PURPOSE).toBe(false);
  });
});
