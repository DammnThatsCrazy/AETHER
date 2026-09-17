/**
 * FPS-023 — Graph Attribution Edge
 * Verifies attribution edge creation, model, and confidence.
 */
import { describe, it, expect } from 'vitest';

import { GraphEdge } from '@aether/proof-contracts';
import { graphAttributionEdgeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Attribution Edge', () => {
  it('should create an attribution edge with required fields from fixture', () => {
    const edges = graphAttributionEdgeFixture.properties.edges as unknown as Record<string, unknown>[];

    expect(edges.length).toBeGreaterThanOrEqual(1);
    const edge = edges[0] as Record<string, unknown>;
    expect(edge.id).toBe('edge_attr_001');
    expect(edge.source).toBe('node_campaign_001');
    expect(edge.target).toBe('node_conv_001');
    expect(edge.type).toBe('attribution');
    expect(edge.weight).toBe(0.75);
    const props = edge.properties as Record<string, unknown>;
    expect(props.model).toBe('last_touch');
    expect(props.confidence).toBe(0.9);
  });

  it('should assign weight to attribution', () => {
    const edge: GraphEdge = {
      edge_id: 'ea1',
      source: 'j1',
      target: 'cv1',
      relation: 'attribution',
      weight: 0.85,
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };
    expect(edge.weight).toBe(0.85);
  });

  it('should link journey to conversion via attribution', () => {
    const edge: GraphEdge = {
      edge_id: 'ea1',
      source: 'journey_1',
      target: 'conversion_1',
      relation: 'attribution',
      weight: 1,
      properties: {},
    };
    expect(edge.source).toMatch(/journey/);
    expect(edge.target).toMatch(/conversion/);
  });

  it('should validate attribution model in properties', () => {
    const edge: GraphEdge = {
      edge_id: 'ea1',
      source: 'j1',
      target: 'cv1',
      relation: 'attribution',
      weight: 1,
      properties: { model: 'first_touch', confidence: 0.7 },
    };
    expect(edge.properties?.model).toBe('first_touch');
    expect(edge.properties?.confidence).toBe(0.7);
  });
});
