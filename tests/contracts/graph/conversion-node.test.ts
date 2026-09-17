/**
 * FPS-023 — Graph Conversion Node
 * Verifies conversion node creation, value, and lifecycle.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';
import { graphConversionNodeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Conversion Node', () => {
  it('should create a conversion node with required fields from fixture', () => {
    const nodes = graphConversionNodeFixture.properties?.nodes || [];
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.id).toBe('node_conv_001');
    expect(raw.type).toBe('conversion');
    expect(raw.labels).toEqual(['conversion', 'purchase', 'completed']);
    const props = raw.properties as Record<string, unknown>;
    expect(props.event).toBe('purchase');
    expect(props.value).toBe(49.99);
    expect(props.currency).toBe('usd');
    expect(props.conversion_type).toBe('purchase');
  });

  it('should have created_at and updated_at timestamps on conversion node', () => {
    const nodes = graphConversionNodeFixture.properties?.nodes || [];
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.created_at).toBe('2024-09-10T12:00:00.000Z');
    expect(raw.updated_at).toBe('2024-09-10T12:00:00.000Z');
  });

  it('should track conversion value', () => {
    const node: GraphNode = {
      node_id: 'ncv1',
      type: 'conversion',
      labels: ['conversion', 'signup'],
      properties: { event: 'signup', value: 0 },
    };
    expect(node.properties?.value).toBe(0);
  });

  it('should support high-value conversions', () => {
    const node: GraphNode = {
      node_id: 'ncv1',
      type: 'conversion',
      labels: ['conversion', 'enterprise_purchase'],
      properties: { event: 'enterprise_purchase', value: 50000 },
    };
    expect(node.properties?.value).toBe(50000);
  });

  it('should validate conversion node has occurred_at in properties', () => {
    const nodes = graphConversionNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.occurred_at).toBe('2024-09-10T12:00:00.000Z');
  });

  it('should validate GraphNode type accepts conversion type', () => {
    const node: GraphNode = {
      node_id: 'conv_1',
      type: 'conversion',
      labels: ['conversion', 'purchase'],
      properties: { event: 'purchase', value: 49.99, currency: 'usd' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    expect(node.node_id).toBe('conv_1');
    expect(node.type).toBe('conversion');
  });

  it('should accept optional confidence on conversion node', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'conversion',
      labels: ['conversion'],
      properties: { event: 'purchase', value: 99.99 },
      confidence: 0.9,
    };
    expect(node.confidence).toBe(0.9);
  });

  it('should validate fixture edges is empty array', () => {
    const edges = graphConversionNodeFixture.properties?.edges;
    expect(Array.isArray(edges)).toBe(true);
    expect(edges?.length).toBe(0);
  });

  it('should read fixture metadata', () => {
    expect(graphConversionNodeFixture._fixture_version).toBe(1);
    expect(graphConversionNodeFixture._fixtureName).toBe('graphConversionNodeFixture');
  });
});
