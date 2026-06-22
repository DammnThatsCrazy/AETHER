import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

export function useEntityDataQuality(entityId: string) {
  return useQuery({
    key: `profile:data-quality:${entityId}`,
    fetcher: () => api.profile.dataQuality(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}
