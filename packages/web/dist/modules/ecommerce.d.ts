export interface EcommerceCallbacks {
    onTrack: (event: string, props: Record<string, unknown>) => void;
}
export declare class EcommerceModule {
    private callbacks;
    constructor(callbacks: EcommerceCallbacks);
    /** Track a product view */
    trackProductView(product: Record<string, unknown>): void;
    /** Track add-to-cart */
    trackAddToCart(item: Record<string, unknown>): void;
    /** Track remove-from-cart */
    trackRemoveFromCart(item: Record<string, unknown>): void;
    /** Track checkout */
    trackCheckout(items: Record<string, unknown>[], step?: number): void;
    /** Track purchase */
    trackPurchase(order: Record<string, unknown>): void;
    /** Clean up */
    destroy(): void;
}
