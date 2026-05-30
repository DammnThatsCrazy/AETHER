/**
 * Graph intelligence hooks — typed wrappers for /v1/graph/* traversal routes.
 *
 * These use the new GraphTraversalEngine-backed routes (PR #111):
 *   - BFS traversal from a start node
 *   - Shortest path between two nodes
 *   - Temporal graph reconstruction (edges at or before asOf)
 *   - Graph overlay application
 *   - Graph filter
 */
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

// BFS neighbourhood traversal
export function useGraphTraversal(params: {
  tenantId: string;
  startId: string;
  startKind: string;
  depth?: number;
  direction?: 'in' | 'out' | 'both';
  limit?: number;
} | null) {
  return useQuery({
    key: params
      ? `graph-intel:traverse:${params.tenantId}:${params.startId}:${params.depth ?? 2}:${params.direction ?? 'both'}`
      : '',
    fetcher: () =>
      api.graphIntelligence.traverse({
        tenantId: params!.tenantId,
        start: { kind: params!.startKind, id: params!.startId },
        depth: params?.depth ?? 2,
        direction: params?.direction ?? 'both',
        ...(params?.limit !== undefined && { limit: params.limit }),
      }),
    staleTime: STALE,
    enabled: !!params,
  });
}

// Shortest path between two nodes
export function useShortestPath(params: {
  tenantId: string;
  fromId: string;
  fromKind: string;
  toId: string;
  toKind: string;
  maxDepth?: number;
} | null) {
  return useQuery({
    key: params
      ? `graph-intel:path:${params.tenantId}:${params.fromId}:${params.toId}:${params.maxDepth ?? 6}`
      : '',
    fetcher: () =>
      api.graphIntelligence.path({
        tenantId: params!.tenantId,
        from: { kind: params!.fromKind, id: params!.fromId },
        to: { kind: params!.toKind, id: params!.toId },
        ...(params?.maxDepth !== undefined && { maxDepth: params.maxDepth }),
      }),
    staleTime: STALE,
    enabled: !!params,
  });
}

// Temporal graph — reconstruct graph as-of a specific point in time
export function useTemporalGraph(params: {
  tenantId: string;
  anchorId: string;
  anchorKind: string;
  asOf: string;
  depth?: number;
} | null) {
  return useQuery({
    key: params
      ? `graph-intel:temporal:${params.tenantId}:${params.anchorId}:${params.asOf}:${params.depth ?? 2}`
      : '',
    fetcher: () =>
      api.graphIntelligence.temporal({
        tenantId: params!.tenantId,
        anchor: { kind: params!.anchorKind, id: params!.anchorId },
        asOf: params!.asOf,
        ...(params?.depth !== undefined && { depth: params.depth }),
      }),
    staleTime: STALE,
    enabled: !!params && !!params.asOf,
  });
}

// Imperative traversal mutation (for on-demand BFS triggered by user action)
export function useGraphTraverseMutation() {
  return useMutation({
    mutationFn: (input: {
      tenantId: string;
      startId: string;
      startKind: string;
      depth?: number;
      direction?: 'in' | 'out' | 'both';
      limit?: number;
    }) =>
      api.graphIntelligence.traverse({
        tenantId: input.tenantId,
        start: { kind: input.startKind, id: input.startId },
        depth: input.depth ?? 2,
        direction: input.direction ?? 'both',
        ...(input.limit !== undefined && { limit: input.limit }),
      }),
  });
}
