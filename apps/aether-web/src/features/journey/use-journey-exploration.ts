import { useMemo } from 'react';
import { useQuery } from '@aether/ui';
import {
  encodeExplorationContext,
  useExplorationClient,
  useExplorationContext,
} from '@aether/ui/exploration';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';

export function journeyExplorationContext(
  base: ExplorationContextV1,
  profileId: string,
): ExplorationContextV1 {
  return {
    ...base,
    scope: { ...base.scope, surface: 'journeys' },
    anchors: [{ kind: 'profile', id: profileId }],
    presentation: {
      ...base.presentation,
      view: 'timeline',
    },
  };
}

export function useJourneyExplorationAvailability(profileId: string) {
  const client = useExplorationClient();
  const base = useExplorationContext();
  const context = useMemo(
    () => journeyExplorationContext(base, profileId),
    [base, profileId],
  );
  const contextKey = encodeExplorationContext(context);
  const result = useQuery({
    key: `exploration:journeys:availability:${contextKey}`,
    fetcher: () => client.validate(context),
    staleTime: 30_000,
    enabled: Boolean(profileId),
  });
  return { ...result, client, context };
}
