import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useGeoSummary(params?: { level?: string; geo_id?: string; window?: string }) {
  const cacheKey = `geo:summary:${params?.level ?? 'global'}:${params?.geo_id ?? ''}:${params?.window ?? '30d'}`;
  return useQuery({
    key: cacheKey,
    fetcher: () => api.geo.summary(params).catch(() => null),
    staleTime: STALE,
  });
}

export function useGeoEntities(params: { level: string; geo_id: string; window?: string; limit?: number; offset?: number }) {
  const cacheKey = `geo:entities:${params.level}:${params.geo_id}:${params.window ?? '30d'}:${params.offset ?? 0}`;
  return useQuery({
    key: cacheKey,
    fetcher: () => api.geo.entities(params).catch(() => null),
    staleTime: STALE,
  });
}
