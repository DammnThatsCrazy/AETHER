import { describe, expect, it } from 'vitest';
import {
  density, episodeBucket, longestGaps, parseProfileJourney, segmentEpisodes, stepLane,
} from '@aether-app/features/journeys/journey-model';
import { FIXTURE_NOW, journeyPayload } from '../component/journeys-fixture';

describe('journey model', () => {
  const journey = parseProfileJourney(journeyPayload());

  it('sorts steps by time and keeps the summary block', () => {
    expect(journey.steps.map(s => s.step_id)).toEqual(['s1', 's2', 's3', 's4', 's5']);
    expect(journey.summary?.state).toBe('converted');
    expect(journey.meta?.journey_id).toBe('j-1');
  });

  it('classifies lanes from actor_type without guessing', () => {
    expect(journey.steps.map(stepLane)).toEqual(['person', 'person', 'agent', 'unclassified', 'system']);
  });

  it('splits episodes on a 30-minute gap and nests sessions', () => {
    const eps = segmentEpisodes(journey.steps);
    expect(eps.map(e => e.id)).toEqual(['s1', 's4']);
    expect(eps[0]!.sessions.map(s => s.id)).toEqual(['sess-a']);
    expect(episodeBucket(eps[1]!, FIXTURE_NOW)).toBe('today');
  });

  it('bins density per minute for short spans and reports the longest waits', () => {
    const ep = segmentEpisodes(journey.steps)[0]!;
    const d = density(ep.steps);
    expect(d.binMs).toBe(60_000);
    expect(d.bins.reduce((a, b) => a + b, 0)).toBe(3);
    expect(longestGaps(journey.steps, 1)[0]).toMatchObject({ from: 'Agent compare', to: 'Order placed' });
  });

  it('treats a malformed payload as an empty journey', () => {
    expect(parseProfileJourney(null)).toMatchObject({ steps: [], meta: null, summary: null });
  });
});
