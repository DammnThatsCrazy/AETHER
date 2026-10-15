export interface AutoDiscoveryCallbacks {
    onTrack: (event: string, properties: Record<string, unknown>) => void;
    /** Canonical registry event emitter (navigation_intent / navigation_arrival). */
    onObserve?: (type: string, properties: Record<string, unknown>) => void;
}
export interface AutoDiscoveryConfig {
    /** Emit navigation_intent/navigation_arrival correlation events (default on). */
    navigationCorrelation?: boolean;
}
export declare class AutoDiscoveryModule {
    private callbacks;
    private config;
    private listeners;
    private started;
    constructor(callbacks: AutoDiscoveryCallbacks, config?: AutoDiscoveryConfig);
    /** Start click tracking (idempotent — never stacks duplicate listeners) */
    start(): void;
    /** Stop all tracking and clean up */
    destroy(): void;
    /**
     * Consume a pending navigation intent and emit `navigation_arrival`.
     * Called on page load and after SPA route completion. Consumed exactly
     * once; expired intents are dropped silently.
     */
    recordArrival(): void;
    private trackClicks;
    /**
     * Element identity preference: data-aether-id → stable element id →
     * accessible name (aria-label / trimmed text, truncated, privacy-reduced)
     * → structural selector fallback.
     */
    private resolveIdentity;
    /** aria-label or trimmed text content, truncated and digit-reduced. */
    private accessibleName;
    private emitNavigationIntent;
    /** Read + delete the stored intent; expired entries are dropped silently. */
    private consumeStoredIntent;
    private getSelector;
}
