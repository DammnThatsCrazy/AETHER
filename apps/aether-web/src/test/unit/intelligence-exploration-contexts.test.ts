import { describe, expect, it } from 'vitest';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import { campaignExplorationContext } from '@aether-app/features/campaigns/use-campaign-exploration';
import { clusterExplorationContext } from '@aether-app/features/cluster360/use-cluster-exploration';
import { geoExplorationContext } from '@aether-app/features/geo/use-geo-exploration';
import { journeyExplorationContext } from '@aether-app/features/journey/use-journey-exploration';

const base: ExplorationContextV1 = {
  version: '1',
  scope: { tenant_id: 'tenant-a', surface: '/campaigns' },
  temporal: {
    mode: 'window',
    field: 'occurred_at',
    timezone: 'UTC',
    range: {
      kind: 'instant',
      start: '2026-07-01T00:00:00Z',
      endExclusive: '2026-07-28T00:00:00Z',
    },
  },
  population: {
    logic: 'AND',
    expressions: [{ field: 'campaign.channel', op: 'eq', value: 'email' }],
  },
};

describe('intelligence exploration contexts', () => {
  it('retargets campaign context without dropping population or time', () => {
    const context = campaignExplorationContext(base, 'campaign-1');
    expect(context.scope).toEqual({ tenant_id: 'tenant-a', surface: 'campaign360' });
    expect(context.anchors).toEqual([{ kind: 'campaign', id: 'campaign-1' }]);
    expect(context.population).toEqual(base.population);
    expect(context.temporal).toEqual(base.temporal);
    expect(context.presentation?.view).toBe('table');
  });

  it('uses only registered cluster, geo, and journey surface identifiers', () => {
    expect(clusterExplorationContext(base, 'cluster-1').scope.surface).toBe('cluster360');
    expect(geoExplorationContext(base).scope.surface).toBe('geo');
    expect(journeyExplorationContext(base, 'profile-1')).toMatchObject({
      scope: { tenant_id: 'tenant-a', surface: 'journeys' },
      anchors: [{ kind: 'profile', id: 'profile-1' }],
      presentation: { view: 'timeline' },
    });
  });

  it('does not mutate the router-derived base context', () => {
    campaignExplorationContext(base, 'campaign-1');
    clusterExplorationContext(base, 'cluster-1');
    geoExplorationContext(base);
    journeyExplorationContext(base, 'profile-1');
    expect(base.scope.surface).toBe('/campaigns');
    expect(base.anchors).toBeUndefined();
  });
});
