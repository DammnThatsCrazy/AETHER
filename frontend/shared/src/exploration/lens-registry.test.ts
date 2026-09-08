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
    expect(getBlueprintLens('object')?.projectionIds).toEqual([]);
    expect(getBlueprintLens('object')?.supportedObjectKinds).toEqual([
      'agent',
      'campaign',
      'cluster',
      'connection',
      'entity',
      'episode',
      'population',
      'relationship',
      'source',
    ]);
    expect(getBlueprintLens('relationship')?.canonicalLensId).toBe('relationship');
    expect(getBlueprintLens('value')?.projectionIds).toEqual(['economic360']);
    expect(getBlueprintLens('signals')?.canonicalLensId).toBeNull();
    expect(getBlueprintLens('signals')?.pending).toBe(true);
    expect(getBlueprintLens('domain')?.projectionIds).toEqual([]);
  });

  it('derives object and surface predicates from existing registries', () => {
    expect(lensSupportsObject('object', 'campaign')).toBe(true);
    expect(lensSupportsObject('object', 'source')).toBe(true);
    expect(lensSupportsObject('relationship', 'relationship')).toBe(true);
    expect(lensSupportsObject('relationship', 'campaign')).toBe(false);
    expect(lensSupportsSurface('relationship', 'graph')).toBe(true);
    expect(lensSupportsSurface('relationship', 'geographic360')).toBe(false);
    expect(lensSupportsSurface('value', 'economic360')).toBe(true);
  });

  it('does not invent pairwise incompatibilities absent from canonical registries', () => {
    const result = resolveLensSetAvailability(['syndicates', 'object'], objectContext);
    expect(result.incompatiblePairs).toEqual([]);
    expect(result.resolutions.find((entry) => entry.lensId === 'object')?.reasons).not.toContain(
      'incompatible_lens:object:syndicates',
    );
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
      resolveLensAvailability('relationship', {
        objectKind: 'relationship',
        surfaceId: 'graph',
        capabilities: { 'relationship360.explore': false },
      }).availability,
    ).toBe('not_entitled');
    expect(
      resolveLensAvailability('relationship', {
        objectKind: 'relationship',
        surfaceId: 'graph',
        capabilities: { 'relationship360.explore': true },
        permissions: { 'relationship360.read': false },
      }).availability,
    ).toBe('unauthorized');
    expect(
      resolveLensAvailability('relationship', {
        objectKind: 'relationship',
        surfaceId: 'graph',
        capabilities: { 'relationship360.explore': true },
        permissions: { 'relationship360.read': true },
        readiness: { 'relationship360.explore': false },
      }).availability,
    ).toBe('not_ready');
  });

  it('keeps generated explore capabilities separate from read permissions', () => {
    const relationship = getBlueprintLens('relationship');
    expect(relationship?.requiredCapabilities).toEqual(['relationship360.explore']);
    expect(relationship?.requiredPermissions).toEqual(['relationship360.read']);
    expect(
      resolveLensAvailability('relationship', {
        objectKind: 'relationship',
        surfaceId: 'graph',
        capabilities: { 'relationship360.explore': true },
      }).availability,
    ).toBe('unauthorized');
    expect(
      resolveLensAvailability('relationship', {
        objectKind: 'relationship',
        surfaceId: 'graph',
        permissions: { 'relationship360.read': true },
      }).availability,
    ).toBe('not_ready');
  });

  it('honors canonical lens, projection, and surface temporal constraints', () => {
    const unavailable = resolveLensAvailability('relationship', {
      objectKind: 'relationship',
      surfaceId: 'graph',
      temporalMode: 'compare',
      capabilities: { 'relationship360.explore': true },
      permissions: { 'relationship360.read': true },
    });
    expect(unavailable.availability).toBe('not_ready');
    expect(unavailable.reasons).toContain('temporal_mode_not_supported:compare');

    const available = resolveLensAvailability('relationship', {
      objectKind: 'relationship',
      surfaceId: 'graph',
      temporalMode: 'relative',
      capabilities: { 'relationship360.explore': true },
      permissions: { 'relationship360.read': true },
    });
    expect(available.availability).toBe('available');
  });

  it('does not turn absent blueprint families into available lenses', () => {
    const result = resolveLensAvailability('signals', {
      objectKind: 'entity',
      surfaceId: 'profile360',
    });
    expect(result.availability).toBe('not_ready');
    expect(result.reasons).toContain('canonical_lens_pending');
  });

});
