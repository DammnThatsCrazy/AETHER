// @vitest-environment jsdom
/**
 * SDK integration — commerce detection wired through AetherSDK.init() and the
 * canonical observe() gate. Raw SDKCommerceSignals must surface as canonical
 * registry events (product_viewed / cart_updated / checkout_started /
 * order_completed) with schema-versioned sdk_signal metadata, and never as a
 * fabricated runtime `commerce.*` type.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import aether from '../src/index';
import { SDK_SIGNAL_SCHEMA_VERSION } from '@aether/shared/commerce-bridge';

function installFetchCapture() {
  const sent: any[] = [];
  const fetchMock = vi.fn(async (_url: string, init?: any) => {
    if (init?.body) {
      try {
        const parsed = JSON.parse(init.body);
        if (Array.isArray(parsed.batch)) sent.push(...parsed.batch);
      } catch { /* ignore non-batch calls (manifest, heartbeat) */ }
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ accepted: 1, duplicates: 0, rejected: 0, events: [] }),
      text: async () => '{}',
    } as any;
  });
  (globalThis as any).fetch = fetchMock;
  return sent;
}

const BASE_CONFIG = {
  apiKey: 'test-key',
  endpoint: 'https://api.test',
  flushInterval: 60_000,
  modules: { autoDiscovery: false, performance: false, ecommerce: true, commerceDetection: true },
};

describe('commerce detection → observe() canonical gate (jsdom)', () => {
  let sent: any[];

  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '';
    window.history.replaceState({}, '', '/');
    document.body.addEventListener('click', (e) => e.preventDefault());
    sent = installFetchCapture();
  });

  afterEach(() => {
    try { aether.destroy?.(); } catch { /* ignore */ }
    vi.restoreAllMocks();
  });

  async function flush() {
    await (aether as any).flush?.();
  }

  it('bridges a product-view click to canonical product_viewed', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce', 'analytics']);

    document.body.innerHTML =
      '<a href="/products/abc-holder" data-aether-track>Holder</a>';
    document.querySelector('a')!.dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );

    await flush();
    const evt = sent.find((e) => e.type === 'product_viewed');
    expect(evt).toBeTruthy();
    expect(evt.properties.sdk_signal).toBeDefined();
    expect(evt.properties.sdk_signal.schema_version).toBe(SDK_SIGNAL_SCHEMA_VERSION);
    expect(evt.properties.sdk_signal.signal_type).toBe('product_view');
    // The SDK plane is a projection — it never self-confirms; verdicts come
    // exclusively from the server-side confirm_interaction mirror.
    expect(evt.properties.confirmation).toEqual({ confirmed: false, state: 'not_found' });
    expect(evt.context.surface).toBe('web');
  });

  it('bridges an order-confirmation page to canonical order_completed', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce', 'analytics']);
    window.history.replaceState({}, '', '/order/confirmation');
    document.body.innerHTML = '<div data-order-id="ORD-77"></div>';
    // A direct replaceState is not a tracked SPA route, so re-run detection
    // the same way the SDK does on route completion.
    (aether as any).commerceDetection?.detectOnLoad();
    await flush();

    const evt = sent.find((e) => e.type === 'order_completed');
    expect(evt).toBeTruthy();
    expect(evt.properties.order_id).toBe('ORD-77');
    expect(evt.properties.sdk_signal.signal_type).toBe('order_confirmed');
    expect(evt.properties.sdk_signal.source_url).toContain('/order/confirmation');
    expect(evt.properties.confirmation).toEqual({ confirmed: false, state: 'not_found' });
  });

  it('never emits a fabricated runtime commerce.* event type', async () => {
    aether.init({ ...BASE_CONFIG });
    aether.consent.grant(['commerce', 'analytics']);

    document.body.innerHTML = '<button data-add-to-cart data-product-id="P-1">Add</button>';
    document.querySelector('button')!.dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );

    await flush();
    // The SDK emits the canonical registry type, never a `commerce.*` type.
    expect(sent.find((e) => e.type === 'commerce.cart_updated')).toBeUndefined();
    expect(sent.find((e) => e.type === 'commerce.order_confirmed')).toBeUndefined();
    const evt = sent.find((e) => e.type === 'cart_updated');
    expect(evt).toBeTruthy();
  });

  it('respects the commerceDetection module flag (off → no detection)', async () => {
    aether.init({
      ...BASE_CONFIG,
      modules: { autoDiscovery: false, performance: false, ecommerce: true, commerceDetection: false },
    });
    aether.consent.grant(['commerce', 'analytics']);

    document.body.innerHTML = '<button data-add-to-cart data-product-id="P-1">Add</button>';
    document.querySelector('button')!.dispatchEvent(
      new MouseEvent('click', { bubbles: true, cancelable: true }),
    );

    await flush();
    expect(sent.find((e) => e.type === 'cart_updated')).toBeUndefined();
  });
});
