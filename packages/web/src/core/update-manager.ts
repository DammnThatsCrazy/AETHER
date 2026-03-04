// =============================================================================
// AETHER SDK — UPDATE MANAGER
// Fetches remote manifest, syncs OTA data modules (chain registry, protocols,
// wallet labels, wallet classification) without requiring SDK reinstall.
// =============================================================================

interface SDKManifest {
  latestVersion: string;
  minimumVersion: string;
  updateUrgency: 'none' | 'recommended' | 'critical';
  downloads?: {
    sdkBundleUrl: string;
    sdkBundleHash: string;
    sdkBundleSize: number;
  };
  featureFlags: Record<string, boolean>;
  dataModules: {
    chainRegistry?: DataModuleDescriptor;
    protocolRegistry?: DataModuleDescriptor;
    walletLabels?: DataModuleDescriptor;
    walletClassification?: DataModuleDescriptor;
  };
  checkIntervalMs: number;
  generatedAt: string;
}

interface DataModuleDescriptor {
  version: string;
  url: string;
  hash: string;
  size: number;
  updatedAt: string;
}

interface UpdateManagerConfig {
  enabled: boolean;
  checkIntervalMs?: number;
  onUpdateAvailable?: (version: string, urgency: string) => void;
}

interface DataModuleCache {
  version: string;
  data: unknown;
  hash: string;
  updatedAt: string;
}

type DataModuleInjector = (data: unknown) => void;

const STORAGE_PREFIX = '_aether_dm_';
const MANIFEST_CACHE_KEY = '_aether_manifest';

/**
 * UpdateManager — OTA Data Module Sync
 *
 * Runs after SDK init() as a non-blocking, fire-and-forget background process.
 * Fetches the SDK manifest from CDN, checks for updated data modules,
 * downloads and verifies them, then injects into running SDK registries.
 */
export class UpdateManager {
  private config: UpdateManagerConfig;
  private endpoint: string;
  private sdkVersion: string;
  private checkTimer: ReturnType<typeof setInterval> | null = null;
  private injectors: Map<string, DataModuleInjector> = new Map();
  private debug: boolean;
  private destroyed = false;

  constructor(
    endpoint: string,
    sdkVersion: string,
    config: Partial<UpdateManagerConfig> = {},
    debug = false,
  ) {
    this.endpoint = endpoint;
    this.sdkVersion = sdkVersion;
    this.debug = debug;
    this.config = {
      enabled: config.enabled ?? true,
      checkIntervalMs: config.checkIntervalMs,
      onUpdateAvailable: config.onUpdateAvailable,
    };
  }

  /**
   * Register a data module injector function.
   * Called when an OTA update is available for the given module.
   */
  registerInjector(moduleName: string, injector: DataModuleInjector): void {
    this.injectors.set(moduleName, injector);
  }

  /**
   * Start the update manager. Non-blocking — returns immediately.
   */
  start(): void {
    if (!this.config.enabled) {
      this.log('Auto-update disabled');
      return;
    }

    this.log('Starting UpdateManager');

    // Initial check (fire-and-forget)
    this.checkForUpdates().catch((err) => {
      this.log('Initial update check failed:', err.message);
    });
  }

  /**
   * Check for updates: fetch manifest, compare data module versions,
   * download and inject any updates.
   */
  async checkForUpdates(): Promise<void> {
    if (this.destroyed) return;

    try {
      const manifest = await this.fetchManifest();
      if (this.destroyed) return;

      // Check SDK version urgency
      if (manifest.updateUrgency !== 'none' && manifest.latestVersion !== this.sdkVersion) {
        this.config.onUpdateAvailable?.(manifest.latestVersion, manifest.updateUrgency);
      }

      // Sync data modules
      await this.syncDataModules(manifest);

      // Schedule next check
      const interval = this.config.checkIntervalMs ?? manifest.checkIntervalMs ?? 3600000;
      this.scheduleNextCheck(interval);

      this.log(`Update check complete. Next check in ${interval / 1000}s`);
    } catch (error) {
      // Schedule retry with backoff
      this.scheduleNextCheck(300000); // Retry in 5 minutes
      throw error;
    }
  }

  /**
   * Fetch the SDK manifest from CDN
   */
  private async fetchManifest(): Promise<SDKManifest> {
    const url = `${this.endpoint}/sdk/manifests/web/latest.json`;
    this.log(`Fetching manifest: ${url}`);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);

