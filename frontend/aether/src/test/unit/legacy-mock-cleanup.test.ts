import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanupLegacyMockWorker } from '@aether-app/lib/browser/legacy-mock-cleanup';

const originalServiceWorker = Object.getOwnPropertyDescriptor(navigator, 'serviceWorker');
const originalCaches = Object.getOwnPropertyDescriptor(globalThis, 'caches');

function registration(
  scriptURL: string,
  state: 'active' | 'waiting' | 'installing' = 'active',
) {
  const unregister = vi.fn().mockResolvedValue(true);
  return {
    value: {
      active: state === 'active' ? { scriptURL } : null,
      waiting: state === 'waiting' ? { scriptURL } : null,
      installing: state === 'installing' ? { scriptURL } : null,
      unregister,
    } as unknown as ServiceWorkerRegistration,
    unregister,
  };
}

describe('cleanupLegacyMockWorker', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    if (originalServiceWorker) {
      Object.defineProperty(navigator, 'serviceWorker', originalServiceWorker);
    } else {
      Reflect.deleteProperty(navigator, 'serviceWorker');
    }
    if (originalCaches) {
      Object.defineProperty(globalThis, 'caches', originalCaches);
    } else {
      Reflect.deleteProperty(globalThis, 'caches');
    }
    vi.restoreAllMocks();
  });

  it('unregisters only the legacy worker, including waiting workers and query strings', async () => {
    const legacy = registration('https://app.example.test/mockServiceWorker.js?legacy=1', 'waiting');
    const unrelated = registration('https://app.example.test/service-worker.js');
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: {
        getRegistrations: vi.fn().mockResolvedValue([legacy.value, unrelated.value]),
      },
    });

    await cleanupLegacyMockWorker();

    expect(legacy.unregister).toHaveBeenCalledOnce();
    expect(unrelated.unregister).not.toHaveBeenCalled();
  });

  it('deletes only exact legacy MSW cache names', async () => {
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: vi.fn().mockResolvedValue([]) },
    });
    const deleteCache = vi.fn().mockResolvedValue(true);
    Object.defineProperty(globalThis, 'caches', {
      configurable: true,
      value: {
        keys: vi.fn().mockResolvedValue([
          'aether-msw-cache',
          'MSW',
          'msw-analytics',
          'mock-data',
          'aether-app-shell',
        ]),
        delete: deleteCache,
      },
    });

    await cleanupLegacyMockWorker();

    expect(deleteCache).toHaveBeenCalledTimes(2);
    expect(deleteCache).toHaveBeenCalledWith('aether-msw-cache');
    expect(deleteCache).toHaveBeenCalledWith('MSW');
    expect(deleteCache).not.toHaveBeenCalledWith('msw-analytics');
    expect(deleteCache).not.toHaveBeenCalledWith('mock-data');
    expect(deleteCache).not.toHaveBeenCalledWith('aether-app-shell');
  });

  it('purges known mock state while preserving real credentials and preferences', async () => {
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: vi.fn().mockResolvedValue([]) },
    });
    localStorage.setItem('aether_mock_tenant_id', 'tenant_demo_001');
    localStorage.setItem('aether-theme', 'dark');
    localStorage.setItem('aether-timezone', 'America/New_York');
    localStorage.setItem('unrelated', 'keep-me');
    sessionStorage.setItem('aether_session_key', 'ak_real_backend_key');
    sessionStorage.setItem('aether_session_token', 'mock_access_token');
    sessionStorage.setItem('aether_session_expires_at', '2099-01-01T00:00:00.000Z');
    sessionStorage.setItem('aether_mock_query_cache', '{"synthetic":true}');

    await cleanupLegacyMockWorker();

    expect(localStorage.getItem('aether_mock_tenant_id')).toBeNull();
    expect(sessionStorage.getItem('aether_mock_query_cache')).toBeNull();
    expect(sessionStorage.getItem('aether_session_token')).toBeNull();
    expect(sessionStorage.getItem('aether_session_expires_at')).toBeNull();
    expect(sessionStorage.getItem('aether_session_key')).toBe('ak_real_backend_key');
    expect(localStorage.getItem('aether-theme')).toBe('dark');
    expect(localStorage.getItem('aether-timezone')).toBe('America/New_York');
    expect(localStorage.getItem('unrelated')).toBe('keep-me');
  });

  it('is idempotent', async () => {
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: vi.fn().mockResolvedValue([]) },
    });
    const deleteCache = vi.fn().mockResolvedValue(true);
    Object.defineProperty(globalThis, 'caches', {
      configurable: true,
      value: {
        keys: vi.fn().mockResolvedValue([]),
        delete: deleteCache,
      },
    });
    sessionStorage.setItem('aether_session_key', 'ak_mock_login_key');

    await cleanupLegacyMockWorker();
    await cleanupLegacyMockWorker();

    expect(sessionStorage.getItem('aether_session_key')).toBeNull();
    expect(deleteCache).not.toHaveBeenCalled();
  });
});
