import { useQuery } from '@aether/ui';
import { api, type DemoSeedStatus } from '@aether-app/lib/api/endpoints';

export function useDemoSeedStatus() {
  return useQuery<DemoSeedStatus>({
    key: 'demo-seed-status:current-tenant',
    fetcher: api.demoSeed.status,
    staleTime: 60_000,
  });
}
