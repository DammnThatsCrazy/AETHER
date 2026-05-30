import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useBehaviorLatest(entityId: string) {
  return useQuery({
    key: `behavior:latest:${entityId}`,
    fetcher: () => api.behavior.latest(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useBehaviorHistory(entityId: string, params?: { window?: string; limit?: number }) {
  return useQuery({
    key: `behavior:history:${entityId}:${params?.window ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.behavior.history(entityId, params),
    staleTime: STALE,
    enabled: !!entityId,
  });
}
