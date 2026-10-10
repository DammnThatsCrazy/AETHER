import { afterEach, describe, expect, it, vi } from 'vitest';

import { fetchJourneyPage } from '@aether-app/features/journey/use-unified-journey';
import { api } from '@aether-app/lib/api/endpoints';

const unifiedJourney = vi.spyOn(api.profile, 'unifiedJourney');

describe('fetchJourneyPage', () => {
  afterEach(() => {
    unifiedJourney.mockReset();
  });

  it('loads through the auth-aware profile API client', async () => {
    unifiedJourney.mockResolvedValue({
      steps: [{ step_id: 'step-1', activity_family: 'campaign' }],
      meta: {
        journey_id: 'journey-1',
        journey_version_id: 'version-1',
        step_count: 1,
        compiler_version: '2.0',
        quality_status: 'complete',
      },
      pagination: { has_more: false, next_cursor: null },
    });

    const result = await fetchJourneyPage('profile/with-slash', {
      family: 'campaign',
      limit: 25,
    });

    expect(unifiedJourney).toHaveBeenCalledWith('profile/with-slash', {
      limit: 25,
      family: 'campaign',
    });
    expect(result.steps).toHaveLength(1);
    expect(result.meta?.journey_id).toBe('journey-1');
  });
});
