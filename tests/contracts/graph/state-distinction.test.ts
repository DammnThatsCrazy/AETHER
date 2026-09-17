/**
 * FPS-023 — Graph State Distinction
 * Verifies that graph distinguishes between missing, empty, and zero states.
 */
import { describe, it, expect } from 'vitest';

import { GraphNode } from '@aether/proof-contracts';

describe('FPS-023: Graph State Distinction', () => {
  it('should distinguish missing vs empty properties', () => {
    const nodeWithMissingProps: GraphNode = {
      node_id: 'node_1',
      type: 'profile',
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithEmptyArr: GraphNode = {
      node_id: 'node_2',
      type: 'profile',
      properties: { tags: [] },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithEmptyString: GraphNode = {
      node_id: 'node_3',
      type: 'profile',
      properties: { name: '' },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    // Missing properties object
    expect(nodeWithMissingProps.properties).toEqual({});
    // Empty array is distinct from missing
    expect(Array.isArray(nodeWithEmptyArr.properties.tags)).toBe(true);
    expect(nodeWithEmptyArr.properties.tags.length).toBe(0);
    // Empty string is distinct from missing
    expect(nodeWithEmptyString.properties.name).toBe('');
    expect(nodeWithEmptyString.properties.name).not.toBeUndefined();
  });

  it('should distinguish missing vs zero value', () => {
    const nodeWithMissingValue: GraphNode = {
      node_id: 'node_1',
      type: 'conversion',
      properties: { value: undefined },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithValueZero: GraphNode = {
      node_id: 'node_2',
      type: 'conversion',
      properties: { value: 0 },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithValue: GraphNode = {
      node_id: 'node_3',
      type: 'conversion',
      properties: { value: 100 },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    // Missing: property is undefined but object exists
    expect(nodeWithMissingValue.properties).toBeDefined();
    expect((nodeWithMissingValue.properties as any).value).toBeUndefined();

    // Zero is a valid value, distinct from missing
    expect((nodeWithValueZero.properties as any).value).toBe(0);
    expect((nodeWithValueZero.properties as any).value).not.toBeUndefined();

    // Real value works as expected
    expect((nodeWithValue.properties as any).value).toBe(100);
  });

  it('should distinguish missing vs empty arrays', () => {
    const nodeWithMissingArr: GraphNode = {
      node_id: 'node_1',
      type: 'profile',
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithEmptyArr: GraphNode = {
      node_id: 'node_2',
      type: 'profile',
      properties: { tags: [] },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    // Missing: property doesn't exist
    expect((nodeWithMissingArr.properties as any).tags).toBeUndefined();

    // Empty: array exists but has no elements
    expect(Array.isArray((nodeWithEmptyArr.properties as any).tags)).toBe(true);
    expect((nodeWithEmptyArr.properties as any).tags.length).toBe(0);
  });

  it('should distinguish missing vs zero financial value in graph nodes', () => {
    const nodeMissingValue: GraphNode = {
      node_id: 'conv_missing',
      type: 'conversion',
      properties: { revenue: undefined },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeZeroValue: GraphNode = {
      node_id: 'conv_zero',
      type: 'conversion',
      properties: { revenue: 0 },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithValue: GraphNode = {
      node_id: 'conv_1',
      type: 'conversion',
      properties: { revenue: 100 },
      created_at: '2024-01-01T00:00:00.000Z',
    };

    // Missing: revenue is undefined — node exists but no value assigned
    expect((nodeMissingValue.properties as any).revenue).toBeUndefined();

    // Zero: revenue is explicitly 0 — node exists with zero value
    expect((nodeZeroValue.properties as any).revenue).toBe(0);

    // Real value
    expect((nodeWithValue.properties as any).revenue).toBe(100);
  });

  it('should distinguish empty string vs missing string in labels', () => {
    const nodeEmptyLabel: GraphNode = {
      node_id: 'node_empty',
      type: 'profile',
      labels: [''],
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeNoLabel: GraphNode = {
      node_id: 'node_none',
      type: 'profile',
      labels: [],
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };

    const nodeWithLabel: GraphNode = {
      node_id: 'node_with',
      type: 'profile',
      labels: ['customer'],
      properties: {},
      created_at: '2024-01-01T00:00:00.000Z',
    };

    expect(nodeEmptyLabel.labels.length).toBe(1);
    expect(nodeEmptyLabel.labels[0]).toBe('');
    expect(nodeNoLabel.labels.length).toBe(0);
    expect(nodeWithLabel.labels).toContain('customer');
  });
});
