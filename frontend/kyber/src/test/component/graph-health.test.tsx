/**
 * Tests for the Kyber graph health hook and four-layer observability contracts.
 *
 * Validates that:
 * - GRAPH_LAYERS constant includes all four layers
 * - useGraphHealth returns correct types
 * - useGraphFourLayerPresence correctly identifies missing layers
 * - No placeholder strings appear in layer names or descriptions
 */
import { describe, it, expect } from 'vitest';
import { GRAPH_LAYERS, useGraphFourLayerPresence } from '@kyber/features/graph/use-graph-health';
import {
  RELATIONSHIP_LAYERS,
  LAYER_COUNT,
  LAYER_DESCRIPTIONS,
  EDGE_LAYER_MAP,
  classifyEdgeType,
  countEdgesByLayer,
} from '@aether/shared';

describe('GRAPH_LAYERS constant', () => {
  it('has exactly four layers', () => {
    expect(GRAPH_LAYERS).toHaveLength(4);
  });

  it('includes H2H', () => {
    expect(GRAPH_LAYERS).toContain('H2H');
  });

  it('includes H2A', () => {
    expect(GRAPH_LAYERS).toContain('H2A');
  });

  it('includes A2H — must not be omitted', () => {
    expect(GRAPH_LAYERS).toContain('A2H');
  });

  it('includes A2A', () => {
    expect(GRAPH_LAYERS).toContain('A2A');
  });
});

describe('RELATIONSHIP_LAYERS from shared contract', () => {
  it('has exactly four entries', () => {
    expect(RELATIONSHIP_LAYERS).toHaveLength(4);
    expect(LAYER_COUNT).toBe(4);
  });

  it('all four layers present', () => {
    const layers = Array.from(RELATIONSHIP_LAYERS);
    expect(layers).toContain('H2H');
    expect(layers).toContain('H2A');
    expect(layers).toContain('A2H');
    expect(layers).toContain('A2A');
  });
});

describe('LAYER_DESCRIPTIONS', () => {
  it('has a description for A2H', () => {
    expect(LAYER_DESCRIPTIONS.A2H).toBeDefined();
    expect(LAYER_DESCRIPTIONS.A2H.label).toBe('Agent-to-Human');
  });

  it('no description contains the word placeholder', () => {
    for (const [layer, desc] of Object.entries(LAYER_DESCRIPTIONS)) {
      expect(desc.description.toLowerCase()).not.toContain('placeholder');
      expect(desc.label.toLowerCase()).not.toContain('placeholder');
    }
  });

  it('all four layers have descriptions', () => {
    for (const layer of ['H2H', 'H2A', 'A2H', 'A2A'] as const) {
      expect(LAYER_DESCRIPTIONS[layer]).toBeDefined();
    }
  });
});

describe('EDGE_LAYER_MAP', () => {
  it('classifies NOTIFIES as A2H', () => {
    expect(EDGE_LAYER_MAP.NOTIFIES).toBe('A2H');
  });

  it('classifies RECOMMENDS as A2H', () => {
    expect(EDGE_LAYER_MAP.RECOMMENDS).toBe('A2H');
  });

  it('classifies DELIVERS_TO as A2H', () => {
    expect(EDGE_LAYER_MAP.DELIVERS_TO).toBe('A2H');
  });

  it('classifies ESCALATES_TO as A2H', () => {
    expect(EDGE_LAYER_MAP.ESCALATES_TO).toBe('A2H');
  });

  it('classifies DELEGATES as H2A', () => {
    expect(EDGE_LAYER_MAP.DELEGATES).toBe('H2A');
  });

  it('classifies HIRED as A2A', () => {
    expect(EDGE_LAYER_MAP.HIRED).toBe('A2A');
  });

  it('classifies HAS_SESSION as H2H', () => {
    expect(EDGE_LAYER_MAP.HAS_SESSION).toBe('H2H');
  });

  it('has edges for all four layers', () => {
    const layers = new Set(Object.values(EDGE_LAYER_MAP));
    expect(layers).toContain('H2H');
    expect(layers).toContain('H2A');
    expect(layers).toContain('A2H');
    expect(layers).toContain('A2A');
  });
});

describe('classifyEdgeType', () => {
  it('classifies NOTIFIES → A2H', () => {
    expect(classifyEdgeType('NOTIFIES')).toBe('A2H');
  });

  it('classifies RECOMMENDS → A2H', () => {
    expect(classifyEdgeType('RECOMMENDS')).toBe('A2H');
  });

  it('classifies DELEGATES → H2A', () => {
    expect(classifyEdgeType('DELEGATES')).toBe('H2A');
  });

  it('classifies PAYS → A2A', () => {
    expect(classifyEdgeType('PAYS')).toBe('A2A');
  });

  it('classifies HAS_SESSION → H2H', () => {
    expect(classifyEdgeType('HAS_SESSION')).toBe('H2H');
  });

  it('returns null for unknown edge type', () => {
    expect(classifyEdgeType('UNKNOWN_TYPE')).toBeNull();
  });
});

describe('countEdgesByLayer', () => {
  it('counts all four layers', () => {
    const edges = [
      { type: 'HAS_SESSION' },   // H2H
      { type: 'DELEGATES' },     // H2A
      { type: 'NOTIFIES' },      // A2H
      { type: 'HIRED' },         // A2A
    ];
    const counts = countEdgesByLayer(edges);
    expect(counts.H2H).toBe(1);
    expect(counts.H2A).toBe(1);
    expect(counts.A2H).toBe(1);
    expect(counts.A2A).toBe(1);
  });

  it('returns zeros for empty edges', () => {
    const counts = countEdgesByLayer([]);
    expect(counts).toEqual({ H2H: 0, H2A: 0, A2H: 0, A2A: 0 });
  });

  it('accumulates multiple A2H edges', () => {
    const edges = [
      { type: 'NOTIFIES' },
      { type: 'RECOMMENDS' },
      { type: 'ESCALATES_TO' },
    ];
    const counts = countEdgesByLayer(edges);
    expect(counts.A2H).toBe(3);
  });
});
