interface LoaderConfig {
    /** Cache TTL in milliseconds. Default: 3600000 (1 hour) */
    cacheTTL?: number;
    /** Pin to a specific version or use 'latest'. Default: 'latest' */
    version?: string;
    /** Callback when SDK is loaded and ready */
    onReady?: (sdk: any) => void;
    /** Callback on load failure */
    onError?: (error: Error) => void;
    /** Network timeout in ms. Default: 10000 */
    timeout?: number;
    /** CDN base URL. Default: 'https://cdn.aether.network/sdk' */
    cdnBase?: string;
}
interface CachedBundle {
    version: string;
    code: string;
    timestamp: number;
    hash: string;
}
interface SDKManifest {
    latestVersion: string;
    minimumVersion: string;
    updateUrgency: 'none' | 'recommended' | 'critical';
    downloads?: {
        sdkBundleUrl: string;
        sdkBundleHash: string;
        sdkBundleSize: number;
    };
    checkIntervalMs: number;
    generatedAt: string;
}
/**
 * AetherLoader — CDN Auto-Loader
 *
 * Loads the latest Aether SDK bundle from CDN with intelligent caching.
 * Place at a stable, never-changing URL: cdn.aether.network/sdk/v5/loader.js
 *
 * Usage:
 *   <script src="https://cdn.aether.network/sdk/v5/loader.js"></script>
 *   <script>
 *     AetherLoader.load().then(aether => aether.init({ apiKey: 'your-key' }));
 *   </script>
 */
declare const AetherLoader: {
    _loaded: boolean;
    _sdk: any;
    _loading: Promise<any> | null;
    /**
     * Load the Aether SDK. Returns the SDK singleton.
     * Caches the bundle in localStorage for fast subsequent loads.
     */
    load(config?: LoaderConfig): Promise<any>;
    _doLoad(config: LoaderConfig): Promise<any>;
    /**
     * Background update check — runs after serving from cache
     */
    _backgroundUpdate(cdnBase: string, requestedVersion: string, cached: CachedBundle, timeout: number): Promise<void>;
    /**
     * Fetch the SDK manifest from CDN
     */
    _fetchManifest(cdnBase: string, version: string, timeout: number): Promise<SDKManifest>;
    /**
     * Fetch with timeout via AbortController
     */
    _fetchWithTimeout(url: string, timeout: number): Promise<string>;
    /**
     * Evaluate the SDK bundle code in the global scope
     */
    _evaluateBundle(code: string): void;
    /**
     * SHA-256 hash for integrity verification
     */
    _sha256(text: string): Promise<string>;
    /**
     * Get cached bundle from localStorage
     */
    _getCachedBundle(): CachedBundle | null;
    /**
     * Store bundle in localStorage
     */
    _setCachedBundle(bundle: CachedBundle): void;
    /**
     * Clear the cached bundle
     */
    clearCache(): void;
    /**
     * Get the currently loaded SDK version
     */
    getLoadedVersion(): string | null;
};
export default AetherLoader;
export { AetherLoader };
export type { LoaderConfig, SDKManifest };
