/**
 * Aether Profile360 hooks — generic entity lookup by type + id.
 *
 * Unlike api.profile.* (which is user-scoped), Profile360 works for ANY
 * entity type: user, agent, wallet, device, session, contract, protocol,
 * journey, delegation, transaction, payment, reward, campaign, execution_trace.
 *
 * The backend returns identity + all requested sub_resources in a single call.
 * Use the sub-resource hooks for individual slices when you don't need the full payload.
 */
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import type { Profile360EntityType } from '@aether/shared';

const STALE = 60_000;

function key(entityType: string, entityId: string, suffix = 'full') {
  return `profile360:${entityType}:${entityId}:${suffix}`;
}

/** Full Profile360 payload — identity + all sub_resources for any entity type. */
export function useProfile360(entityType: Profile360EntityType, entityId: string) {
  return useQuery({
    key: key(entityType, entityId),
    fetcher: () => api.profile360.full(entityType, entityId),
    staleTime: STALE,
    enabled: !!(entityType && entityId),
  });
}

/** Graph neighbourhood for any entity — nodes and edges across all interaction classes. */
export function useProfile360Graph(
  entityType: Profile360EntityType,
  entityId: string,
  params?: { cursor?: string; limit?: number },
) {
  return useQuery({
    key: key(entityType, entityId, `graph:${params?.cursor ?? ''}:${params?.limit ?? ''}`),
    fetcher: () => api.profile360.graph(entityType, entityId, params),
    staleTime: STALE,
    enabled: !!(entityType && entityId),
  });
}

/** Chronological event timeline for any entity. */
export function useProfile360Timeline(
  entityType: Profile360EntityType,
  entityId: string,
  params?: { cursor?: string; limit?: number; type?: string },
) {
  return useQuery({
    key: key(entityType, entityId, `timeline:${params?.type ?? ''}:${params?.limit ?? ''}`),
    fetcher: () => api.profile360.timeline(entityType, entityId, params),
    staleTime: STALE,
    enabled: !!(entityType && entityId),
  });
}
