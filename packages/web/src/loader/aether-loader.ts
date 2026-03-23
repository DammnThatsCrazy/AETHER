// =============================================================================
// AETHER SDK — CDN AUTO-LOADER v5.0
// Lightweight (~3KB) loader at stable URL that dynamically loads the latest SDK
// URL: cdn.aether.network/sdk/v5/loader.js
// =============================================================================

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

const STORAGE_KEY = '_aether_loader_bundle';
const MANIFEST_KEY = '_aether_loader_manifest';
const DEFAULT_CDN = 'https://cdn.aether.network/sdk';
const DEFAULT_TTL = 3600000; // 1 hour
const DEFAULT_TIMEOUT = 10000; // 10 seconds

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
const AetherLoader = {
  _loaded: false,
  _sdk: null as any,
  _loading: null as Promise<any> | null,

  /**
   * Load the Aether SDK. Returns the SDK singleton.
   * Caches the bundle in localStorage for fast subsequent loads.
   */
  async load(config: LoaderConfig = {}): Promise<any> {
    // Return cached SDK if already loaded in this session
    if (this._loaded && this._sdk) {
      config.onReady?.(this._sdk);
      return this._sdk;
    }

    // Deduplicate concurrent load() calls
    if (this._loading) return this._loading;

    this._loading = this._doLoad(config);
    try {
      const sdk = await this._loading;
      return sdk;
    } finally {
      this._loading = null;
    }
  },

  async _doLoad(config: LoaderConfig): Promise<any> {
    const cdnBase = config.cdnBase ?? DEFAULT_CDN;
    const cacheTTL = config.cacheTTL ?? DEFAULT_TTL;
    const timeout = config.timeout ?? DEFAULT_TIMEOUT;
    const requestedVersion = config.version ?? 'latest';

    try {
      // 1. Check localStorage cache
      const cached = this._getCachedBundle();

      if (cached && (Date.now() - cached.timestamp) < cacheTTL) {
        // Cache is fresh — use immediately
        this._evaluateBundle(cached.code);
        config.onReady?.(this._sdk);

        // Background check for newer version (fire-and-forget)
        this._backgroundUpdate(cdnBase, requestedVersion, cached, timeout).catch(() => {});

        return this._sdk;
      }

      // 2. Cache expired or missing — fetch manifest to resolve version
      const manifest = await this._fetchManifest(cdnBase, requestedVersion, timeout);
      const targetVersion = requestedVersion === 'latest'
        ? manifest.latestVersion
        : requestedVersion;

      // If cached version matches latest, refresh timestamp and use
      if (cached && cached.version === targetVersion) {
        cached.timestamp = Date.now();
        this._setCachedBundle(cached);
        this._evaluateBundle(cached.code);
        config.onReady?.(this._sdk);
        return this._sdk;
      }

      // 3. Fetch the SDK bundle
      const bundleUrl = manifest.downloads?.sdkBundleUrl
        ?? `${cdnBase}/${targetVersion}/aether.umd.js`;

      const code = await this._fetchWithTimeout(bundleUrl, timeout);

      // 4. Verify hash if provided
      if (manifest.downloads?.sdkBundleHash) {
        const hash = await this._sha256(code);
        if (hash !== manifest.downloads.sdkBundleHash) {
          throw new Error(`Bundle hash mismatch: expected ${manifest.downloads.sdkBundleHash}, got ${hash}`);
        }
      }

      // 5. Cache and evaluate
      this._setCachedBundle({
        version: targetVersion,
        code,
        timestamp: Date.now(),
        hash: manifest.downloads?.sdkBundleHash ?? '',
      });

      this._evaluateBundle(code);
      config.onReady?.(this._sdk);
      return this._sdk;
    } catch (error) {
      // Fallback: try expired cache
      const cached = this._getCachedBundle();
      if (cached) {
        console.warn('[Aether Loader] CDN unreachable, using cached SDK v' + cached.version);
        this._evaluateBundle(cached.code);
        config.onReady?.(this._sdk);
        return this._sdk;
      }

      // No cache, no network — fatal
      const err = error instanceof Error ? error : new Error(String(error));
      config.onError?.(err);
      throw err;
    }
  },

  /**
   * Background update check — runs after serving from cache
   */
  async _backgroundUpdate(
    cdnBase: string,
    requestedVersion: string,
    cached: CachedBundle,
    timeout: number,
  ): Promise<void> {
    try {
      const manifest = await this._fetchManifest(cdnBase, requestedVersion, timeout);
      const targetVersion = requestedVersion === 'latest'
        ? manifest.latestVersion
        : requestedVersion;

      if (cached.version !== targetVersion) {
        // New version available — pre-fetch for next page load
        const bundleUrl = manifest.downloads?.sdkBundleUrl
          ?? `${cdnBase}/${targetVersion}/aether.umd.js`;
        const code = await this._fetchWithTimeout(bundleUrl, timeout);

        this._setCachedBundle({
          version: targetVersion,
          code,
          timestamp: Date.now(),
          hash: manifest.downloads?.sdkBundleHash ?? '',
        });

        console.info(`[Aether Loader] SDK v${targetVersion} pre-cached. Will be active on next page load.`);
      }
    } catch {
      // Background update failures are silent
    }
  },

  /**
   * Fetch the SDK manifest from CDN
   */
  async _fetchManifest(cdnBase: string, version: string, timeout: number): Promise<SDKManifest> {
    const url = `${cdnBase}/manifests/web/latest.json`;
    const text = await this._fetchWithTimeout(url, timeout);
    return JSON.parse(text);
  },

  /**
   * Fetch with timeout via AbortController
   */
  async _fetchWithTimeout(url: string, timeout: number): Promise<string> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);

    try {
      const response = await fetch(url, {
        signal: controller.signal,
        cache: 'no-cache',
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      return await response.text();
    } finally {
      clearTimeout(timer);
    }
  },

  /**
   * Evaluate the SDK bundle code in the global scope
   */
  _evaluateBundle(code: string): void {
    try {
      const fn = new Function(code);
      fn();
      // SDK is expected to set window.Aether or export via UMD
      this._sdk = (globalThis as any).Aether?.default ?? (globalThis as any).Aether;
      this._loaded = true;
    } catch (e) {
      throw new Error(`[Aether Loader] Failed to evaluate SDK bundle: ${e}`);
    }
  },

  /**
   * SHA-256 hash for integrity verification
   */
  async _sha256(text: string): Promise<string> {
    if (typeof crypto?.subtle?.digest !== 'function') return '';
    const buffer = new TextEncoder().encode(text);
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  },

  /**
   * Get cached bundle from localStorage
   */
  _getCachedBundle(): CachedBundle | null {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },

  /**
   * Store bundle in localStorage
   */
  _setCachedBundle(bundle: CachedBundle): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(bundle));
    } catch {
      // localStorage full or unavailable — continue without caching
      console.warn('[Aether Loader] Unable to cache SDK bundle (localStorage unavailable or full)');
    }
  },

  /**
   * Clear the cached bundle
   */
  clearCache(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(MANIFEST_KEY);
    } catch {}
    this._loaded = false;
    this._sdk = null;
  },

  /**
   * Get the currently loaded SDK version
   */
  getLoadedVersion(): string | null {
    const cached = this._getCachedBundle();
    return cached?.version ?? null;
  },
};

// UMD export for <script> tag usage
if (typeof globalThis !== 'undefined') {
  (globalThis as any).AetherLoader = AetherLoader;
}

export default AetherLoader;
export { AetherLoader };
export type { LoaderConfig, SDKManifest };
