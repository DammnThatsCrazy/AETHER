import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

export function useRevenueIntelligence(window = '30d', entityId?: string) {
  return useQuery({
    key: `intelligence:revenue:${entityId ?? 'tenant'}:${window}`,
    fetcher: () => api.intelligence.revenueIntelligence(entityId, { window }),
    staleTime: STALE,
  });
}
