import { queryCache, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { parseProfileJourney, type ProfileJourney } from './journey-model';
import { JOURNEY_STEP_LIMIT } from './use-profile-journey';

/**
 * The API has no tenant-wide journey list, so the Journeys index reads each
 * listed profile's compiled journey. The fan-out is bounded: at most
 * JOURNEY_FANOUT_CAP profiles, JOURNEY_FANOUT_CONCURRENCY reads at a time.
 * The page discloses the cap and any failed reads.
 */
export const JOURNEY_FANOUT_CAP = 24;
export const JOURNEY_FANOUT_CONCURRENCY = 6;

export type FanoutEntry =
  | { readonly id: string; readonly status: 'ok'; readonly journey: ProfileJourney }
  | { readonly id: string; readonly status: 'error'; readonly error: string };

const STALE_MS = 60_000;
const profileKey = (id: string) => `journeys:profile:${id}`;

async function readOne(id: string, generation: number): Promise<FanoutEntry> {
  const key = profileKey(id);
  const cached = queryCache.get<ProfileJourney>(key);
  if (cached && !queryCache.isStale(key, STALE_MS)) return { id, status: 'ok', journey: cached.data };
  try {
    const journey = parseProfileJourney(await api.profile.unifiedJourney(id, { limit: JOURNEY_STEP_LIMIT }));
    // Same key as useProfileJourney, so opening a card does not re-read it.
    // The generation guard drops the write if the signed-in identity changed
    // while the read was in flight (queryCache.clear() on login/logout).
    queryCache.set(key, journey, generation);
    return { id, status: 'ok', journey };
  } catch (err) {
    return { id, status: 'error', error: err instanceof Error ? err.message : 'Request failed' };
  }
}

/** Reads every id with at most `concurrency` requests in flight; never rejects. */
export async function fanoutJourneys(ids: readonly string[], concurrency = JOURNEY_FANOUT_CONCURRENCY): Promise<FanoutEntry[]> {
  const out: FanoutEntry[] = new Array<FanoutEntry>(ids.length);
  const generation = queryCache.generation;
  let next = 0;
  const worker = async () => {
    // Stop issuing reads once the identity changes: they would carry the new
    // credential into a fan-out that belongs to the previous one.
    while (next < ids.length && queryCache.generation === generation) {
      const i = next++;
      out[i] = await readOne(ids[i]!, generation);
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, ids.length) }, worker));
  for (let i = 0; i < ids.length; i += 1) {
    out[i] ??= { id: ids[i]!, status: 'error', error: 'Signed-in identity changed' };
  }
  return out;
}

export function useJourneyFanout(ids: readonly string[]) {
  return useQuery<FanoutEntry[]>({
    key: `journeys:fanout:${ids.join('|')}`,
    fetcher: () => fanoutJourneys(ids),
    staleTime: STALE_MS,
    enabled: ids.length > 0,
  });
}
