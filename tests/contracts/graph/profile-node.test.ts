/**
 * FPS-023 — Graph Profile Node
 * Verifies profile node creation, properties, and lifecycle.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';
import { graphProfileNodeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Profile Node', () => {
  it('should create a profile node with required fields from fixture', () => {
    const nodes = graphProfileNodeFixture.properties?.nodes || [];
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const raw = nodes[0];
    // Fixture uses 'id', contract uses 'node_id' — verify the mapping
    expect((raw as Record<string, unknown>).id).toBe('node_profile_001');
    expect((raw as Record<string, unknown>).type).toBe('profile');
    expect((raw as Record<string, unknown>).labels).toEqual(['profile', 'user', 'identified']);
    expect((raw as Record<string, unknown>).properties).toBeDefined();
    expect((raw.properties as Record<string, unknown>).email).toBe('profile@example.com');
    expect((raw.properties as Record<string, unknown>).name).toBe('Test Profile');
    expect((raw.properties as Record<string, unknown>).user_id).toBe('user_001');
  });

  it('should have created_at and updated_at timestamps on profile node', () => {
    const nodes = graphProfileNodeFixture.properties?.nodes || [];
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.created_at).toBe('2024-09-10T08:00:00.000Z');
    expect(raw.updated_at).toBe('2024-09-11T12:05:00.000Z');
  });

  it('should support multiple property keys on profile node', () => {
    const nodes = graphProfileNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    const keys = Object.keys(props);
    expect(keys).toContain('email');
    expect(keys).toContain('name');
    expect(keys).toContain('user_id');
    expect(keys).toContain('anonymous_id');
    expect(keys).toContain('segment');
  });

  it('should validate GraphNode type accepts profile type', () => {
    const node: GraphNode = {
      node_id: 'profile_1',
      type: 'profile',
      labels: ['profile', 'user'],
      properties: { email: 'test@example.com', name: 'Test' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    expect(node.node_id).toBe('profile_1');
    expect(node.type).toBe('profile');
    expect(node.labels).toEqual(['profile', 'user']);
  });

  it('should validate GraphNode properties is a Record', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'profile',
      labels: ['profile'],
      properties: { key1: 'value1', key2: 42 },
    };
    expect(typeof node.properties).toBe('object');
    expect(node.properties?.key1).toBe('value1');
    expect(node.properties?.key2).toBe(42);
  });

  it('should validate labels is an array of strings', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'profile',
      labels: ['profile', 'identified', 'premium'],
      properties: {},
    };
    expect(Array.isArray(node.labels)).toBe(true);
    expect(node.labels.length).toBe(3);
  });

  it('should accept optional confidence on profile node', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'profile',
      labels: ['profile'],
      properties: {},
      confidence: 0.95,
    };
    expect(node.confidence).toBe(0.95);
  });

  it('should accept optional metadata on profile node', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'profile',
      labels: ['profile'],
      properties: {},
      metadata: {
        derived_from: ['web_sdk', 'shopify'],
        provenance: ['ingestion_pipeline'],
        version: '1.0',
      },
    };
    expect((node.metadata as any)?.derived_from).toEqual(['web_sdk', 'shopify']);
    expect((node.metadata as any)?.version).toBe('1.0');
  });

  it('should read fixture _fixture_version', () => {
    expect(graphProfileNodeFixture._fixture_version).toBe(1);
    expect(graphProfileNodeFixture._fixtureName).toBe('graphProfileNodeFixture');
  });

  it('should validate edges is empty array on profile-only node fixture', () => {
    const edges = graphProfileNodeFixture.properties?.edges;
    expect(Array.isArray(edges)).toBe(true);
    expect(edges?.length).toBe(0);
  });
});
