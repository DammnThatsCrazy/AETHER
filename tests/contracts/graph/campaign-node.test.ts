/**
 * FPS-023 — Graph Campaign Node
 * Verifies campaign node creation, channel, and lifecycle.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';
import { graphCampaignNodeFixture } from '@aether/proof-fixtures';

describe('FPS-023: Graph Campaign Node', () => {
  it('should create a campaign node with required fields from fixture', () => {
    const nodes = graphCampaignNodeFixture.properties?.nodes || [];
    expect(nodes.length).toBeGreaterThanOrEqual(1);
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.id).toBe('node_campaign_001');
    expect(raw.type).toBe('campaign');
    expect(raw.labels).toEqual(['campaign', 'email', 'welcome']);
    const props = raw.properties as Record<string, unknown>;
    expect(props.name).toBe('summer_promo');
    expect(props.channel).toBe('email');
    expect(props.campaign_type).toBe('promotional');
    expect(props.status).toBe('active');
  });

  it('should have created_at and updated_at timestamps on campaign node', () => {
    const nodes = graphCampaignNodeFixture.properties?.nodes || [];
    const raw = nodes[0] as Record<string, unknown>;
    expect(raw.created_at).toBe('2024-09-01T00:00:00.000Z');
    expect(raw.updated_at).toBe('2024-09-10T00:00:00.000Z');
  });

  it('should track campaign channel', () => {
    const node: GraphNode = {
      node_id: 'nc1',
      type: 'campaign',
      labels: ['campaign', 'push'],
      properties: { name: 'launch', channel: 'push' },
    };
    expect(node.properties?.channel).toBe('push');
  });

  it('should support multiple campaign names', () => {
    const node: GraphNode = {
      node_id: 'nc1',
      type: 'campaign',
      labels: ['campaign', 'email'],
      properties: { name: 'black_friday', channel: 'email' },
    };
    expect(node.properties?.name).toBe('black_friday');
  });

  it('should validate campaign node has source in properties', () => {
    const nodes = graphCampaignNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.source).toBe('manual');
  });

  it('should validate campaign node has started_at in properties', () => {
    const nodes = graphCampaignNodeFixture.properties?.nodes || [];
    const props = (nodes[0].properties as Record<string, unknown>) || {};
    expect(props.started_at).toBe('2024-09-01T00:00:00.000Z');
  });

  it('should validate GraphNode type accepts campaign type', () => {
    const node: GraphNode = {
      node_id: 'campaign_1',
      type: 'campaign',
      labels: ['campaign', 'email'],
      properties: { name: 'summer_promo', channel: 'email', status: 'active' },
      created_at: '2024-01-01T00:00:00.000Z',
      updated_at: '2024-01-01T00:00:00.000Z',
    };
    expect(node.node_id).toBe('campaign_1');
    expect(node.type).toBe('campaign');
  });

  it('should accept optional confidence on campaign node', () => {
    const node: GraphNode = {
      node_id: 'n1',
      type: 'campaign',
      labels: ['campaign'],
      properties: {},
      confidence: 0.85,
    };
    expect(node.confidence).toBe(0.85);
  });

  it('should validate fixture edges is empty array', () => {
    const edges = graphCampaignNodeFixture.properties?.edges;
    expect(Array.isArray(edges)).toBe(true);
    expect(edges?.length).toBe(0);
  });

  it('should read fixture metadata', () => {
    expect(graphCampaignNodeFixture._fixture_version).toBe(1);
    expect(graphCampaignNodeFixture._fixtureName).toBe('graphCampaignNodeFixture');
  });
});
