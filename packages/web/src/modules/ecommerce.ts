// =============================================================================
// AETHER SDK — E-COMMERCE MODULE (Tier 2 Thin Client)
// Ships raw e-commerce events to backend. No cart state, no funnel logic.
// =============================================================================

export interface EcommerceCallbacks {
  onTrack: (event: string, props: Record<string, unknown>) => void;
}

export class EcommerceModule {
  private callbacks: EcommerceCallbacks;

  constructor(callbacks: EcommerceCallbacks) {
    this.callbacks = callbacks;
  }

  /** Track a product view */
  trackProductView(product: Record<string, unknown>): void {
    this.callbacks.onTrack('product_viewed', product);
  }

  /** Track add-to-cart */
  trackAddToCart(item: Record<string, unknown>): void {
    this.callbacks.onTrack('product_added', item);
  }

  /** Track remove-from-cart */
  trackRemoveFromCart(item: Record<string, unknown>): void {
    this.callbacks.onTrack('product_removed', item);
  }

  /** Track checkout */
  trackCheckout(items: Record<string, unknown>[], step?: number): void {
    this.callbacks.onTrack('checkout_started', { items, step: step ?? 1 });
  }

  /** Track purchase */
  trackPurchase(order: Record<string, unknown>): void {
    this.callbacks.onTrack('order_completed', order);
  }

  /** Clean up */
  destroy(): void {
    // No resources to clean up in thin client
  }
}
