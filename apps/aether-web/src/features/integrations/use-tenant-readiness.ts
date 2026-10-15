import { useQuery } from '@aether/ui';
import { restClient } from '@aether-app/lib/api/rest/client';
import { z } from 'zod';
import {
  tenantReadinessResponseSchema,
  type TenantReadinessItem,
  type TenantReadinessResponse,
} from './types';

const STALE = 30_000;

/**
 * Transport envelope mirror ({data,status,timestamp}) — the FE endpoint layer
 * (lib/api/endpoints) validates this same shape; restClient is used directly
 * here so the WS-4 joined graph stays additive inside features/integrations and
 * does not require touching the shared endpoint map.
 */
const tenantReadinessEnvelopeSchema = z.object({
  data: tenantReadinessResponseSchema,
  status: z.string(),
  timestamp: z.string(),
});

/** Optional server-side filters mirroring the route query params. */
export interface TenantReadinessQuery {
  experienceCategory?: string;
  state?: string;
}

function fetchTenantReadiness(
  q: TenantReadinessQuery = {},
): Promise<TenantReadinessResponse> {
  const params = new URLSearchParams();
  if (q.experienceCategory) params.set('experience_category', q.experienceCategory);
  if (q.state) params.set('state', q.state);
  const qs = params.toString();
  return restClient
    .get(
      `/v1/tenant/integration-readiness${qs ? `?${qs}` : ''}`,
      tenantReadinessEnvelopeSchema,
    )
    .then((r) => r.data);
}

/**
 * The tenant-contextual *integration* readiness graph (joined, WS-4).
 *
 * Distinct from features/activation' launch-readiness ``useTenantReadiness``:
 * this is the integrations surface — one item per connectable catalog manifest
 * joined with the tenant's stored connection record facts. Honesty contract
 * (see the backend projection):
 *   - ``readiness`` is ALWAYS the manifest's catalog baseline — a healthy
 *     connection can never raise it (Connected ≠ Ready).
 *   - ``connection.connected`` is a record fact, never a readiness claim.
 *   - ``tenant_state`` is an evidence-derived connection/attention label
 *     (available / connected / ready / connection_disabled / needs_attention)
 *     and is NOT a capability-readiness word.
 *   - ``ready`` is only ever present when BOTH the provider catalog is
 *     sandbox-validated or better AND the tenant connection is currently
 *     healthy.
 */
export function useTenantIntegrationReadiness(query?: TenantReadinessQuery) {
  const q = query ?? {};
  const key = [
    'tenant-integration-readiness',
    'list',
    q.experienceCategory ?? '*',
    q.state ?? '*',
  ].join(':');
  return useQuery({
    key,
    fetcher: () => fetchTenantReadiness(q),
    staleTime: STALE,
  });
}

/**
 * One tenant-contextual readiness item (server coverage is whole, so the item
 * is found by family rather than by a separate fetch). Returns undefined while
 * loading and when the family has no item in the projection.
 */
export function selectTenantReadinessItem(
  items: TenantReadinessItem[] | undefined,
  family: string,
): TenantReadinessItem | undefined {
  return items?.find((i) => i.family === family);
}
