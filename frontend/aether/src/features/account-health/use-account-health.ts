import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

export function useAccountHealth(entityId?: string, window = '30d') {
  return useQuery({
    key: `intelligence:account-health:${entityId ?? 'tenant'}:${window}`,
    fetcher: () => api.intelligence.accountHealth(entityId, { window }),
    staleTime: STALE,
  });
}
