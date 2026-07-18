import { describe, it, expect } from 'vitest';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import { breadcrumbsFromContext, surfaceSupportsSavedViews } from './chrome-model';

function ctx(overrides: Partial<ExplorationContextV1> = {}): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: 't1', surface: 'graph' },
    temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
    ...overrides,
  };
}

describe('chrome-model', () => {
  it('builds a trail from surface, anchors, and focus', () => {
    const crumbs = breadcrumbsFromContext(
      ctx({
        anchors: [{ kind: 'cluster', id: 'c1' }],
        selection: { focused: { kind: 'entity', id: 'e1' } },
      }),
      'Graph',
    );
    expect(crumbs.map((c) => c.label)).toEqual(['Graph', 'cluster · c1', 'focus · e1']);
  });

  it('reflects the surface saved-view capability', () => {
    expect(surfaceSupportsSavedViews('graph')).toBe(true);
    expect(surfaceSupportsSavedViews('profile360')).toBe(false);
    expect(surfaceSupportsSavedViews('nonexistent')).toBe(false);
  });
});
