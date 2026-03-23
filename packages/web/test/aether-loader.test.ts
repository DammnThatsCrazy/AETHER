import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AetherLoader } from '../src/loader/aether-loader';

const storage = new Map<string, string>();

describe('AetherLoader', () => {
  const originalFetch = globalThis.fetch;
  const originalLocalStorage = globalThis.localStorage;
  const originalAether = (globalThis as typeof globalThis & { Aether?: unknown }).Aether;

  beforeEach(() => {
    storage.clear();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => storage.get(key) ?? null),
        setItem: vi.fn((key: string, value: string) => storage.set(key, value)),
        removeItem: vi.fn((key: string) => storage.delete(key)),
      },
    });
    AetherLoader.clearCache();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: originalLocalStorage,
    });
    if (originalAether === undefined) {
      delete (globalThis as typeof globalThis & { Aether?: unknown }).Aether;
    } else {
      (globalThis as typeof globalThis & { Aether?: unknown }).Aether = originalAether;
    }
    AetherLoader.clearCache();
  });

  it('falls back to a cached bundle when manifest fetch fails', async () => {
    storage.set('_aether_loader_bundle', JSON.stringify({
      version: '8.3.1',
      code: 'globalThis.Aether = { default: { init: () => "cached" } };',
      timestamp: Date.now() - 7_200_000,
      hash: '',
    }));
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network unavailable')) as typeof fetch;

    const sdk = await AetherLoader.load();

    expect((sdk as { init: () => string }).init()).toBe('cached');
    expect(globalThis.fetch).toHaveBeenCalledOnce();
    expect(AetherLoader.getLoadedVersion()).toBe('8.3.1');
  });

  it('deduplicates concurrent load requests and caches the resolved bundle', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        text: async () => JSON.stringify({
          latestVersion: '8.3.1',
          minimumVersion: '8.3.0',
          updateUrgency: 'none',
          downloads: {
            sdkBundleUrl: 'https://cdn.aether.network/sdk/8.3.1/aether.umd.js',
            sdkBundleHash: '',
            sdkBundleSize: 128,
          },
          checkIntervalMs: 60_000,
          generatedAt: '2026-03-22T00:00:00Z',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        text: async () => 'globalThis.Aether = { default: { init: () => "network" } };',
      });
    globalThis.fetch = fetchMock as typeof fetch;

    const [sdkA, sdkB] = await Promise.all([AetherLoader.load(), AetherLoader.load()]);

    expect(sdkA).toBe(sdkB);
    expect((sdkA as { init: () => string }).init()).toBe('network');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(AetherLoader.getLoadedVersion()).toBe('8.3.1');
  });
});
