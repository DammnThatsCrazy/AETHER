import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { parseProfileJourney, type ProfileJourney } from './journey-model';

/** The read caps one page of steps at this many (backend max). */
export const JOURNEY_STEP_LIMIT = 200;

/**
 * One profile's compiled unified journey, keeping the summary block
 * (state, started/ended/converted) that `useUnifiedJourney` drops.
 * Thin wrapper over `api.profile.unifiedJourney`.
 */
export function useProfileJourney(profileId: string) {
  return useQuery<ProfileJourney>({
    key: `journeys:profile:${profileId}`,
    fetcher: async () => parseProfileJourney(await api.profile.unifiedJourney(profileId, { limit: JOURNEY_STEP_LIMIT })),
    staleTime: 60_000,
    enabled: !!profileId,
  });
}
