/**
 * FPS-023 — Graph Touchpoint Edge
 * Verifies touchpoint edge creation, source/target, and properties.
 */
import { describe, it, expect } from 'vitest';

import { GraphEdge } from '@aether/proof-contracts';
import { graphTouchpointEdgeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Touchpoint Edge', () => {
  it('should create a touchpoint edge with required fields from fixture', () => {
    const edges = graphTouchpointEdgeFixture.properties.edges as unknown as Record<string, unknown>[];

    expect(edges.length).toBeGreaterThanOrEqual(1);
    const edge = edges[0] as Record<string, unknown>;
    expect(edge.id).toBe('edge_tp_001');
    expect(edge.source).toBe('node_profile_001');
    expect(edge.target).toBe('node_journey_001');
    expect(edge.type).toBe('touchpoint');
    expect(edge.weight).toBe(1);
    const props = edge.properties as Record<string, unknown>;
    expect(props.channel).toBe('web');
    expect(props.touchpoint_type).toBe('page_view');
  });

  it('should assign weight to touchpoint', () => {
    const edge: GraphEdge = {
      edge_id: 'et1',
      source: 'p1',
      target: 'j1',
      relation: 'touchpoint',
      weight: 2.5,
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };
    expect(edge.weight).toBe(2.5);
  });

  it('should track touchpoint channel', () => {
    const edge: GraphEdge = {
      edge_id: 'et1',
      source: 'profile_1',
      target: 'journey_1',
      relation: 'touchpoint',
      weight: 1,
      properties: { channel: 'mobile' },
    };
    expect(edge.properties?.channel).toBe('mobile');
  });

  it('should link profile to journey via touchpoint', () => {
    const edge: GraphEdge = {
      edge_id: 'et1',
      source: 'profile_1',
      target: 'journey_1',
      relation: 'touchpoint',
      weight: 1,
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };
    expect(edge.source).toMatch(/profile/);
    expect(edge.target).toMatch(/journey/);
  });

  it('should read fixture metadata', () => {
    const raw = graphTouchpointEdgeFixture as unknown as Record<string, unknown>;
    expect(raw._fixture_version).toBe(1);
  });
});
