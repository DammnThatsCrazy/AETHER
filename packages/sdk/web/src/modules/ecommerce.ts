// =============================================================================
// Aether SDK — E-COMMERCE MODULE (Tier 2 Thin Client)
// Ships raw e-commerce events to backend. No cart state, no funnel logic.
// Emits CANONICAL top-level commerce event types via observe(); the legacy
// `product_added` / `product_removed` names are gone from the wire — helper
// methods now emit `cart_item_added` / `cart_item_removed`.
// =============================================================================

export interface EcommerceCallbacks {
  /** Emit a canonical registry event type (routed through AetherSDK.observe). */
  onObserve: (type: string, props: Record<string, unknown>) => void;
}

export class EcommerceModule {
  private callbacks: EcommerceCallbacks;

  constructor(callbacks: EcommerceCallbacks) {
    this.callbacks = callbacks;
  }

  /** Track a product view — emits canonical `product_viewed`. */
  trackProductView(product: Record<string, unknown>): void {
    this.callbacks.onObserve('product_viewed', product);
  }

  /** Track add-to-cart — emits canonical `cart_item_added`. */
  trackAddToCart(item: Record<string, unknown>): void {
    this.callbacks.onObserve('cart_item_added', item);
  }

  /** Track remove-from-cart — emits canonical `cart_item_removed`. */
  trackRemoveFromCart(item: Record<string, unknown>): void {
    this.callbacks.onObserve('cart_item_removed', item);
  }

  /** Track checkout — emits canonical `checkout_started`. */
  trackCheckout(items: Record<string, unknown>[], step?: number): void {
    this.callbacks.onObserve('checkout_started', { items, step: step ?? 1 });
  }

  /** Track purchase — emits canonical `order_completed`. */
  trackPurchase(order: Record<string, unknown>): void {
    this.callbacks.onObserve('order_completed', order);
  }

  // ---------------------------------------------------------------------------
  // Deprecated legacy aliases — retained for source compatibility only. They now
  // emit the CANONICAL event types, never the retired `product_added` /
  // `product_removed` names.
  // ---------------------------------------------------------------------------

  /** @deprecated use {@link trackAddToCart}; emits canonical `cart_item_added`. */
  productAdded(item: Record<string, unknown>): void {
    this.trackAddToCart(item);
  }

  /** @deprecated use {@link trackRemoveFromCart}; emits canonical `cart_item_removed`. */
  productRemoved(item: Record<string, unknown>): void {
    this.trackRemoveFromCart(item);
  }

  /** Clean up */
  destroy(): void {
    // No resources to clean up in thin client
  }
}
