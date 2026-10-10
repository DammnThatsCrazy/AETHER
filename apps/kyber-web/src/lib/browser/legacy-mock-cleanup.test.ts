import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanupLegacyMockWorker } from './legacy-mock-cleanup';

const legacyStorageKeys = [
  'mock_access_token',
  'mock_refresh_token',
  'kyber_mock_auth',
  'kyber_mock_user',
  'kyber_mock_tenant',
  'kyber_mock_api_key',
  'kyber_mock_query_cache',
];

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe('cleanupLegacyMockWorker', () => {
  it('removes only the exact legacy worker, cache names, and mock storage keys', async () => {
    const unregisterLegacy = vi.fn().mockResolvedValue(true);
    const unregisterUnrelated = vi.fn().mockResolvedValue(true);
    const deleteCache = vi.fn().mockResolvedValue(true);

    vi.stubGlobal('navigator', {
      serviceWorker: {
        getRegistrations: vi.fn().mockResolvedValue([
          {
            active: { scriptURL: 'https://kyber.example/mockServiceWorker.js' },
            unregister: unregisterLegacy,
          },
          {
            active: { scriptURL: 'https://kyber.example/app-service-worker.js' },
            unregister: unregisterUnrelated,
          },
        ]),
      },
    });
    vi.stubGlobal('caches', {
      keys: vi.fn().mockResolvedValue(['mock', 'msw', 'mock-images', 'msw-assets', 'app-cache']),
      delete: deleteCache,
    });

    for (const key of legacyStorageKeys) {
      localStorage.setItem(key, 'legacy');
      sessionStorage.setItem(key, 'legacy');
    }
    localStorage.setItem('kyber-theme', 'dark');
    localStorage.setItem('kyber-timezone', 'America/New_York');
    localStorage.setItem('access_token', 'real-credential');
    sessionStorage.setItem('kyber_pkce_verifier', 'real-pkce-verifier');

    await cleanupLegacyMockWorker();

    expect(unregisterLegacy).toHaveBeenCalledOnce();
    expect(unregisterUnrelated).not.toHaveBeenCalled();
    expect(deleteCache.mock.calls.map(([name]) => name)).toEqual(['mock', 'msw']);
    for (const key of legacyStorageKeys) {
      expect(localStorage.getItem(key)).toBeNull();
      expect(sessionStorage.getItem(key)).toBeNull();
    }
    expect(localStorage.getItem('kyber-theme')).toBe('dark');
    expect(localStorage.getItem('kyber-timezone')).toBe('America/New_York');
    expect(localStorage.getItem('access_token')).toBe('real-credential');
    expect(sessionStorage.getItem('kyber_pkce_verifier')).toBe('real-pkce-verifier');
  });

  it('is idempotent and recognizes a waiting legacy worker with a query string', async () => {
    const unregister = vi.fn().mockResolvedValue(true);
    const getRegistrations = vi.fn()
      .mockResolvedValueOnce([
        {
          waiting: { scriptURL: '/mockServiceWorker.js?migration=1' },
          unregister,
        },
      ])
      .mockResolvedValueOnce([]);
    const deleteCache = vi.fn().mockResolvedValue(true);

    vi.stubGlobal('navigator', { serviceWorker: { getRegistrations } });
    vi.stubGlobal('caches', {
      keys: vi.fn().mockResolvedValueOnce(['MSW']).mockResolvedValueOnce([]),
      delete: deleteCache,
    });

    await cleanupLegacyMockWorker();
    await cleanupLegacyMockWorker();

    expect(unregister).toHaveBeenCalledOnce();
    expect(deleteCache).toHaveBeenCalledOnce();
    expect(deleteCache).toHaveBeenCalledWith('MSW');
  });
});
