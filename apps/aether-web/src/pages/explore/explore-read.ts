import { useMemo } from 'react';
import { useGraphData } from '@aether-app/features/graph/use-graph-data';
import type { GraphSnapshot } from './explore-model';

/**
 * The Graph page's one read: the canonical graph query (`/v1/explore/query`,
 * surface `graph`) through `useGraphData`, the same hook the advanced
 * explorer's GraphPage uses (requests share its `queryLatest` key). Loading,
 * error and ready stay distinct; nothing is filled in when the read is empty.
 */
export function useExploreGraphRead(): GraphSnapshot {
  const { nodes, edges, clusters, isLoading, error } = useGraphData();
  return useMemo<GraphSnapshot>(
    () => ({ status: error ? 'error' : isLoading ? 'loading' : 'ready', nodes, edges, clusters }),
    [nodes, edges, clusters, isLoading, error],
  );
}
