/**
 * Graph health and four-layer observability hooks for Kyber operator dashboard.
 *
 * Exposes per-layer metrics (H2H, H2A, A2H, A2A), mutation health, and
 * backend mode (neptune/local/staging/degraded).
 *
 * Tenant-specific views are scoped by tenantId.
 * Global/operator views require operator permission (enforced server-side).
 */
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import type { RelationshipLayer } from '@aether/shared';

export const GRAPH_LAYERS: readonly RelationshipLayer[] = ['H2H', 'H2A', 'A2H', 'A2A'];
const STALE = 30_000;

export interface GraphLayerCount {
  H2H: number;
  H2A: number;
  A2H: number;
  A2A: number;
}

export interface GraphHealthData {
  status: 'healthy' | 'no_data' | 'degraded' | 'dependency_unavailable';
  backend_mode: 'neptune' | 'local' | 'staging';
  node_count: number;
  edge_count: number;
  layer_counts: GraphLayerCount;
  layers_with_data: RelationshipLayer[];
  all_four_layers_present: boolean;
  relationship_layers: RelationshipLayer[];
  computed_at: string;
}

/** Graph health for a specific tenant (operator-scoped). */
export function useGraphHealth(tenantId: string | null) {
  return useQuery({
    key: tenantId ? `graph-health:${tenantId}` : '',
    fetcher: () => api.graph.health(tenantId!) as Promise<GraphHealthData>,
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

/** Graph contracts — layer listing and route surface. */
export function useGraphContracts() {
  return useQuery({
    key: 'graph-contracts',
    fetcher: () =>
      api.graph.contracts() as Promise<{
        data: {
          version: string;
          routes: string[];
          status: string;
          relationship_layers: RelationshipLayer[];
          layer_count: number;
        };
      }>,
    staleTime: 300_000,
  });
}

/** Layer coverage overlay for a tenant. */
export function useGraphLayerCoverage(params: {
  tenantId: string;
  limit?: number;
} | null) {
  return useQuery({
    key: params ? `graph-layer-coverage:${params.tenantId}:${params.limit ?? 1000}` : '',
    fetcher: () =>
      api.graphIntelligence.overlay({
        tenantId: params!.tenantId,
        overlays: ['layer_coverage'],
        ...(params?.limit !== undefined && { limit: params.limit }),
      }),
    staleTime: STALE,
    enabled: !!params,
  });
}

/** Check whether all four layers are present in a tenant's graph. */
export function useGraphFourLayerPresence(tenantId: string | null) {
  const health = useGraphHealth(tenantId);
  const allPresent = health.data?.all_four_layers_present ?? false;
  const missingLayers = GRAPH_LAYERS.filter(
    (l) => !(health.data?.layers_with_data ?? []).includes(l),
  );

  return {
    ...health,
    allPresent,
    missingLayers,
    layerCounts: health.data?.layer_counts ?? { H2H: 0, H2A: 0, A2H: 0, A2A: 0 },
  };
}
