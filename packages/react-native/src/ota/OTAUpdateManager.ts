// =============================================================================
// AETHER SDK — React Native OTA Update Manager (v5.0.0)
// Fetches remote manifest, syncs OTA data modules (chain registry, protocols,
// wallet labels, wallet classification) without requiring SDK reinstall.
// Uses AsyncStorage for caching; designed for fire-and-forget usage from
// AetherProvider.
// =============================================================================

import AsyncStorage from '@react-native-async-storage/async-storage';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DataModuleDescriptor {
  version: string;
  url: string;
  hash: string;
  size: number;
  updatedAt: string;
}

interface SDKManifest {
  latestVersion: string;
  minimumVersion: string;
  updateUrgency: 'none' | 'recommended' | 'critical';
  featureFlags: Record<string, boolean>;
  dataModules: Record<string, DataModuleDescriptor>;
  checkIntervalMs: number;
  generatedAt: string;
}

interface UpdateCheckResult {
  available: boolean;
  version?: string;
  urgency?: 'none' | 'recommended' | 'critical';
}

interface CachedModule {
  version: string;
  data: unknown;
  hash: string;
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VERSION = '5.0.0';
const STORAGE_PREFIX = '@aether_dm_';
const MANIFEST_KEY = '@aether_manifest';
const FETCH_TIMEOUT_MS = 10_000;
const MODULE_FETCH_TIMEOUT_MS = 15_000;

// ---------------------------------------------------------------------------
// OTAUpdateManager
// ---------------------------------------------------------------------------

/**
 * OTA Update Manager for React Native.
 *
 * Designed for fire-and-forget usage from `AetherProvider`:
 *
 * ```ts
 * useEffect(() => {
 *   OTAUpdateManager.syncDataModules(endpoint, sdkVersion).catch(() => {});
 * }, []);
 * ```
 *
 * Read cached modules later:
 *
 * ```ts
 * const chains = await OTAUpdateManager.getCachedModule('chainRegistry');
 * ```
 */
export class OTAUpdateManager {
  // -------------------------------------------------------------------------
  // Public API
  // -------------------------------------------------------------------------

  /**
   * Check whether a newer SDK version or data modules are available.
   *
   * @param apiKey          Aether API key.
   * @param endpoint        Base URL (e.g. `https://api.aether.network`).
   * @param currentVersion  Current SDK version string.
   * @returns An object indicating whether an update is available.
   */
  static async checkForUpdate(
    apiKey: string,
    endpoint: string,
    currentVersion: string,
  ): Promise<UpdateCheckResult> {
    try {
      const manifest = await OTAUpdateManager.fetchManifest(apiKey, endpoint, currentVersion);

      if (manifest.latestVersion !== currentVersion && manifest.updateUrgency !== 'none') {
        return {
          available: true,
          version: manifest.latestVersion,
          urgency: manifest.updateUrgency,
        };
      }

      // Check if any data modules have newer versions.
      for (const [name, descriptor] of Object.entries(manifest.dataModules)) {
        const cached = await OTAUpdateManager.getCachedModuleVersion(name);
        if (!cached || cached !== descriptor.version) {
          return { available: true, version: manifest.latestVersion, urgency: manifest.updateUrgency };
        }
      }

      return { available: false };
    } catch (error) {
      OTAUpdateManager.log('checkForUpdate failed:', error);
      return { available: false };
    }
  }

  /**
   * Fetch the remote manifest and download any updated data modules.
   * This is the primary entry point — call it fire-and-forget from your provider.
   *
   * @param apiKey          Aether API key.
   * @param endpoint        Base URL.
   * @param currentVersion  Current SDK version.
   */
  static async syncDataModules(
    apiKey: string,
    endpoint: string,
    currentVersion: string,
  ): Promise<void> {
    try {
      const manifest = await OTAUpdateManager.fetchManifest(apiKey, endpoint, currentVersion);

      const moduleEntries = Object.entries(manifest.dataModules);
      const downloadPromises: Promise<void>[] = [];

      for (const [name, descriptor] of moduleEntries) {
        if (!descriptor) continue;

        // Check cached version.
        const cachedVersion = await OTAUpdateManager.getCachedModuleVersion(name);
        if (cachedVersion && cachedVersion === descriptor.version) {
          OTAUpdateManager.log(`Module '${name}' v${cachedVersion} up to date`);
          continue;
        }

        downloadPromises.push(OTAUpdateManager.downloadAndCacheModule(apiKey, name, descriptor));
      }

      if (downloadPromises.length > 0) {
        const results = await Promise.allSettled(downloadPromises);
        const failures = results.filter((r) => r.status === 'rejected');
        if (failures.length > 0) {
          OTAUpdateManager.log(`${failures.length} module download(s) failed`);
        }
      }

      OTAUpdateManager.log('Data module sync complete');
    } catch (error) {
      OTAUpdateManager.log('syncDataModules failed:', error);
      throw error;
    }
  }

