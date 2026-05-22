export interface FeatureFlagCallbacks {
    onTrack: (event: string, properties: Record<string, unknown>) => void;
}
export interface FeatureFlagConfig {
    endpoint: string;
    apiKey: string;
    refreshIntervalMs?: number;
}
export declare class FeatureFlagModule {
    private callbacks;
    private config;
    private flags;
    private refreshTimer;
    constructor(callbacks: FeatureFlagCallbacks);
    /** Initialize: load cache, fetch from backend, start refresh timer */
    init(config: FeatureFlagConfig): Promise<void>;
    /** Check if a flag is enabled */
    isEnabled(key: string): boolean;
    /** Get a typed flag value with a default fallback */
    getValue<T>(key: string, defaultValue: T): T;
    /** Force-refresh flags from backend */
    refresh(): Promise<void>;
    /** Stop refresh timer and clean up */
    destroy(): void;
    private loadCache;
    private persistCache;
}
