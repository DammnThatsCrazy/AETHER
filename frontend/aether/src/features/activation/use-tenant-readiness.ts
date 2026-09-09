import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { TenantReadinessResponse } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

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
