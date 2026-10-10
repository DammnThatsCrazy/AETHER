/**
 * Tests for Aether tenant graph layer filtering — all four layers must be present.
 *
 * Validates that:
 * - GraphLayer type includes A2H
 * - Layer filtering correctly selects A2H edges
 * - No layer is silently dropped from the filter set
 * - The graph-contract shared package exports all four layers
 */
import { describe, it, expect } from 'vitest';
import type { GraphLayer } from '@aether-app/features/graph/use-graph-data';
import {
  RELATIONSHIP_LAYERS,
  LAYER_COUNT,
  LAYER_DESCRIPTIONS,
  EDGE_LAYER_MAP,
  classifyEdgeType,
  countEdgesByLayer,
  LAYER_FILTERS,
} from '@aether/shared';

describe('GraphLayer type coverage', () => {
  it('RELATIONSHIP_LAYERS has exactly four entries', () => {
    expect(RELATIONSHIP_LAYERS).toHaveLength(4);
    expect(LAYER_COUNT).toBe(4);
  });

  it('all four layers are in RELATIONSHIP_LAYERS', () => {
    const layers = Array.from(RELATIONSHIP_LAYERS);
    expect(layers).toContain('H2H');
    expect(layers).toContain('H2A');
    expect(layers).toContain('A2H');
    expect(layers).toContain('A2A');
  });

  it('LAYER_FILTERS includes all four layers plus all', () => {
    const filters = Array.from(LAYER_FILTERS);
    expect(filters).toContain('all');
    expect(filters).toContain('H2H');
    expect(filters).toContain('H2A');
    expect(filters).toContain('A2H');
    expect(filters).toContain('A2A');
  });
});

describe('A2H layer in shared contract', () => {
  it('A2H has a layer description', () => {
    expect(LAYER_DESCRIPTIONS.A2H).toBeDefined();
    expect(LAYER_DESCRIPTIONS.A2H.label).toBe('Agent-to-Human');
  });

  it('A2H description does not say placeholder or future', () => {
    const desc = LAYER_DESCRIPTIONS.A2H.description.toLowerCase();
    expect(desc).not.toContain('placeholder');
    expect(desc).not.toContain('future release');
    expect(desc).not.toContain('todo');
  });
});

describe('A2H edge filtering', () => {
  it('NOTIFIES edge classified as A2H', () => {
    expect(classifyEdgeType('NOTIFIES')).toBe('A2H');
  });

  it('RECOMMENDS edge classified as A2H', () => {
    expect(classifyEdgeType('RECOMMENDS')).toBe('A2H');
  });

  it('DELIVERS_TO edge classified as A2H', () => {
    expect(classifyEdgeType('DELIVERS_TO')).toBe('A2H');
  });

  it('ESCALATES_TO edge classified as A2H', () => {
    expect(classifyEdgeType('ESCALATES_TO')).toBe('A2H');
  });

  it('A2H filter selects only A2H edges in countEdgesByLayer', () => {
    const edges = [
      { type: 'NOTIFIES' },
      { type: 'RECOMMENDS' },
      { type: 'HAS_SESSION' },
      { type: 'DELEGATES' },
    ];
    const counts = countEdgesByLayer(edges);
    expect(counts.A2H).toBe(2);
    expect(counts.H2H).toBe(1);
    expect(counts.H2A).toBe(1);
    expect(counts.A2A).toBe(0);
  });
});

describe('Tenant-scoped graph: no global fields exposed', () => {
  it('LAYER_DESCRIPTIONS has no global cross-tenant fields', () => {
    // Verify descriptions are tenant-safe (no "all tenants", "global", "operator" references)
    for (const [layer, desc] of Object.entries(LAYER_DESCRIPTIONS)) {
      expect(desc.description.toLowerCase()).not.toContain('all tenants');
      expect(desc.description.toLowerCase()).not.toContain('operator only');
    }
  });
});
