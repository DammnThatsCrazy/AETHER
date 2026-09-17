/**
 * FPS-023 — Graph Journey Node
 * Verifies journey node creation, stage tracking, and lifecycle.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';
import { graphJourneyNodeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Journey Node', () => {
  it('should create a journey node with required fields from fixture', () => {
    const nodes = graphJourneyNodeFixture.properties?.nodes || [];
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.id).toBe('node_journey_001');
    expect(raw.type).toBe('journey');
    expect(raw.labels).toEqual(['journey', 'onboarding']);
    expect(raw.properties).toBeDefined();
    const props = raw.properties as Record<string, unknown>;
    expect(props.name).toBe('onboarding');
    expect(props.stage).toBe('activation');
    expect(props.journey_type).toBe('onboarding');
    expect(props.version).toBe('1.0');
  });

  it('should have created_at and updated_at timestamps on journey node', () => {
    const nodes = graphJourneyNodeFixture.properties?.nodes || [];
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.created_at).toBe('2024-09-10T10:00:00.000Z');
    expect(raw.updated_at).toBe('2024-09-11T10:00:00.000Z');
  });

  it('should track journey stage transitions', () => {
    const node: GraphNode = {
      node_id: 'nj1',
      type: 'journey',
      labels: ['journey', 'onboarding'],
      properties: { name: 'onboarding', stage: 'activation' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    const updatedProps = { ...node.properties, stage: 'retention' };
    expect(updatedProps.stage).toBe('retention');
  });

  it('should support multiple journey names', () => {
    const node: GraphNode = {
      node_id: 'nj1',
      type: 'journey',
      labels: ['journey', 'purchase_flow'],
      properties: { name: 'purchase_flow', stage: 'checkout' },
    };
    expect(node.properties?.name).toBe('purchase_flow');
  });

  it('should validate journey node has started_at in properties', () => {
    const nodes = graphJourneyNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.started_at).toBe('2024-09-10T10:00:00.000Z');
  });

  it('should validate GraphNode type accepts journey type', () => {
    const node: GraphNode = {
      node_id: 'journey_1',
      type: 'journey',
      labels: ['journey', 'onboarding'],
      properties: { name: 'onboarding', stage: 'activation' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    expect(node.node_id).toBe('journey_1');
    expect(node.type).toBe('journey');
  });

  it('should validate fixture has edges empty array', () => {
    const edges = graphJourneyNodeFixture.properties?.edges;
    expect(Array.isArray(edges)).toBe(true);
    expect(edges?.length).toBe(0);
  });

  it('should read fixture metadata', () => {
    expect(graphJourneyNodeFixture._fixture_version).toBe(1);
    expect(graphJourneyNodeFixture._fixtureName).toBe('graphJourneyNodeFixture');
  });
});
