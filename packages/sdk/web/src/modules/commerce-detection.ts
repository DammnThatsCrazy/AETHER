// =============================================================================
// Aether SDK — COMMERCE DETECTION MODULE (WS2, Tier 2 Thin Client)
//
// SDK plane ONLY: DOM heuristics turn page interactions into RAW, schema-
// versioned `SDKCommerceSignal` observations (product_view / cart_updated /
// checkout_started / order_confirmed). This module NEVER emits runtime
// `commerce.*` events and NEVER claims a server-confirmed state — it only
// calls `onSignal`, and the SDK layer decides what the signal means.
//
// Heuristics mirror the auto-discovery DOM-frame:
//   - click resolution to the owning interactive control (nested SVG/span),
//   - idempotent start(), destruction-safe listener teardown,
//   - privacy: sanitized source URLs + digit-redacted free-text fields.
//
// Privacy scope: structured commerce identifiers (product_id, order_id, price)
// are merchant data, not PII, and pass through verbatim. Free-text payload
// fields (product names) get the same long-digit-run redaction as
// auto-discovery's accessible-name handling.
// =============================================================================

import { now, sanitizeUrl } from '../utils';
import {
  type CommerceSignalType,
  type SDKCommerceSignal,
} from '@aether/shared/commerce-bridge';

/**
 * Monotonic sequence backing the deterministic signal_id fallback. Reset on
 * module load only — a destroyed/re-initialized module keeps counting so ids
 * never collide across sessions on the same page.
 */
let signalSequence = 0;

/**
 * Build a signal_id without `Math.random` (checklist item 9). Prefers the
 * platform `crypto.randomUUID` when available; otherwise falls back to a
 * deterministic scheme (monotonic sequence + signal context) so a missing
 * `randomUUID` never leaks a Math.random id and identical inputs + state
 * always produce the same id.
 */
function makeSignalId(
  signalType: CommerceSignalType,
  occurredAt: string,
  sourceRecordId: string | null,
): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  signalSequence += 1;
  return `sig:${signalType}:${occurredAt}:${signalSequence}:${sourceRecordId ?? 'none'}`;
}

export interface CommerceDetectionCallbacks {
  /** Called once per raw SDK-plane observation. */
  onSignal: (signal: SDKCommerceSignal) => void;
}

export interface CommerceDetectionConfig {
  /**
   * Detect order confirmation pages (structured order elements + dedicated
   * confirmation paths). Default: on.
   */
  orderConfirmation?: boolean;
  /**
   * Emit a cart_updated observation on cart-page load. Default: on.
   */
  cartPageView?: boolean;
}

/** Selector matching the interactive controls a click should resolve to. */
const INTERACTIVE_SELECTOR =
  'a, button, input[type="button"], input[type="submit"], [role="button"], [data-aether-track]';

const PRODUCT_SELECTOR =
  '[data-aether-product], [data-product-id], [itemprop="product"], .product-card, .product-tile, .product-item';
const ADD_TO_CART_SELECTOR =
  '[data-add-to-cart], [data-aether-cart], [data-cart-add], .add-to-cart, .add_to_cart, [data-add-to-cart-button], [aria-label*="add to cart" i]';
const CHECKOUT_SELECTOR =
  '[data-aether-checkout], [data-checkout], .checkout-btn, .checkout-button, [aria-label*="checkout" i], [aria-label*="buy now" i]';

