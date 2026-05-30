/**
 * Entity intelligence hooks — typed wrappers for /v1/entities/profile,
 * /v1/entities/timeline/query, and /v1/entities/relationships/query.
 *
 * These complement use-entity-graph.ts (which fetches raw graph topology)
 * with intelligence-layer endpoints: dimension scoring, timeline events,
 * and scored relationship edges.
 */
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

// Entity profile with intelligence dimensions
export function useEntityProfile(params: {
  tenantId: string;
  entityId: string;
  entityKind: string;
  dimensions?: string[];
} | null) {
  return useQuery({
    key: params
      ? `entity-intel:profile:${params.tenantId}:${params.entityId}:${(params.dimensions ?? []).join(',')}`
      : '',
    fetcher: () =>
      api.entityIntelligence.profile({
        tenantId: params!.tenantId,
        entity: { kind: params!.entityKind, id: params!.entityId },
        ...(params?.dimensions !== undefined && { dimensions: params.dimensions }),
      }),
    staleTime: STALE,
    enabled: !!params,
  });
}

// Entity event timeline (paginated, cursor-based)
export function useEntityTimeline(params: {
  tenantId: string;
  entityId: string;
  entityKind: string;
  fromTime?: string;
  toTime?: string;
  limit?: number;
  cursor?: string;
} | null) {
  return useQuery({
    key: params
      ? `entity-intel:timeline:${params.tenantId}:${params.entityId}:${params.cursor ?? ''}:${params.fromTime ?? ''}:${params.toTime ?? ''}`
      : '',
    fetcher: () =>
      api.entityIntelligence.timeline({
        tenantId: params!.tenantId,
        entity: { kind: params!.entityKind, id: params!.entityId },
        ...(params?.fromTime !== undefined && { fromTime: params.fromTime }),
        ...(params?.toTime !== undefined && { toTime: params.toTime }),
        ...(params?.limit !== undefined && { limit: params.limit }),
        ...(params?.cursor !== undefined && { cursor: params.cursor }),
      }),
    staleTime: STALE,
    enabled: !!params,
  });
}

// Scored relationship edges for an entity
export function useEntityRelationshipGraph(params: {
  tenantId: string;
  entityId: string;
  entityKind: string;
  depth?: number;
  minScore?: number;
  limit?: number;
  cursor?: string;
} | null) {
  return useQuery({
    key: params
      ? `entity-intel:relationships:${params.tenantId}:${params.entityId}:${params.depth ?? 1}:${params.minScore ?? ''}:${params.cursor ?? ''}`
      : '',
    fetcher: () =>
      api.entityIntelligence.relationships({
        tenantId: params!.tenantId,
        entity: { kind: params!.entityKind, id: params!.entityId },
        ...(params?.depth !== undefined && { depth: params.depth }),
        ...(params?.minScore !== undefined && { minScore: params.minScore }),
        ...(params?.limit !== undefined && { limit: params.limit }),
        ...(params?.cursor !== undefined && { cursor: params.cursor }),
      }),
    staleTime: STALE,
    enabled: !!params,
  });
}

// Imperative entity profile fetch (for manual refresh or on-demand load)
export function useEntityProfileMutation() {
  return useMutation({
    mutationFn: (input: {
      tenantId: string;
      entityId: string;
      entityKind: string;
      dimensions?: string[];
    }) =>
      api.entityIntelligence.profile({
        tenantId: input.tenantId,
        entity: { kind: input.entityKind, id: input.entityId },
        ...(input.dimensions !== undefined && { dimensions: input.dimensions }),
      }),
  });
}
