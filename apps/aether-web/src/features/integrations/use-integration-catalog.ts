import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 30_000;

/** Derived one-customer catalog — every connectable manifest, experience-grouped. */
export function useIntegrationCatalog() {
  return useQuery({
    key: 'integration-catalog:list',
    fetcher: () => api.integrationCatalog.list(),
    staleTime: STALE,
  });
}

/** Catalog-level readiness matrix over the canonical CredentialReadiness ladder. */
export function useIntegrationReadiness() {
  return useQuery({
    key: 'integration-catalog:readiness',
    fetcher: () => api.integrationCatalog.readiness(),
    staleTime: STALE,
  });
}
