import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

const h = vi.hoisted(() => ({ get: vi.fn(), user: { id: 'tenant-a' } as { id: string } | null, keys: [] as string[] }));

vi.mock('@aether-app/lib/api/rest/client', () => ({ restClient: { get: h.get, post: vi.fn(), put: vi.fn() } }));
vi.mock('@aether-app/features/auth', () => ({ useAuth: () => ({ user: h.user }) }));
vi.mock('@aether/ui', async () => {
  const actual = await vi.importActual<typeof import('@aether/ui')>('@aether/ui');
  return {
    ...actual,
    useQuery: (opts: { key: string }) => {
      h.keys.push(opts.key);
      return { data: null, isLoading: false, error: null, refetch: vi.fn() };
    },
  };
});

import { fetchAllTenantApiKeys, useOrganizationProfile, useTenantApiKeys } from '@aether-app/features/onboarding/use-workspace-setup';

const page = (ids: string[], total: number) => ({
  data: { api_keys: ids.map(id => ({ id, name: `key ${id}` })), total },
  status: 'success',
  timestamp: 't',
});

describe('fetchAllTenantApiKeys', () => {
  beforeEach(() => h.get.mockReset());

  it('reads every page so absence from the first page is never taken as "no key"', async () => {
    const first = Array.from({ length: 100 }, (_, i) => `k${i}`);
    h.get.mockResolvedValueOnce(page(first, 101)).mockResolvedValueOnce(page(['k100'], 101));
    const { api_keys } = await fetchAllTenantApiKeys();
    expect(api_keys).toHaveLength(101);
    expect(api_keys[100]).toEqual({ id: 'k100', name: 'key k100', platform: null });
    expect(h.get.mock.calls.map(c => c[0])).toEqual([
      '/v1/me/api-keys?limit=100&offset=0',
      '/v1/me/api-keys?limit=100&offset=100',
    ]);
  });
});

describe('onboarding query keys', () => {
  it('are scoped to the authenticated principal', () => {
    h.keys = [];
    h.user = { id: 'tenant-a' };
    renderHook(() => { useOrganizationProfile(); useTenantApiKeys(); });
    h.user = { id: 'tenant-b' };
    renderHook(() => { useOrganizationProfile(); useTenantApiKeys(); });
    expect(h.keys).toEqual([
      'onboarding:organization:tenant-a',
      'onboarding:api-keys:tenant-a',
      'onboarding:organization:tenant-b',
      'onboarding:api-keys:tenant-b',
    ]);
  });
});
