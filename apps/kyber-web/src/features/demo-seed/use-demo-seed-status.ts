import { useQuery } from '@aether/ui';
import { api, type DemoSeedStatus } from '@kyber/lib/api/endpoints';

export function useDemoSeedStatus(tenantId: string | null) {
  return useQuery<DemoSeedStatus>({
    key: `demo-seed-status:${tenantId ?? 'no-tenant'}`,
    fetcher: () => api.demoSeed.status(tenantId ?? ''),
    enabled: tenantId !== null,
    staleTime: 60_000,
  });
}