    try {
      const response = await fetch(url, {
        signal: controller.signal,
        cache: 'no-cache',
        headers: {
          'X-Aether-SDK': 'web',
          'X-Aether-Version': this.sdkVersion,
        },
      });

      if (!response.ok) {
        throw new Error(`Manifest fetch failed: HTTP ${response.status}`);
      }

      const manifest: SDKManifest = await response.json();

      // Cache manifest
      try {
        localStorage.setItem(MANIFEST_CACHE_KEY, JSON.stringify(manifest));
      } catch {}

      return manifest;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Sync data modules: compare versions, download updates, verify and inject
   */
  private async syncDataModules(manifest: SDKManifest): Promise<void> {
    const modules = manifest.dataModules;
    if (!modules) return;

    const updatePromises: Promise<void>[] = [];

    for (const [name, descriptor] of Object.entries(modules)) {
      if (!descriptor) continue;

      const cached = this.getCachedModule(name);

      // Skip if we have the same version cached
      if (cached && cached.version === descriptor.version) {
        // Inject cached data if injector is registered but data hasn't been injected yet
        const injector = this.injectors.get(name);
        if (injector && cached.data) {
          try { injector(cached.data); } catch {}
        }
        continue;
      }

      // New version available — download
      updatePromises.push(this.updateModule(name, descriptor));
    }

    if (updatePromises.length > 0) {
      await Promise.allSettled(updatePromises);
    }
  }

  /**
   * Download, verify, cache, and inject a single data module
   */
  private async updateModule(name: string, descriptor: DataModuleDescriptor): Promise<void> {
    this.log(`Updating data module: ${name} v${descriptor.version}`);

    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 15000);

      let text: string;
      try {
        const response = await fetch(descriptor.url, {
          signal: controller.signal,
          cache: 'no-cache',
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        text = await response.text();
      } finally {
        clearTimeout(timer);
      }

      // Verify SHA-256 hash
      if (descriptor.hash) {
        const hash = await this.sha256(text);
        if (hash && hash !== descriptor.hash) {
          this.log(`Hash mismatch for ${name}: expected ${descriptor.hash}, got ${hash}`);
          return; // Reject update, keep previous version
        }
      }

      // Parse and validate
      const data = JSON.parse(text);

      // Cache
      const cached: DataModuleCache = {
        version: descriptor.version,
        data,
        hash: descriptor.hash,
        updatedAt: descriptor.updatedAt,
      };

      try {
        localStorage.setItem(STORAGE_PREFIX + name, JSON.stringify(cached));
      } catch {
        this.log(`Unable to cache module ${name} (localStorage full)`);
      }

      // Inject into running SDK
      const injector = this.injectors.get(name);
      if (injector) {
        injector(data);
        this.log(`Injected data module: ${name} v${descriptor.version}`);
      }
    } catch (error) {
      this.log(`Failed to update module ${name}: ${error instanceof Error ? error.message : error}`);
    }
  }

  /**
   * Get a cached data module from localStorage
   */
  private getCachedModule(name: string): DataModuleCache | null {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + name);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  /**
   * Load cached data modules and inject them (called on startup)
   */
  loadCachedModules(): void {
    for (const [name, injector] of this.injectors) {
      const cached = this.getCachedModule(name);
      if (cached?.data) {
        try {
          injector(cached.data);
          this.log(`Loaded cached module: ${name} v${cached.version}`);
        } catch {}
      }
    }
  }

  /**
   * Schedule the next update check
   */
  private scheduleNextCheck(intervalMs: number): void {
    if (this.checkTimer) {
      clearInterval(this.checkTimer);
    }

    this.checkTimer = setInterval(() => {
      this.checkForUpdates().catch((err) => {
        this.log('Scheduled update check failed:', err.message);
      });
    }, intervalMs);
  }

  /**
   * SHA-256 hash for integrity verification
   */
  private async sha256(text: string): Promise<string> {
    if (typeof crypto?.subtle?.digest !== 'function') return '';
    const buffer = new TextEncoder().encode(text);
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  /**
   * Stop the update manager and clean up
   */
  destroy(): void {
    this.destroyed = true;
    if (this.checkTimer) {
      clearInterval(this.checkTimer);
      this.checkTimer = null;
    }
    this.injectors.clear();
    this.log('UpdateManager destroyed');
  }

  private log(...args: unknown[]): void {
    if (!this.debug) return;
    console.debug('[Aether UpdateManager]', ...args);
  }
}