  /**
   * Read a previously cached data module from AsyncStorage.
   *
   * @param key Module key, e.g. `"chainRegistry"`.
   * @returns The parsed data, or `null` if not cached.
   */
  static async getCachedModule(key: string): Promise<unknown | null> {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_PREFIX + key);
      if (!raw) return null;

      const cached: CachedModule = JSON.parse(raw);
      return cached.data ?? null;
    } catch {
      return null;
    }
  }

  /**
   * Clear all cached data modules and the manifest from AsyncStorage.
   */
  static async clearCache(): Promise<void> {
    try {
      const allKeys = await AsyncStorage.getAllKeys();
      const aetherKeys = allKeys.filter(
        (k) => k.startsWith(STORAGE_PREFIX) || k === MANIFEST_KEY,
      );
      if (aetherKeys.length > 0) {
        await AsyncStorage.multiRemove(aetherKeys);
      }
      OTAUpdateManager.log('Cache cleared');
    } catch (error) {
      OTAUpdateManager.log('clearCache failed:', error);
    }
  }

  // -------------------------------------------------------------------------
  // Manifest Fetch
  // -------------------------------------------------------------------------

  private static async fetchManifest(
    apiKey: string,
    endpoint: string,
    currentVersion: string,
  ): Promise<SDKManifest> {
    const url = `${endpoint}/sdk/manifests/react-native/latest.json`;
    OTAUpdateManager.log(`Fetching manifest: ${url}`);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${apiKey}`,
          'X-Aether-SDK': 'react-native',
          'X-Aether-Version': currentVersion,
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status} fetching manifest`);
      }

      const manifest: SDKManifest = await response.json();

      // Cache raw manifest.
      try {
        await AsyncStorage.setItem(MANIFEST_KEY, JSON.stringify(manifest));
      } catch {
        // Non-critical — ignore cache failure.
      }

      return manifest;
    } finally {
      clearTimeout(timer);
    }
  }

  // -------------------------------------------------------------------------
  // Module Download
  // -------------------------------------------------------------------------

  private static async downloadAndCacheModule(
    apiKey: string,
    name: string,
    descriptor: DataModuleDescriptor,
  ): Promise<void> {
    OTAUpdateManager.log(`Downloading module '${name}' v${descriptor.version}`);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), MODULE_FETCH_TIMEOUT_MS);

    try {
      const response = await fetch(descriptor.url, {
        method: 'GET',
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${apiKey}`,
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status} downloading module '${name}'`);
      }

      const text = await response.text();

      // Verify SHA-256 hash if available on the platform.
      if (descriptor.hash) {
        const computedHash = await OTAUpdateManager.sha256(text);
        if (computedHash && computedHash !== descriptor.hash) {
          OTAUpdateManager.log(
            `Hash mismatch for '${name}': expected ${descriptor.hash}, got ${computedHash}`,
          );
          return; // Reject update, keep previous cached version.
        }
      }

      // Parse JSON to validate.
      const data = JSON.parse(text);

      // Build cache wrapper.
      const cached: CachedModule = {
        version: descriptor.version,
        data,
        hash: descriptor.hash,
        updatedAt: descriptor.updatedAt,
      };

      await AsyncStorage.setItem(STORAGE_PREFIX + name, JSON.stringify(cached));
      OTAUpdateManager.log(`Cached module '${name}' v${descriptor.version}`);
    } finally {
      clearTimeout(timer);
    }
  }

  // -------------------------------------------------------------------------
  // Cache Helpers
  // -------------------------------------------------------------------------

  private static async getCachedModuleVersion(name: string): Promise<string | null> {
    try {
      const raw = await AsyncStorage.getItem(STORAGE_PREFIX + name);
      if (!raw) return null;
      const cached: CachedModule = JSON.parse(raw);
      return cached.version ?? null;
    } catch {
      return null;
    }
  }

  // -------------------------------------------------------------------------
  // SHA-256
  // -------------------------------------------------------------------------

  /**
   * Compute SHA-256 hex digest. Uses the Web Crypto API if available
   * (React Native Hermes with polyfill, or JSC with expo-crypto).
   * Returns empty string if crypto is not available (non-critical).
   */
  private static async sha256(text: string): Promise<string> {
    try {
      // Try Web Crypto API (available with polyfills like react-native-quick-crypto).
      if (typeof globalThis.crypto?.subtle?.digest === 'function') {
        const encoder = new TextEncoder();
        const data = encoder.encode(text);
        const hashBuffer = await globalThis.crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
      }
    } catch {
      // Fall through — not critical.
    }
    // If crypto not available, return empty string (skip hash check).
    return '';
  }

  // -------------------------------------------------------------------------
  // Logging
  // -------------------------------------------------------------------------

  private static log(...args: unknown[]): void {
    if (__DEV__) {
      console.debug('[Aether OTAUpdateManager]', ...args);
    }
  }
}

export default OTAUpdateManager;
