import { useMemo } from 'react';
import { useQuery } from '@aether/ui';
import {
  encodeExplorationContext,
  useExplorationClient,
  useExplorationContext,
} from '@aether/ui/exploration';
import type {
  ExplorationContextV1,
  ExplorationResultEnvelope,
} from '@aether/shared/exploration-contract';

export interface ClusterExplorationRow {
  readonly cluster_id: string;
  readonly member_ids: readonly string[];
  readonly member_count: number;
}

export interface ClusterExplorationData {
  readonly clusters: readonly ClusterExplorationRow[];
  readonly unclustered_count: number;
  readonly nodes: readonly unknown[];
}

export function clusterExplorationContext(
  base: ExplorationContextV1,
  clusterId?: string,
): ExplorationContextV1 {
  return {
    ...base,
    scope: { ...base.scope, surface: 'cluster360' },
    ...(clusterId
      ? { anchors: [{ kind: 'cluster', id: clusterId }] }
      : base.anchors
        ? { anchors: base.anchors }
        : {}),
    presentation: {
      ...base.presentation,
      view: 'table',
      columns: ['cluster_id', 'member_count'],
    },
  };
}

export function useClusterExploration(cursor: string | null, clusterId?: string) {
  const client = useExplorationClient();
  const base = useExplorationContext();
  const context = useMemo(
    () => clusterExplorationContext(base, clusterId),
    [base, clusterId],
  );
  const contextKey = encodeExplorationContext(context);
  const result = useQuery<ExplorationResultEnvelope<ClusterExplorationData>>({
    key: `exploration:cluster360:${contextKey}:${cursor ?? 'first'}`,
    fetcher: () => client.queryLatest(
      { context, cursor, limit: 50 },
      { key: 'aether:cluster360' },
    ),
    staleTime: 30_000,
  });
  return { ...result, client, context };
}
