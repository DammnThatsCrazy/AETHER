import { useEffect, useRef } from 'react';
import { useQuery, queryCache } from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';
import { useGraphContext } from '@aether/ui/exploration';
import { api } from '@aether-app/lib/api/endpoints';
import type { TenantReadinessResponse } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

/**
 * Readiness is a tenant/session response, not a process-global singleton.
 * Encoding both authorities into the cache key prevents a logout, account
 * switch, or tenant change from reusing another authenticated session's
 * checklist. The session coordinate is the authenticated principal exposed by
 * AuthProvider; credentials themselves never enter a cache key.
 */
export function tenantReadinessQueryKey(
  kind: 'snapshot' | 'trust-states',
  tenantId: string,
  sessionScope: string,
): string {
  return [
    'tenant:readiness',
    kind,
    encodeURIComponent(tenantId),
    encodeURIComponent(sessionScope),
  ].join(':');
}

export const GRAPH_READINESS_CHECKS = [
  'events_received',
  'identity_resolution_verified',
  'graph_projection_verified',
  'profile360_verified',
  'data_quality_verified',
] as const;

export type GraphReadinessCheck = (typeof GRAPH_READINESS_CHECKS)[number];
export type GraphReadinessState = 'no_data' | 'building' | 'ready';

export interface GraphReadiness {
  readonly state: GraphReadinessState;
  /** Named checks that currently prevent graph maturity from being ready. */
  readonly blocking: readonly GraphReadinessCheck[];
}

/**
 * Derive the smallest honest UI state from the server-owned readiness checks.
 * This is intentionally categorical: no client-computed score or substitute
 * readiness vocabulary is introduced.
 */
export function deriveGraphMaturity(
  readiness: TenantReadinessResponse,
): GraphReadiness {
  const statuses = new Map(readiness.checks.map((check) => [check.name, check.status]));
  const blocking = GRAPH_READINESS_CHECKS.filter((name) => statuses.get(name) !== 'passed' && statuses.get(name) !== 'not_applicable');

  if (statuses.get('events_received') !== 'passed' && statuses.get('events_received') !== 'not_applicable') {
    return { state: 'no_data', blocking };
  }
  return blocking.length === 0
    ? { state: 'ready', blocking: [] }
    : { state: 'building', blocking };
}

/**
 * Minimal consumer of the tenant launch-readiness surface
 * (GET /v1/tenant/readiness + /v1/tenant/readiness/trust-states).
 *
 * Both endpoints are tenant-scoped and require the "read" permission; the
 * backend returns an all-pending checklist until a snapshot is recorded, so a
 * tenant that has never self-served still sees the full gate set.
 */
function useScopedReadinessQuery<T>(
  kind: 'snapshot' | 'trust-states',
  fetcher: () => Promise<T>,
) {
  const { isAuthenticated, user } = useAuth();
  const context = useGraphContext();
  const tenantId = context.scope.tenant_id;
  const sessionScope = user?.id ?? 'anonymous';
  const key = tenantReadinessQueryKey(kind, tenantId, sessionScope);
  const enabled = isAuthenticated && Boolean(tenantId) && Boolean(user?.id);
  const previousKey = useRef<string | null>(null);

  // Drop the prior identity's cached response when auth scope changes. The
  // new key already isolates the replacement request; invalidating the old
  // key also avoids retaining tenant readiness data after logout/switch.
  useEffect(() => {
    if (previousKey.current !== null && previousKey.current !== key) {
      queryCache.invalidate(previousKey.current);
    }
    previousKey.current = key;
  }, [key]);

  return useQuery({ key, fetcher, staleTime: STALE, enabled });
}

export function useTenantReadiness() {
  return useScopedReadinessQuery('snapshot', () => api.readiness.snapshot());
}

export function useTenantTrustStates() {
  return useScopedReadinessQuery('trust-states', () => api.readiness.trustStates());
}
