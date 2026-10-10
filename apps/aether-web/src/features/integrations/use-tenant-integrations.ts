import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 30_000;

/** The tenant's configured integrations (connection facts, not readiness claims). */
export function useTenantIntegrations() {
  return useQuery({
    key: 'tenant-integrations:list',
    fetcher: () => api.integrationCatalog.tenantIntegrations(),
    staleTime: STALE,
  });
}

/** One tenant integration (404 unless the tenant has a stored record for it). */
export function useTenantIntegration(integrationId: string) {
  return useQuery({
    key: `tenant-integrations:${integrationId}`,
    fetcher: () => api.integrationCatalog.tenantIntegration(integrationId),
    staleTime: STALE,
    enabled: !!integrationId,
  });
}
