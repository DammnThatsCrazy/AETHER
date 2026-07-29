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

export interface GeoExplorationRow {
  readonly country: string;
  readonly count: number;
}

export interface GeoExplorationData {
  readonly countries: readonly GeoExplorationRow[];
  readonly without_geo_count: number;
  readonly nodes: readonly unknown[];
}

export function geoExplorationContext(base: ExplorationContextV1): ExplorationContextV1 {
  return {
    ...base,
    scope: { ...base.scope, surface: 'geo' },
    presentation: {
      ...base.presentation,
      view: 'table',
      columns: ['country', 'count'],
    },
  };
}

export function useGeoExploration(cursor: string | null) {
  const client = useExplorationClient();
  const base = useExplorationContext();
  const context = useMemo(() => geoExplorationContext(base), [base]);
  const contextKey = encodeExplorationContext(context);
  const result = useQuery<ExplorationResultEnvelope<GeoExplorationData>>({
    key: `exploration:geo:${contextKey}:${cursor ?? 'first'}`,
    fetcher: () => client.queryLatest(
      { context, cursor, limit: 50 },
      { key: 'aether:geo' },
    ),
    staleTime: 30_000,
  });
  return { ...result, client, context };
}
