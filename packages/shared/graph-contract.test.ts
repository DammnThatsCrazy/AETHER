import { describe, expect, it } from 'vitest';
import {
  classifyEdgeType,
  countEdgesByLayer,
  EDGE_LAYER_MAP,
  RELATIONSHIP_LAYERS,
  LAYER_COUNT,
} from './graph-contract';

describe('graph-contract', () => {
  describe('LAYER_COUNT', () => {
    it('must be exactly 4', () => {
      expect(LAYER_COUNT).toBe(4);
      expect(RELATIONSHIP_LAYERS).toHaveLength(4);
    });
  });

  describe('classifyEdgeType', () => {
    it('returns the correct layer for known edge types', () => {
      for (const [edgeType, layer] of Object.entries(EDGE_LAYER_MAP)) {
        expect(classifyEdgeType(edgeType)).toBe(layer);
      }
    });

    it('returns null for unknown edge types', () => {
      expect(classifyEdgeType('unknown_edge')).toBeNull();
      expect(classifyEdgeType('')).toBeNull();
    });
  });

  describe('countEdgesByLayer', () => {
    it('returns zero counts for an empty edge list', () => {
      const counts = countEdgesByLayer([]);
      expect(counts).toEqual({ H2H: 0, H2A: 0, A2H: 0, A2A: 0 });
    });

    it('counts edges by their classified layer', () => {
      const h2hType = Object.entries(EDGE_LAYER_MAP).find(([, l]) => l === 'H2H')?.[0];
      const a2aType = Object.entries(EDGE_LAYER_MAP).find(([, l]) => l === 'A2A')?.[0];
      if (!h2hType || !a2aType) return;

      const counts = countEdgesByLayer([
        { type: h2hType },
        { type: h2hType },
        { type: a2aType },
        { type: 'unknown_edge' },
      ]);
      expect(counts.H2H).toBe(2);
      expect(counts.A2A).toBe(1);
      expect(counts.H2A).toBe(0);
      expect(counts.A2H).toBe(0);
    });

    it('ignores edges with unrecognised types', () => {
      const counts = countEdgesByLayer([{ type: 'not_a_real_edge' }]);
      expect(Object.values(counts).every((v) => v === 0)).toBe(true);
    });
  });
});
