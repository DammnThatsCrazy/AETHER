/**
 * FPS-023 — Graph Communication Node
 * Verifies communication node creation, channel, and lifecycle.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';
import { graphCommunicationNodeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Communication Node', () => {
  it('should create a communication node with required fields from fixture', () => {
    const nodes = graphCommunicationNodeFixture.properties?.nodes || [];
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.id).toBe('node_comm_001');
    expect(raw.type).toBe('communication');
    expect(raw.labels).toEqual(['communication', 'email', 'welcome']);
    const props = raw.properties as Record<string, unknown>;
    expect(props.channel).toBe('email');
    expect(props.subject).toBe('Welcome');
    expect(props.type).toBe('welcome_email');
    expect(props.status).toBe('delivered');
  });

  it('should have created_at and updated_at timestamps on communication node', () => {
    const nodes = graphCommunicationNodeFixture.properties?.nodes || [];
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.created_at).toBe('2024-09-10T10:00:00.000Z');
    expect(raw.updated_at).toBe('2024-09-10T10:02:00.000Z');
  });

  it('should track communication subject', () => {
    const node: GraphNode = {
      node_id: 'nc1',
      type: 'communication',
      labels: ['communication', 'email'],
      properties: { channel: 'email', subject: 'Your Order' },
    };
    expect(node.properties?.subject).toBe('Your Order');
  });

  it('should support different channels', () => {
    const node: GraphNode = {
      node_id: 'nc1',
      type: 'communication',
      labels: ['communication', 'sms'],
      properties: { channel: 'sms', subject: 'OTP code' },
    };
    expect(node.properties?.channel).toBe('sms');
  });

  it('should validate GraphNode type accepts communication type', () => {
    const node: GraphNode = {
      node_id: 'comm_1',
      type: 'communication',
      labels: ['communication', 'email'],
      properties: { channel: 'email', subject: 'Welcome', type: 'welcome_email' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    expect(node.node_id).toBe('comm_1');
    expect(node.type).toBe('communication');
  });

  it('should validate sent_at in properties', () => {
    const nodes = graphCommunicationNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.sent_at).toBe('2024-09-10T10:00:00.000Z');
  });

  it('should validate fixture edges is empty array', () => {
    const edges = graphCommunicationNodeFixture.properties?.edges;
    expect(Array.isArray(edges)).toBe(true);
    expect(edges?.length).toBe(0);
  });

  it('should read fixture metadata', () => {
    expect(graphCommunicationNodeFixture._fixture_version).toBe(1);
    expect(graphCommunicationNodeFixture._fixtureName).toBe('graphCommunicationNodeFixture');
  });
});
