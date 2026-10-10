import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useInteropProviders() {
  return useQuery({
    key: 'interop:providers',
    fetcher: () => api.interop.providers(),
    staleTime: STALE,
  });
}

export function useInteropMessages(params?: { status?: string; provider_id?: string; path_id?: string; limit?: number }) {
  return useQuery({
    key: `interop:messages:${params?.status ?? 'all'}:${params?.provider_id ?? 'all'}:${params?.path_id ?? 'all'}:${params?.limit ?? 50}`,
    fetcher: () => api.interop.messages({ limit: 50, ...params }),
    staleTime: 30_000,
  });
}

export function useInteropMessageDetail(interopMessageId: string) {
  return useQuery({
    key: `interop:message:${interopMessageId}`,
    fetcher: () => api.interop.messageDetail(interopMessageId),
    staleTime: 30_000,
    enabled: !!interopMessageId,
  });
}

export function useInteropPaths() {
  return useQuery({
    key: 'interop:paths',
    fetcher: () => api.interop.paths(),
    staleTime: STALE,
  });
}

export function useInteropSecurityPolicies(pathId?: string) {
  return useQuery({
    key: `interop:security-policies:${pathId ?? 'all'}`,
    fetcher: () => api.interop.securityPolicies(pathId ? { path_id: pathId } : undefined),
    staleTime: STALE,
  });
}
