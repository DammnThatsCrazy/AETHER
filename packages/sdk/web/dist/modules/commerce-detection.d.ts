import { type SDKCommerceSignal } from '@aether/shared/commerce-bridge';
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
export declare class CommerceDetectionModule {
    private callbacks;
    private config;
    private listeners;
    private started;
    /** Dedupe keys for confirmation observations (order_id or `path:<path>`). */
    private emittedConfirmationKeys;
    constructor(callbacks: CommerceDetectionCallbacks, config?: CommerceDetectionConfig);
    /** Start click tracking + on-load detection (idempotent). */
    start(): void;
    /** Stop all tracking and clean up. */
    destroy(): void;
    /**
     * Re-run URL/DOM-driven detection. Called on page load and after SPA route
     * completion (index.ts). Order-confirmation observations are deduped by
     * order id / path so a confirmation is observed once, never replayed.
     */
    detectOnLoad(): void;
    private trackClicks;
    private isCartElement;
    private isCheckoutElement;
    private isProductElement;
    private emitSignal;
    private emitProductSignal;
    private emitCartSignal;
    private emitCheckoutSignal;
    private detectOrderConfirmation;
    private detectCartPage;
    private matches;
    private textOf;
    private microdataText;
    private closestAttribute;
    private quantityInput;
    private productIdFromUrl;
}
