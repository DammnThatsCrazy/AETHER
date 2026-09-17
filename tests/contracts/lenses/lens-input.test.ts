/**
 * FPS-023 — Lens Input Contract
 * Verifies lens input schema for profile dimension queries.
 */
import { describe, it, expect } from 'vitest';

import { LensInput } from '@aether/proof-contracts';
import { lensInputFixture } from '@aether/proof-fixtures';

describe('FPS-023: Lens Input', () => {
  it('should construct a valid lens input from fixture', () => {
    const fixtureProps = lensInputFixture.properties || {};
    expect(fixtureProps.profileId).toBe('profile_001');
    expect(fixtureProps.dimensions).toEqual(['segments', 'campaigns', 'purchases']);
    expect(fixtureProps.filters).toEqual({ plan: 'premium' });
    expect(fixtureProps.timeRange).toBeDefined();
    expect(fixtureProps.timeRange?.start).toBe('2024-09-01T00:00:00.000Z');
    expect(fixtureProps.timeRange?.end).toBe('2024-09-11T00:00:00.000Z');
  });

  it('should accept lens input with workspace_id from contract', () => {
    const input: LensInput = {
      workspace_id: 'proof-lab',
      lens_name: 'profile_segments',
      event_types: ['page', 'identify', 'order_completed'],
      time_window: { start: '2024-09-01T00:00:00.000Z', end: '2024-09-11T00:00:00.000Z' },
      filters: { plan: 'premium' },
      group_by: ['segments'],
      aggregations: [{ metric: 'count', field: 'events', operation: 'sum' }],
      sort: [{ field: 'count', direction: 'desc' }],
      limit: 50,
      offset: 0,
    };
    expect(input.workspace_id).toBe('proof-lab');
    expect(input.lens_name).toBe('profile_segments');
    expect(input.event_types?.length).toBe(3);
    expect(input.aggregations?.length).toBe(1);
  });

  it('should accept empty dimensions for full profile', () => {
    const input: LensInput = {
      workspace_id: 'w1',
      lens_name: 'full_profile',
      group_by: [],
    };
    expect(input.group_by?.length).toBe(0);
  });

  it('should accept empty filters', () => {
    const input: LensInput = {
      workspace_id: 'w1',
      lens_name: 'no_filter',
      filters: undefined,
    };
    expect(input.filters).toBeUndefined();
  });

  it('should validate time window is ordered', () => {
    const input: LensInput = {
      workspace_id: 'w1',
      lens_name: 'time_range_test',
      time_window: { start: '2024-01-01T00:00:00.000Z', end: '2024-12-31T00:00:00.000Z' },
    };
    const start = new Date(input.time_window?.start || '');
    const end = new Date(input.time_window?.end || '');
    expect(start.getTime()).toBeLessThan(end.getTime());
  });

  it('should accept aggregations with various operations', () => {
    const input: LensInput = {
      workspace_id: 'w1',
      lens_name: 'agg_test',
      aggregations: [
        { metric: 'count', field: 'events', operation: 'sum' },
        { metric: 'revenue', field: 'value', operation: 'avg' },
        { metric: 'distinct', field: 'users', operation: 'distinct' },
      ],
    };
    expect(input.aggregations?.length).toBe(3);
    expect(input.aggregations?.[0].operation).toBe('sum');
    expect(input.aggregations?.[1].operation).toBe('avg');
  });

  it('should accept sort configuration', () => {
    const input: LensInput = {
      workspace_id: 'w1',
      lens_name: 'sort_test',
      sort: [
        { field: 'count', direction: 'desc' },
        { field: 'name', direction: 'asc' },
      ],
    };
    expect(input.sort?.length).toBe(2);
    expect(input.sort?.[0].direction).toBe('desc');
  });

  it('should read fixture _fixture_version', () => {
    expect(lensInputFixture._fixture_version).toBe(1);
    expect(lensInputFixture._fixtureName).toBe('lensInputFixture');
  });

  it('should accept source classification on lens input', () => {
    const input: LensInput = {
      workspace_id: 'w1',
      lens_name: 'scoped_lens',
      source: {
        platform: 'web',
        data_type: 'lens',
        platform_id: 'webapp',
        sdk: '@aether/lens',
        environment: 'staging',
      },
    };
    expect(input.source?.platform).toBe('web');
    expect(input.source?.data_type).toBe('lens');
  });
});
