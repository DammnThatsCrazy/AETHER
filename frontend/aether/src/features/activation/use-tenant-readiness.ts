import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

/**
 * Minimal consumer of the tenant launch-readiness surface
 * (GET /v1/tenant/readiness + /v1/tenant/readiness/trust-states).
 *
 * Both endpoints are tenant-scoped and require the "read" permission; the
 * backend returns an all-pending checklist until a snapshot is recorded, so a
 * tenant that has never self-served still sees the full gate set.
 */
export function useTenantReadiness() {
  return useQuery({
    key: 'tenant:readiness',
    fetcher: () => api.readiness.snapshot(),
    staleTime: STALE,
  });
}

export function useTenantTrustStates() {
  return useQuery({
    key: 'tenant:readiness:trust-states',
    fetcher: () => api.readiness.trustStates(),
    staleTime: STALE,
  });
}
