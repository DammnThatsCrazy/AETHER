import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useEntitiesList(params?: { type?: string; limit?: number; offset?: number }) {
  const key = `entities:list:${params?.type ?? ''}:${params?.limit ?? ''}:${params?.offset ?? ''}`;
  return useQuery({
    key,
    fetcher: () => api.entities.list(params),
    staleTime: STALE,
  });
}

export function useEntity(entityId: string) {
  return useQuery({
    key: `entities:get:${entityId}`,
    fetcher: () => api.entities.get(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useEntityGraph(entityId: string) {
  return useQuery({
    key: `entities:graph:${entityId}`,
    fetcher: () => api.entities.getGraph(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useEntitySearch(query: string, type?: string, limit = 20) {
  return useQuery({
    key: `entities:search:${query}:${type ?? ''}:${limit}`,
    fetcher: () => api.entities.search(query, type, limit),
    staleTime: STALE,
    enabled: query.length > 1,
  });
}
