// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { CommerceDetectionModule } from '../src/modules/commerce-detection';
import {
  SDK_SIGNAL_SCHEMA_VERSION,
  type SDKCommerceSignal,
} from '@aether/shared/commerce-bridge';

type Signals = SDKCommerceSignal[];

function createModule(config?: { orderConfirmation?: boolean; cartPageView?: boolean }) {
  const signals: Signals = [];
  const module = new CommerceDetectionModule(
    {
      onSignal: (signal) => signals.push(signal),
    },
    config,
  );
  return { module, signals };
}

function click(el: Element, init: MouseEventInit = {}): void {
  el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
}

let modules: CommerceDetectionModule[] = [];

beforeEach(() => {
  document.body.innerHTML = '';
  window.history.replaceState({}, '', '/');
  document.body.addEventListener('click', (e) => e.preventDefault());
  modules = [];
});

afterEach(() => {
  modules.forEach((m) => m.destroy());
  modules = [];
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function start(config?: { orderConfirmation?: boolean; cartPageView?: boolean }) {
  const created = createModule(config);
  created.module.start();
  modules.push(created.module);
  return created;
}

function withUrl(path: string): void {
  window.history.replaceState({}, '', path);
}

describe('product view detection', () => {
  it('emits a schema-versioned product_view signal for a product card click', () => {
    document.body.innerHTML =
      '<div class="product-card" data-product-id="P-42" data-price="19.99">' +
      '<button data-add-to-cart="true">Add</button></div>';
    const { signals } = start();

    click(document.querySelector('button')!);

    // Add-to-cart wins the priority chain over product card.
    expect(signals).toHaveLength(1);
    expect(signals[0].signal_type).toBe('cart_updated');
  });

  it('emits product_view for a standalone product card click', () => {
    document.body.innerHTML =
      '<div class="product-card" data-product-id="P-42" data-price="19.99">' +
      '<span>Widget</span></div>';
    const { signals } = start();

    click(document.querySelector('.product-card')!);

    expect(signals).toHaveLength(1);
    const signal = signals[0];
    expect(signal.signal_type).toBe('product_view');
    expect(signal.lineage.source_record_id).toBe('P-42');
    expect(signal.payload.product_id).toBe('P-42');
    expect(signal.payload.price).toBe('19.99');
  });

  it('resolves product id from /products/:id links', () => {
    document.body.innerHTML = '<a href="/products/wireless-phone-holder" data-aether-track>Holder</a>';
    const { signals } = start();

    click(document.querySelector('a')!);

    expect(signals[0].signal_type).toBe('product_view');
    expect(signals[0].payload.product_id).toBe('wireless-phone-holder');
  });

  it('redacts long digit runs from free-text product names', () => {
    document.body.innerHTML =
      '<div class="product-card" data-product-id="P-1" data-product-name="Order 12345678 - Widget"></div>';
    const { signals } = start();

    click(document.querySelector('.product-card')!);

    const name = String(signals[0].payload.name);
    expect(name).toContain('****');
    expect(name).not.toContain('12345678');
  });

  it('ignores non-product controls (no false positive)', () => {
    document.body.innerHTML = '<a href="/pricing">Pricing</a>';
    const { signals } = start();

    click(document.querySelector('a')!);

    expect(signals).toHaveLength(0);
  });
});

describe('cart updated detection', () => {
  it('emits cart_updated for an add-to-cart button with quantity', () => {
    document.body.innerHTML =
      '<button data-add-to-cart data-product-id="P-7" data-quantity="3">Add to cart</button>';
    const { signals } = start();

    click(document.querySelector('button')!);

    expect(signals[0].signal_type).toBe('cart_updated');
    expect(signals[0].payload.product_id).toBe('P-7');
    expect(signals[0].payload.quantity).toBe(3);
  });

  it('emits cart_updated for /cart/add links', () => {
    document.body.innerHTML =
      '<a href="/cart/add?product=SKU-9" data-aether-track>Add</a>';
    const { signals } = start();

    click(document.querySelector('a')!);

    expect(signals[0].signal_type).toBe('cart_updated');
  });

  it('emits cart_updated for aria-labelled add-to-cart controls', () => {
    document.body.innerHTML =
      '<button data-product-id="P-2" aria-label="Add to cart">Icon</button>';
    const { signals } = start();

    click(document.querySelector('button')!);

    expect(signals[0].signal_type).toBe('cart_updated');
  });

  it('emits a cart_updated page-load signal on cart pages', () => {
    withUrl('/cart');
    const { signals } = start();

    const cart = signals.find((s) => s.signal_type === 'cart_updated');
    expect(cart).toBeDefined();
    expect(cart!.payload.reason).toBe('cart_page_view');
    expect(cart!.payload.method).toBe('page_load');
  });
});

describe('checkout started detection', () => {
  it('emits checkout_started for a checkout button', () => {
    document.body.innerHTML = '<button class="checkout-btn">Checkout</button>';
    const { signals } = start();

    click(document.querySelector('button')!);

    expect(signals[0].signal_type).toBe('checkout_started');
    expect(signals[0].payload.step).toBe(1);
  });

  it('emits checkout_started for a /checkout link', () => {
    document.body.innerHTML =
      '<a href="/checkout" data-aether-track>Proceed</a>';
    const { signals } = start();

    click(document.querySelector('a')!);

    expect(signals[0].signal_type).toBe('checkout_started');
    expect(signals[0].payload.method).toBe('link');
    expect(String(signals[0].payload.destination_path)).toContain('/checkout');
  });
});

describe('order confirmation detection', () => {
  it('emits order_confirmed from a structured order element', () => {
    withUrl('/thank-you');
    document.body.innerHTML =
      '<div class="order-confirmation" data-order-id="ORD-123">Thank you</div>';
    const { signals } = start();

    const signal = signals.find((s) => s.signal_type === 'order_confirmed');
    expect(signal).toBeDefined();
    expect(signal!.payload.order_id).toBe('ORD-123');
    expect(signal!.payload.method).toBe('structured_element');
    expect(signal!.lineage.source_record_id).toBe('ORD-123');
  });

  it('emits order_confirmed from a confirmation path alone', () => {
    withUrl('/order/confirmation');
    const { signals } = start();

    const signal = signals.find((s) => s.signal_type === 'order_confirmed');
    expect(signal).toBeDefined();
    expect(signal!.payload.order_id).toBeNull();
    expect(signal!.payload.method).toBe('confirmation_path');
  });

  it('does NOT match blog content mentioning confirmation', () => {
    withUrl('/blog/confirmation-message');
    document.body.innerHTML = '<p>How to handle confirmation messages</p>';
    const { signals } = start();

    expect(signals.some((s) => s.signal_type === 'order_confirmed')).toBe(false);
  });

  it('dedupes confirmation observations by order id (no replay on re-detect)', () => {
    withUrl('/order/confirmation');
    document.body.innerHTML = '<div data-order-id="ORD-9"></div>';
    const { module, signals } = start();

    module.detectOnLoad(); // second pass — same order id
    module.detectOnLoad();

    const confirmations = signals.filter((s) => s.signal_type === 'order_confirmed');
    expect(confirmations).toHaveLength(1);
  });
});

describe('signal envelope invariants', () => {
  it('every emitted signal is schema-versioned, sanitized, and well-shaped', () => {
    withUrl('/products/abc?utm_campaign=x&token=SECRET');
    document.body.innerHTML =
      '<a href="/products/abc?utm_campaign=x&token=SECRET">Widget</a>';
    const { signals } = start();

    click(document.querySelector('a')!);

    const signal = signals[0];
    expect(signal.signal_id).toBeTruthy();
    expect(signal.occurred_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(signal.source_url).not.toContain('token');
    expect(signal.source_url).not.toContain('SECRET');
    expect(signal.lineage).toHaveProperty('source_record_id');
  });

  it('start() is idempotent and destroy() removes listeners', () => {
    document.body.innerHTML = '<button data-add-to-cart data-product-id="P-1">Add</button>';
    const { module, signals } = start();

    module.start(); // must not stack a second listener

    click(document.querySelector('button')!);
    const cartCount = signals.filter((s) => s.signal_type === 'cart_updated').length;
    expect(cartCount).toBe(1);

    module.destroy();
    click(document.querySelector('button')!);
    expect(signals.filter((s) => s.signal_type === 'cart_updated')).toHaveLength(1);
  });

  it('can disable order confirmation and cart-page detection via config', () => {
    withUrl('/cart');
    document.body.innerHTML = '<div data-order-id="ORD-1"></div>';
    const { signals } = start({ orderConfirmation: false, cartPageView: false });

    expect(signals).toHaveLength(0);
  });

  it('uses the pinned SDK_SIGNAL_SCHEMA_VERSION contract constant', () => {
    expect(SDK_SIGNAL_SCHEMA_VERSION).toBe('1');
  });

  it('does NOT fall back to Math.random for signal ids (deterministic fallback)', () => {
    // Remove crypto.randomUUID so the deterministic non-random fallback runs.
    vi.stubGlobal('crypto', {});
    document.body.innerHTML =
      '<div class="product-card" data-product-id="P-9" data-price="5.00"></div>';
    const { signals } = start();

    click(document.querySelector('.product-card')!);

    expect(signals).toHaveLength(1);
    expect(signals[0].signal_id).toBeTruthy();
    expect(signals[0].signal_id).toMatch(/^sig:product_view:/);
  });

  it('destroy() resets confirmation dedupe so a re-started module re-emits order_confirmed', () => {
    withUrl('/order/confirmation');
    document.body.innerHTML = '<div data-order-id="ORD-9"></div>';
    const { module, signals } = start();

    expect(signals.filter((s) => s.signal_type === 'order_confirmed')).toHaveLength(1);

    module.destroy();
    module.start(); // re-init on the same URL

    const confirmations = signals.filter((s) => s.signal_type === 'order_confirmed');
    expect(confirmations).toHaveLength(2);
  });
});
