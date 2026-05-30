import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

export function useProviderKeys() {
  return useQuery({
    key: 'providers:keys',
    fetcher: () => api.providers.listKeys(),
    staleTime: STALE,
  });
}

export function useProviderCategories() {
  return useQuery({
    key: 'providers:categories',
    fetcher: () => api.providers.categories(),
    staleTime: STALE,
  });
}

export function useProviderUsage(params?: { category?: string; provider_name?: string }) {
  return useQuery({
    key: `providers:usage:${params?.category ?? ''}:${params?.provider_name ?? ''}`,
    fetcher: () => api.providers.usage(params),
    staleTime: STALE,
  });
}

export function useProviderUsageSummary() {
  return useQuery({
    key: 'providers:usage-summary',
    fetcher: () => api.providers.usageSummary(),
    staleTime: STALE,
  });
}

export function useProviderHealth() {
  return useQuery({
    key: 'providers:health',
    fetcher: () => api.providers.health(),
    staleTime: STALE,
  });
}

export function useStoreProviderKey() {
  return useMutation({
    mutationFn: (key: { provider_name: string; api_key: string; endpoint?: string }) =>
      api.providers.storeKey(key),
  });
}

export function useDeleteProviderKey() {
  return useMutation({
    mutationFn: (provider: string) => api.providers.deleteKey(provider),
  });
}

export function useTestProvider() {
  return useMutation({
    mutationFn: (params: { category: string; method: string; params: Record<string, unknown>; preferred_provider?: string }) =>
      api.providers.test(params),
  });
}
