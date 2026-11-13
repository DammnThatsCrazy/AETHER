import { describe, expect, it, vi } from 'vitest';
import { queryCache } from '@aether/ui';

const calls = vi.hoisted(() => ({ inFlight: 0, peak: 0, ids: [] as string[] }));

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: {
    profile: {
      unifiedJourney: async (id: string) => {
        calls.ids.push(id);
        calls.inFlight += 1;
        calls.peak = Math.max(calls.peak, calls.inFlight);
        await new Promise(r => setTimeout(r, 1));
        calls.inFlight -= 1;
        if (id === 'bad') throw new Error('aggregator offline');
        return { steps: [{ step_id: `${id}-s1`, occurred_at: '2026-10-01T00:00:00Z' }], meta: { journey_id: id }, summary: { journey_state: 'open' } };
      },
    },
  },
}));

import { fanoutJourneys } from '@aether-app/features/journeys/use-journey-fanout';

describe('fanoutJourneys', () => {
  it('reads with bounded concurrency, keeps order, never rejects and fills the profile cache', async () => {
    queryCache.invalidatePrefix('journeys:');
    const ids = ['a', 'b', 'bad', 'c', 'd', 'e', 'f', 'g'];
    const out = await fanoutJourneys(ids, 3);
    expect(calls.peak).toBeLessThanOrEqual(3);
    expect(out.map(e => e.id)).toEqual(ids);
    expect(out[2]).toEqual({ id: 'bad', status: 'error', error: 'aggregator offline' });
    expect(out[0]!.status).toBe('ok');
    expect(queryCache.get('journeys:profile:a')).not.toBeNull();

    // A second fan-out reuses fresh cached journeys and only retries the failure.
    calls.ids = [];
    await fanoutJourneys(ids, 3);
    expect(calls.ids).toEqual(['bad']);
  });

  it('drops writes and stops queued reads when the signed-in identity changes mid fan-out', async () => {
    // Codex review on DammnThatsCrazy/AETHER#867: the direct cache write did
    // not carry the generation, so a fan-out started under tenant A and
    // resolved after signing into tenant B repopulated the cache with A's data.
    queryCache.clear();
    calls.ids = [];
    const ids = ['x1', 'x2', 'x3', 'x4'];
    const pending = fanoutJourneys(ids, 1);
    queryCache.clear(); // identity switch while x1 is in flight
    const out = await pending;
    expect(calls.ids).toEqual(['x1']);
    expect(queryCache.get('journeys:profile:x1')).toBeNull();
    expect(out.slice(1).every(e => e.status === 'error')).toBe(true);
  });
});