const ADD_TO_CART_TEXT = /add to cart|add to bag|add to basket/i;
const CHECKOUT_TEXT = /^(checkout|buy now|buy it now|purchase|proceed to checkout)/i;
const PRODUCT_PATH = /\/products?\/([^/?#]+)/i;
const SHORT_PRODUCT_PATH = /\/p\/([^/?#]+)/i;
const CART_ADD_PATH = /\/cart\/add|\/bag\/add|\/add-to-cart|\/cart\/add-item/i;
const CHECKOUT_PATH = /\/checkout(\/|$|\.html)/i;
const CART_PAGE_PATH = /(^|\/)cart(\/|$|\.html)/i;

/** Anchored to a path segment so `/blog/confirmation-message` never matches. */
const CONFIRMATION_PATH =
  /(^|\/)(order(-|_)?confirm(ed|ation)|purchase(-|_)?confirm(ed|ation)|thank(-|_)?you|order(-|_)?(complete|success)|checkout(-|_)?\/(success|complete|confirmation)|order\/(confirm|confirmation|complete|success))(\/|$|\.html)/i;

const MAX_NAME_LENGTH = 120;

/** Redact long digit runs (account/phone-style PII) from free text. */
function redactDigits(text: string): string {
  return text.replace(/\s+/g, ' ').replace(/\d{4,}/g, '****').slice(0, MAX_NAME_LENGTH);
}

function parseQuantity(value: string | null | undefined): number {
  if (!value) return 1;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function urlSearchParam(search: string, key: string): string | null {
  try {
    return new URLSearchParams(search).get(key);
  } catch {
    return null;
  }
}

export class CommerceDetectionModule {
  private callbacks: CommerceDetectionCallbacks;
  private config: CommerceDetectionConfig;
  private listeners: Array<[EventTarget, string, EventListener]> = [];
  private started = false;
  /** Dedupe keys for confirmation observations (order_id or `path:<path>`). */
  private emittedConfirmationKeys = new Set<string>();

  constructor(callbacks: CommerceDetectionCallbacks, config: CommerceDetectionConfig = {}) {
    this.callbacks = callbacks;
    this.config = config;
  }

  /** Start click tracking + on-load detection (idempotent). */
  start(): void {
    if (typeof document === 'undefined' || this.started) return;
    this.started = true;
    this.trackClicks();
    this.detectOnLoad();
  }

  /** Stop all tracking and clean up. */
  destroy(): void {
    this.listeners.forEach(([target, event, handler]) => {
      target.removeEventListener(event, handler, { capture: true } as EventListenerOptions);
    });
    this.listeners = [];
    this.started = false;
    // Reset the confirmation dedupe set so a re-initialized SDK on the same
    // URL emits a fresh order_confirmed observation for a new session.
    this.emittedConfirmationKeys.clear();
  }

  /**
   * Re-run URL/DOM-driven detection. Called on page load and after SPA route
   * completion (index.ts). Order-confirmation observations are deduped by
   * order id / path so a confirmation is observed once, never replayed.
   */
  detectOnLoad(): void {
    if (typeof window === 'undefined' || typeof document === 'undefined') return;
    this.detectOrderConfirmation();
    if (this.config.cartPageView !== false) {
      this.detectCartPage();
    }
  }

  private trackClicks(): void {
    const handler = (e: Event) => {
      const event = e as MouseEvent;
      const rawTarget = event.target as Element | null;
      if (!rawTarget) return;

      // Interactive-ancestor resolution: a click on a nested <svg>/<span>
      // resolves to the button/link that owns it (mirrors auto-discovery).
      const control = (typeof rawTarget.closest === 'function'
        ? rawTarget.closest(INTERACTIVE_SELECTOR)
        : null) as HTMLElement | null;
      const element = control ?? (rawTarget as HTMLElement);
      if (!element.tagName) return;

      const anchor = element.closest?.('a') as HTMLAnchorElement | null;
      let href: string | undefined;
      if (anchor) {
        try {
          href = new URL(anchor.href, window.location.href).toString();
        } catch {
          href = undefined;
        }
      }

      if (this.isCartElement(element, href)) {
        this.emitCartSignal(element);
        return;
      }
      if (this.isCheckoutElement(element, href)) {
        this.emitCheckoutSignal(element, href);
        return;
      }
      if (this.isProductElement(element, href)) {
        this.emitProductSignal(element, href);
      }
    };

    document.addEventListener('click', handler, { passive: true, capture: true });
    this.listeners.push([document, 'click', handler]);
  }

  // -------------------------------------------------------------------------
  // Heuristics
  // -------------------------------------------------------------------------

  private isCartElement(el: HTMLElement, href?: string): boolean {
    if (this.matches(el, ADD_TO_CART_SELECTOR)) return true;
    if (href && CART_ADD_PATH.test(href)) return true;
    const text = this.textOf(el);
    return Boolean(text && ADD_TO_CART_TEXT.test(text));
  }

  private isCheckoutElement(el: HTMLElement, href?: string): boolean {
    if (this.matches(el, CHECKOUT_SELECTOR)) return true;
    if (href && CHECKOUT_PATH.test(href)) return true;
    const text = this.textOf(el);
    return Boolean(text && CHECKOUT_TEXT.test(text.trim()));
  }

  private isProductElement(el: HTMLElement, href?: string): boolean {
    if (this.matches(el, PRODUCT_SELECTOR)) return true;
    if (href) {
      if (PRODUCT_PATH.test(href) || SHORT_PRODUCT_PATH.test(href)) return true;
      const productParam = urlSearchParam(new URL(href).search, 'product');
      if (productParam) return true;
    }
    // Microdata product container without a data attribute.
    return Boolean(el.querySelector('[itemprop="product"], [itemprop="name"]'));
  }

  // -------------------------------------------------------------------------
  // Signal construction
  // -------------------------------------------------------------------------

  private emitSignal(
    signalType: CommerceSignalType,
    payload: Record<string, unknown>,
    sourceRecordId: string | null,
  ): void {
    const occurredAt = now();
    const signal: SDKCommerceSignal = {
      signal_id: makeSignalId(signalType, occurredAt, sourceRecordId),
      signal_type: signalType,
      occurred_at: occurredAt,
      source_url: sanitizeUrl(
        typeof window !== 'undefined' ? window.location.href : '',
      ),
      lineage: { source_record_id: sourceRecordId },
      payload,
    };
    this.callbacks.onSignal(signal);
  }

  private emitProductSignal(el: HTMLElement, href?: string): void {
    const productId =
      el.getAttribute('data-product-id') ??
      el.getAttribute('data-aether-product') ??
      this.productIdFromUrl(href);
    if (!productId) return;

    const price =
      el.getAttribute('data-price') ??
      el.getAttribute('data-aether-price') ??
      this.microdataText(el, 'price');
    const name =
      el.getAttribute('data-product-name') ??
      el.getAttribute('aria-label') ??
      this.textOf(el);

    this.emitSignal(
      'product_view',
      {
        product_id: productId,
        name: name ? redactDigits(name) : undefined,
        price: price ?? undefined,
        currency: el.getAttribute('data-currency') ?? el.getAttribute('data-aether-currency') ?? undefined,
        category: el.getAttribute('data-category') ?? undefined,
        method: 'click',
      },
      productId,
    );
  }

  private emitCartSignal(el: HTMLElement): void {
    const productId =
      el.getAttribute('data-product-id') ??
      el.getAttribute('data-cart-product') ??
      this.closestAttribute(el, 'data-product-id');
    const quantity = parseQuantity(el.getAttribute('data-quantity') ?? this.quantityInput(el));
    const price =
      el.getAttribute('data-price') ??
      this.closestAttribute(el, 'data-price') ??
      undefined;

    this.emitSignal(
      'cart_updated',
      {
        product_id: productId ?? undefined,
        quantity,
        price: price ?? undefined,
        currency: el.getAttribute('data-currency') ?? this.closestAttribute(el, 'data-currency') ?? undefined,
        method: 'click',
      },
      productId ?? null,
    );
  }

  private emitCheckoutSignal(el: HTMLElement, href?: string): void {
    this.emitSignal(
      'checkout_started',
      {
        step: 1,
        method: href ? 'link' : 'click',
        destination_path: href ? sanitizeUrl(href) : undefined,
      },
      null,
    );
  }

  private detectOrderConfirmation(): void {
    if (this.config.orderConfirmation === false) return;
    const path = window.location.pathname;
    const orderEl = document.querySelector(
      '[data-aether-order], [data-order-id], [itemprop="order"], .order-confirmation, .thank-you-order',
    );
    const orderId =
      orderEl?.getAttribute('data-order-id') ??
      orderEl?.getAttribute('data-aether-order') ??
      urlSearchParam(window.location.search, 'order_id') ??
      urlSearchParam(window.location.search, 'order');
    const isConfirmationPath = CONFIRMATION_PATH.test(path);

    if (!orderId && !isConfirmationPath) return;
    const key = orderId ?? `path:${path}`;
    if (this.emittedConfirmationKeys.has(key)) return;
    this.emittedConfirmationKeys.add(key);

    this.emitSignal(
      'order_confirmed',
      {
        order_id: orderId ?? null,
        method: orderId ? 'structured_element' : 'confirmation_path',
      },
      orderId ?? null,
    );
  }

  private detectCartPage(): void {
    const path = window.location.pathname;
    if (!CART_PAGE_PATH.test(path)) return;
    this.emitSignal(
      'cart_updated',
      { reason: 'cart_page_view', method: 'page_load' },
      null,
    );
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  private matches(el: HTMLElement, selector: string): boolean {
    return typeof el.matches === 'function' && el.matches(selector);
  }

  private textOf(el: HTMLElement): string {
    return (el.textContent ?? '').replace(/\s+/g, ' ').trim();
  }

  private microdataText(el: HTMLElement, itemprop: string): string | undefined {
    const node = el.querySelector(`[itemprop="${itemprop}"]`);
    const text = node ? (node.textContent ?? '').trim() : '';
    return text || undefined;
  }

  private closestAttribute(el: HTMLElement, attr: string): string | null {
    let current: HTMLElement | null = el;
    while (current) {
      const value = current.getAttribute(attr);
      if (value) return value;
      current = current.parentElement;
    }
    return null;
  }

  private quantityInput(el: HTMLElement): string | null {
    const container = el.closest('[data-quantity], .quantity, form, [data-cart-item]');
    const input = container?.querySelector('input[name="quantity"], [data-quantity-input]');
    return input instanceof HTMLInputElement ? input.value : null;
  }

  private productIdFromUrl(href?: string): string | null {
    if (!href) return null;
    const match = PRODUCT_PATH.exec(href) ?? SHORT_PRODUCT_PATH.exec(href);
    if (match) return match[1];
    try {
      return urlSearchParam(new URL(href).search, 'product_id') ??
        urlSearchParam(new URL(href).search, 'product');
    } catch {
      return null;
    }
  }
}
