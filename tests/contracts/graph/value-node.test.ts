/**
 * FPS-023 — Graph Value Node
 * Verifies value node creation, metric, and lifecycle.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';
import { graphValueNodeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Value Node', () => {
  it('should create a value node with required fields from fixture', () => {
    const nodes = graphValueNodeFixture.properties?.nodes || [];
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.id).toBe('node_value_001');
    expect(raw.type).toBe('value');
    expect(raw.labels).toEqual(['value', 'ltv', 'financial']);
    const props = raw.properties as Record<string, unknown>;
    expect(props.metric).toBe('ltv');
    expect(props.value).toBe(150.00);
    expect(props.currency).toBe('usd');
    expect(props.value_type).toBe('lifetime_value');
  });

  it('should have created_at and updated_at timestamps on value node', () => {
    const nodes = graphValueNodeFixture.properties?.nodes || [];
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.created_at).toBe('2024-09-10T12:00:00.000Z');
    expect(raw.updated_at).toBe('2024-09-10T12:00:00.000Z');
  });

  it('should track different value metrics', () => {
    const node: GraphNode = {
      node_id: 'nv1',
      type: 'value',
      labels: ['value', 'arpu'],
      properties: { metric: 'arpu', value: 125.5 },
    };
    expect(node.properties?.metric).toBe('arpu');
    expect(node.properties?.value).toBe(125.5);
  });

  it('should support integer and decimal values', () => {
    const intNode: GraphNode = {
      node_id: 'nv1',
      type: 'value',
      labels: ['value', 'count'],
      properties: { metric: 'count', value: 42 },
    };
    const decNode: GraphNode = {
      node_id: 'nv2',
      type: 'value',
      labels: ['value', 'rate'],
      properties: { metric: 'rate', value: 0.85 },
    };
    expect(intNode.properties?.value).toBe(42);
    expect(decNode.properties?.value).toBe(0.85);
  });

  it('should validate value node has calculated_at in properties', () => {
    const nodes = graphValueNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.calculated_at).toBe('2024-09-10T12:00:00.000Z');
  });

  it('should validate value node has method in properties', () => {
    const nodes = graphValueNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.method).toBe('rolling_12m');
  });

  it('should validate GraphNode type accepts value type', () => {
    const node: GraphNode = {
      node_id: 'value_1',
      type: 'value',
      labels: ['value', 'ltv'],
      properties: { metric: 'ltv', value: 150.0, currency: 'usd' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    expect(node.node_id).toBe('value_1');
    expect(node.type).toBe('value');
  });

  it('should accept optional confidence on value node', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'value',
      labels: ['value'],
      properties: { metric: 'ltv', value: 100 },
      confidence: 0.8,
    };
    expect(node.confidence).toBe(0.8);
  });

  it('should validate fixture edges is empty array', () => {
    const edges = graphValueNodeFixture.properties?.edges;
    expect(Array.isArray(edges)).toBe(true);
    expect(edges?.length).toBe(0);
  });

  it('should read fixture metadata', () => {
    expect(graphValueNodeFixture._fixture_version).toBe(1);
    expect(graphValueNodeFixture._fixtureName).toBe('graphValueNodeFixture');
  });
});
