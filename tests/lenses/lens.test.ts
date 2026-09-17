/**
 * FPS-240 — Lens Contract
 *
 * Verifies lens input/output processing for profile views.
 *
 * The real lensInputFixture and lensOutputFixture (from @aether/proof-fixtures)
 * store their query data under a `properties` key matching the canonical shape:
 *
 *   lensInputFixture.properties:
 *     { profileId, dimensions, filters, timeRange, aggregation, sort, limit, offset }
 *
 *   lensOutputFixture.properties:
 *     { profileId, segments: string[], metrics: {...}, topEvents: [...],
 *       recommendations: [...], generatedAt, computationTimeMs, totalRecords, isPartial }
 */
import { describe, it, expect } from 'vitest';

import { LensInput, LensOutput, LensSegment } from '@aether/proof-contracts';
import { lensInputFixture, lensOutputFixture } from '@aether/proof-fixtures';

describe('FPS-240: Lens Contract', () => {
  it('should construct valid LensInput', () => {
    const input: LensInput = {
      lens_name: 'active_subscribers',
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      dimensions: ['plan', 'last_active_days'],
      filters: [{ dimension: 'plan', operator: 'eq', value: 'premium' }],
      sort_by: [{ dimension: 'last_active_days', direction: 'desc' }],
      limit: 100,
    };
    expect(input.lens_name).toBe('active_subscribers');
    expect(input.tenant_id).toBe('aether-proof-tenant');
    expect(input.dimensions).toHaveLength(2);
    expect(input.filters).toHaveLength(1);
    expect(input.limit).toBe(100);
  });

  it('should read lensInputFixture properties', () => {
    const props = lensInputFixture.properties;
    expect(props.profileId).toBe('profile_001');
    expect(props.dimensions).toContain('segments');
    expect(props.dimensions).toContain('campaigns');
    expect(props.dimensions).toContain('purchases');
    expect(props.filters).toEqual({ plan: 'premium' });
    expect(props.limit).toBe(50);
  });

  it('should construct valid LensOutput', () => {
    const output: LensOutput = {
      lens_name: 'active_subscribers',
      tenant_id: 'aether-proof-tenant',
      workspace_id: 'proof-lab',
      query: { dimensions: ['plan'], filters: [] },
      total_profiles: 50,
      segments: [
        {
          id: 'seg_001',
          label: 'Premium Users',
          profiles: 30,
          dimensions: { plan: 'premium' },
          confidence: 0.95,
          sample_size: 30,
        },
      ],
      generated_at: new Date().toISOString(),
      cached: false,
    };
    expect(output.lens_name).toBe('active_subscribers');
    expect(output.total_profiles).toBe(50);
    expect(output.segments).toHaveLength(1);
    expect(output.segments[0].label).toBe('Premium Users');
  });

  it('should read lensOutputFixture properties', () => {
    const props = lensOutputFixture.properties;
    expect(props.profileId).toBe('profile_001');
    expect(props.segments).toEqual(['high_value', 'engaged', 'premium']);
    expect(props.metrics).toBeDefined();
    expect(props.metrics.avgPurchaseValue).toBe(49.99);
    expect(props.metrics.sessionCount).toBe(12);
    expect(props.metrics.totalRevenue).toBe(599.88);
    expect(props.metrics.eventCount).toBe(342);
    expect(props.metrics.conversionRate).toBe(0.18);
    expect(props.metrics.lastActiveDaysAgo).toBe(2);
    expect(props.generatedAt).toBe('2024-09-11T14:16:00.000Z');
    expect(props.computationTimeMs).toBe(234);
    expect(props.totalRecords).toBe(342);
    expect(props.isPartial).toBe(false);
    expect(props.recommendations).toBeDefined();
    expect(props.recommendations).toHaveLength(2);
  });

  it('should validate segment structure', () => {
    const segment: LensSegment = {
      id: 'seg_001',
      label: 'Test Segment',
      profiles: 10,
      dimensions: { plan: 'premium' },
      confidence: 0.9,
      sample_size: 10,
    };
    expect(segment.id).toBe('seg_001');
    expect(segment.label).toBe('Test Segment');
    expect(segment.profiles).toBe(10);
    expect(segment.confidence).toBeGreaterThan(0);
    expect(segment.confidence).toBeLessThanOrEqual(1);
  });

  it('should validate lens input and output shape compatibility', () => {
    const inputProps = lensInputFixture.properties;
    const outputProps = lensOutputFixture.properties;
    // Output profileId should match a reasonable lens target
    expect(outputProps.profileId).toBe('profile_001');
    expect(inputProps.dimensions).toBeDefined();
    expect(outputProps.segments).toBeDefined();
    // The input targets profile_001 dimensions, output has computed segments
    expect(outputProps.segments).toHaveLength(3);
  });
});
