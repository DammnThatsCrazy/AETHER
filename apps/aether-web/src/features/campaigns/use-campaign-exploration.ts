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

export interface CampaignExplorationRow {
  readonly campaign_id: string;
  readonly count: number;
}

export interface CampaignExplorationData {
  readonly campaigns: readonly CampaignExplorationRow[];
  readonly unattributed_count: number;
  readonly nodes: readonly unknown[];
}

export function campaignExplorationContext(
  base: ExplorationContextV1,
  campaignId?: string,
): ExplorationContextV1 {
  return {
    ...base,
    scope: { ...base.scope, surface: 'campaign360' },
    ...(campaignId
      ? { anchors: [{ kind: 'campaign', id: campaignId }] }
      : base.anchors
        ? { anchors: base.anchors }
        : {}),
    presentation: {
      ...base.presentation,
      view: 'table',
      columns: ['campaign_id', 'count'],
    },
  };
}

export function useCampaignExploration(cursor: string | null, campaignId?: string) {
  const client = useExplorationClient();
  const base = useExplorationContext();
  const context = useMemo(
    () => campaignExplorationContext(base, campaignId),
    [base, campaignId],
  );
  const contextKey = encodeExplorationContext(context);
  const result = useQuery<ExplorationResultEnvelope<CampaignExplorationData>>({
    key: `exploration:campaign360:${contextKey}:${cursor ?? 'first'}`,
    fetcher: () => client.queryLatest(
      { context, cursor, limit: 50 },
      { key: 'aether:campaign360' },
    ),
    staleTime: 30_000,
  });
  return { ...result, client, context };
}
