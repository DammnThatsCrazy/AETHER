import { describe, expect, it } from 'vitest';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import {
  assertCanonicalTruthState,
  profileContextFor,
} from '@aether-app/features/profile360/use-profile360-exploration';

function mountedContext(): ExplorationContextV1 {
  return {
    version: '1',
    scope: { tenant_id: 'tenant-authority', surface: '/users/entity-42' },
    anchors: [{ kind: 'cluster', id: 'cluster-7' }],
    population: {
      logic: 'AND',
      expressions: [{ field: 'risk.score', op: 'gte', value: 0.7 }],
    },
    temporal: {
      mode: 'as_of',
      field: 'observed_at',
      timezone: 'America/New_York',
      as_of: '2026-07-01T00:00:00Z',
    },
    overlays: ['risk'],
  };
}

describe('profile exploration context', () => {
  it('preserves mounted tenant authority, filters, time, overlays, and existing anchors', () => {
    const mounted = mountedContext();
    const result = profileContextFor(mounted, 'entity-42');

    expect(result.scope).toEqual({ tenant_id: 'tenant-authority', surface: 'profile360' });
    expect(result.population).toBe(mounted.population);
    expect(result.temporal).toBe(mounted.temporal);
    expect(result.overlays).toBe(mounted.overlays);
    expect(result.anchors).toEqual([
      { kind: 'entity', id: 'entity-42' },
      { kind: 'cluster', id: 'cluster-7' },
    ]);
    expect(result.presentation).toMatchObject({ view: 'table', page_size: 100 });
    expect(result.truth).toMatchObject({
      include_evidence: true,
      include_provenance: true,
    });
  });

  it('rejects backend-local truth states before canonical rendering', () => {
    expect(() => assertCanonicalTruthState('populated')).toThrow(
      'unknown truth state "populated"',
    );
    expect(() => assertCanonicalTruthState('not_available')).toThrow(
      'unknown truth state "not_available"',
    );
    expect(() => assertCanonicalTruthState('ready')).not.toThrow();
    expect(() => assertCanonicalTruthState('empty')).not.toThrow();
  });
});
