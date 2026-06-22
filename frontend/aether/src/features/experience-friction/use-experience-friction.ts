import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

export function useExperienceFriction(entityId?: string, window = '30d') {
  return useQuery({
    key: `intelligence:experience:${entityId ?? 'tenant'}:${window}`,
    fetcher: () => api.intelligence.experienceIntelligence(entityId, { window }),
    staleTime: STALE,
  });
}
