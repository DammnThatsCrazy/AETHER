import { describe, expect, it } from 'vitest';

import {
  allBlueprintLenses,
  blueprintLensIds,
  getBlueprintLens,
  lensSupportsObject,
  lensSupportsSurface,
  resolveLensAvailability,
  resolveLensSetAvailability,
  type LensResolutionContext,
} from './lens-registry';

const objectContext: LensResolutionContext = {
  objectKind: 'entity',
  surfaceId: 'profile360',
  capabilities: { 'profile360.explore': true },
  permissions: { 'profile360.read': true },
};

describe('blueprint lens registry', () => {
  it('contains each Phase 1 family exactly once', () => {
    const ids = allBlueprintLenses().map((lens) => lens.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual([...blueprintLensIds]);
    expect(ids).toHaveLength(11);
  });

  it('uses canonical engine bindings only when they exist', () => {
    expect(getBlueprintLens('object')?.canonicalLensId).toBe('standard');
    expect(getBlueprintLens('relationship')?.canonicalLensId).toBe('relationship');
    expect(getBlueprintLens('value')?.projectionIds).toEqual(['economic360']);
    expect(getBlueprintLens('signals')?.canonicalLensId).toBeNull();
    expect(getBlueprintLens('signals')?.pending).toBe(true);
    expect(getBlueprintLens('domain')?.projectionIds).toEqual([]);
  });

  it('derives object and surface predicates from existing registries', () => {
    expect(lensSupportsObject('relationship', 'relationship')).toBe(true);
    expect(lensSupportsObject('relationship', 'campaign')).toBe(false);
    expect(lensSupportsSurface('relationship', 'graph')).toBe(true);
    expect(lensSupportsSurface('relationship', 'geographic360')).toBe(false);
    expect(lensSupportsSurface('value', 'economic360')).toBe(true);
  });
});
describe('lens availability', () => {
  it('is deterministic for identical runtime facts', () => {
    const first = resolveLensAvailability('object', objectContext);
    const second = resolveLensAvailability('object', objectContext);
    expect(first).toEqual(second);
    expect(first.availability).toBe('available');
  });

  it('preserves the capability precedence: entitlement, authorization, readiness', () => {
    expect(
      resolveLensAvailability('object', {
        ...objectContext,
        capabilities: { 'profile360.explore': false },
      }).availability,
    ).toBe('not_entitled');
    expect(
      resolveLensAvailability('object', {
        ...objectContext,
        permissions: { 'profile360.read': false },
      }).availability,
    ).toBe('unauthorized');
    expect(
      resolveLensAvailability('object', {
        ...objectContext,
        readiness: { 'profile360.explore': false },
      }).availability,
    ).toBe('not_ready');
  });

  it('does not turn absent blueprint families into available lenses', () => {
    const result = resolveLensAvailability('signals', {
      objectKind: 'entity',
      surfaceId: 'profile360',
    });
    expect(result.availability).toBe('not_ready');
    expect(result.reasons).toContain('canonical_lens_pending');
  });

  it('reports incompatible combinations symmetrically', () => {
    const result = resolveLensSetAvailability(['syndicates', 'object'], {
      objectKind: 'entity',
      surfaceId: 'profile360',
      capabilities: { 'profile360.explore': true },
      permissions: { 'profile360.read': true },
    });
    expect(result.incompatiblePairs).toEqual([['object', 'syndicates']]);
    expect(result.availability).toBe('not_ready');
    expect(result.resolutions.find((entry) => entry.lensId === 'object')?.reasons).toContain(
      'incompatible_lens:object:syndicates',
    );
  });
});
