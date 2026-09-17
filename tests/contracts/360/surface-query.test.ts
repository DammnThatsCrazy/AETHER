/**
 * FPS-023 — Surface 360 Query Contract
 * Verifies 360-degree profile surface queries.
 */
import { describe, it, expect } from 'vitest';

import { Surface360Query } from '@aether/proof-contracts';
import { surface360QueryFixture } from '@aether/proof-fixtures';

describe('FPS-023: Surface 360 Query', () => {
  it('should construct a valid 360 surface query from fixture', () => {
    const fixtureProps = surface360QueryFixture.properties || {};
    expect(fixtureProps.profileId).toBe('profile_001');
    expect(fixtureProps.surfaces).toEqual(['purchases', 'campaigns', 'identities', 'communications']);
    expect(fixtureProps.depth).toBe('deep');
    expect(fixtureProps.includeEdges).toBe(true);
    expect(fixtureProps.timeWindow).toBeDefined();
    expect(fixtureProps.timeWindow?.start).toBe('2024-01-01T00:00:00.000Z');
    expect(fixtureProps.timeWindow?.end).toBe('2024-09-11T23:59:59.000Z');
    expect(fixtureProps.limitPerSurface).toBe(100);
  });

  it('should construct Surface360Query with required contract fields', () => {
    const query: Surface360Query = {
      workspace_id: 'proof-lab',
      user_id: 'user_001',
      depth: 'deep',
      include_profile: true,
      include_campaigns: true,
      include_communications: true,
      include_journeys: true,
      include_conversions: true,
      include_value: true,
      include_graph: true,
    };
    expect(query.workspace_id).toBe('proof-lab');
    expect(query.user_id).toBe('user_001');
    expect(query.depth).toBe('deep');
    expect(query.include_profile).toBe(true);
    expect(query.include_campaigns).toBe(true);
  });

  it('should accept shallow depth', () => {
    const query: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'shallow',
      include_profile: true,
      include_campaigns: false,
      include_communications: false,
      include_journeys: false,
      include_conversions: false,
      include_value: false,
      include_graph: false,
    };
    expect(query.depth).toBe('shallow');
  });

  it('should accept standard depth', () => {
    const query: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'standard',
      include_profile: true,
      include_campaigns: true,
      include_communications: true,
      include_journeys: false,
      include_conversions: true,
      include_value: false,
      include_graph: false,
    };
    expect(query.depth).toBe('standard');
  });

  it('should toggle edge inclusion', () => {
    const queryWith: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'shallow',
      include_profile: true,
      include_campaigns: false,
      include_communications: false,
      include_journeys: false,
      include_conversions: false,
      include_value: false,
      include_graph: false,
      include_edges: true,
    };
    const queryWithout: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'shallow',
      include_profile: true,
      include_campaigns: false,
      include_communications: false,
      include_journeys: false,
      include_conversions: false,
      include_value: false,
      include_graph: false,
      include_edges: false,
    };
    expect(queryWith.include_edges).toBe(true);
    expect(queryWithout.include_edges).toBe(false);
  });

  it('should accept optional time window filter', () => {
    const query: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'deep',
      include_profile: true,
      include_campaigns: true,
      include_communications: true,
      include_journeys: true,
      include_conversions: true,
      include_value: true,
      include_graph: true,
      time_window: { start: '2024-01-01T00:00:00.000Z', end: '2024-12-31T00:00:00.000Z' },
    };
    expect(query.time_window?.start).toBe('2024-01-01T00:00:00.000Z');
    expect(query.time_window?.end).toBe('2024-12-31T00:00:00.000Z');
  });

  it('should accept optional filters', () => {
    const query: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'deep',
      include_profile: true,
      include_campaigns: true,
      include_communications: true,
      include_journeys: true,
      include_conversions: true,
      include_value: true,
      include_graph: true,
      filters: { plan: 'premium', region: 'US' },
    };
    expect(query.filters?.plan).toBe('premium');
    expect(query.filters?.region).toBe('US');
  });

  it('should accept limit_per_surface', () => {
    const query: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'deep',
      include_profile: true,
      include_campaigns: true,
      include_communications: true,
      include_journeys: true,
      include_conversions: true,
      include_value: true,
      include_graph: true,
      limit_per_surface: 50,
    };
    expect(query.limit_per_surface).toBe(50);
  });

  it('should accept source classification on 360 query', () => {
    const query: Surface360Query = {
      workspace_id: 'w1',
      user_id: 'u1',
      depth: 'deep',
      include_profile: true,
      include_campaigns: true,
      include_communications: true,
      include_journeys: true,
      include_conversions: true,
      include_value: true,
      include_graph: true,
      source: {
        platform: 'web',
        data_type: '360',
        sdk: '@aether/360',
        environment: 'staging',
      },
    };
    expect(query.source?.platform).toBe('web');
    expect(query.source?.data_type).toBe('360');
  });

  it('should read fixture metadata', () => {
    expect(surface360QueryFixture._fixture_version).toBe(1);
    expect(surface360QueryFixture._fixtureName).toBe('surface360QueryFixture');
  });
});
