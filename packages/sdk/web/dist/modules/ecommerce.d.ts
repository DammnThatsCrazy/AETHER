export interface EcommerceCallbacks {
    /** Emit a canonical registry event type (routed through AetherSDK.observe). */
    onObserve: (type: string, props: Record<string, unknown>) => void;
}
export declare class EcommerceModule {
    private callbacks;
    constructor(callbacks: EcommerceCallbacks);
    /** Track a product view — emits canonical `product_viewed`. */
    trackProductView(product: Record<string, unknown>): void;
    /** Track add-to-cart — emits canonical `cart_item_added`. */
    trackAddToCart(item: Record<string, unknown>): void;
    /** Track remove-from-cart — emits canonical `cart_item_removed`. */
    trackRemoveFromCart(item: Record<string, unknown>): void;
    /** Track checkout — emits canonical `checkout_started`. */
    trackCheckout(items: Record<string, unknown>[], step?: number): void;
    /** Track purchase — emits canonical `order_completed`. */
    trackPurchase(order: Record<string, unknown>): void;
    /** @deprecated use {@link trackAddToCart}; emits canonical `cart_item_added`. */
    productAdded(item: Record<string, unknown>): void;
    /** @deprecated use {@link trackRemoveFromCart}; emits canonical `cart_item_removed`. */
    productRemoved(item: Record<string, unknown>): void;
    /** Clean up */
    destroy(): void;
}
