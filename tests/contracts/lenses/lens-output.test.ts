/**
 * FPS-023 — Lens Output Contract
 * Verifies lens output schema for profile dimension queries.
 *
 * The real lensOutputFixture (from @aether/proof-fixtures) stores its query
 * data under a `properties` key. Tests below validate both the fixture shape
 * and constructed LensOutput objects against the @aether/proof-contracts type.
 */
import { describe, it, expect } from 'vitest';

import { LensOutput, LensSegment } from '@aether/proof-contracts';
import { lensOutputFixture } from '@aether/proof-fixtures';

describe('FPS-023: Lens Output', () => {
  it('should read lensOutputFixture properties', () => {
    const props = lensOutputFixture.properties;
    expect(props.profileId).toBe('profile_001');
    expect(props.segments).toEqual(['high_value', 'engaged', 'premium']);
    expect(props.metrics).toBeDefined();
    expect(props.metrics.avgPurchaseValue).toBe(49.99);
    expect(props.metrics.sessionCount).toBe(12);
    expect(props.metrics.totalRevenue).toBe(599.88);
    expect(props.metrics.eventCount).toBe(342);
    expect(props.generatedAt).toBe('2024-09-11T14:16:00.000Z');
    expect(props.computationTimeMs).toBe(234);
    expect(props.totalRecords).toBe(342);
    expect(props.isPartial).toBe(false);
  });

  it('should include computed metrics in contract output', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'profile_metrics',
      metrics: {
        avgPurchaseValue: 49.99,
        sessionCount: 12,
        arpu: 125.5,
        churnRisk: 0.15,
      },
      generated_at: '2024-09-11T14:16:00.000Z',
    };
    expect(output.metrics.avgPurchaseValue).toBe(49.99);
    expect(output.metrics.sessionCount).toBe(12);
    expect(output.metrics.arpu).toBe(125.5);
  });

  it('should include top_events ranked by frequency', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'event_breakdown',
      top_events: [
        { event_type: 'page', count: 120, percentage: 0.35 },
        { event_type: 'identify', count: 45, percentage: 0.13 },
        { event_type: 'order_completed', count: 27, percentage: 0.08 },
      ],
      generated_at: '2024-09-11T14:16:00.000Z',
    };
    expect(output.top_events).toHaveLength(3);
    expect(output.top_events[0].event_type).toBe('page');
    expect(output.top_events[0].count).toBe(120);
    expect(output.top_events[0].percentage).toBe(0.35);
  });

  it('should include segments with segment details', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'segment_analysis',
      segments: [
        {
          id: 'seg_high_value',
          label: 'High Value',
          profiles: 150,
          dimensions: { plan: 'premium' },
          confidence: 0.95,
          sample_size: 150,
        },
      ],
      generated_at: '2024-09-11T14:16:00.000Z',
    };
    expect(output.segments).toHaveLength(1);
    const seg = output.segments[0];
    expect(seg.id).toBe('seg_high_value');
    expect(seg.label).toBe('High Value');
    expect(seg.profiles).toBe(150);
    expect(seg.confidence).toBe(0.95);
  });

  it('should include empty recommendations when none available', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'no_recommendations',
      metrics: {},
      recommendations: [],
      generated_at: '2024-09-11T14:16:00.000Z',
    };
    expect(output.recommendations).toEqual([]);
  });

  it('should record generation timestamp', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'timing_test',
      metrics: {},
      generated_at: '2024-09-11T14:00:00.000Z',
    };
    expect(output.generated_at).toBe('2024-09-11T14:00:00.000Z');
  });

  it('should accept is_partial flag', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'partial_test',
      metrics: {},
      generated_at: '2024-09-11T14:16:00.000Z',
      is_partial: true,
      total_records: 100,
    };
    expect(output.is_partial).toBe(true);
    expect(output.total_records).toBe(100);
  });

  it('should accept warnings array', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'warning_test',
      metrics: {},
      warnings: ['Data source A had 5% missing values', 'Time window truncated'],
      generated_at: '2024-09-11T14:16:00.000Z',
    };
    expect(output.warnings).toHaveLength(2);
    expect(output.warnings[0]).toContain('missing values');
  });

  it('should read fixture metadata', () => {
    expect(lensOutputFixture._fixture_version).toBe(1);
    expect(lensOutputFixture._fixtureName).toBe('lensOutputFixture');
  });

  it('should accept source classification on lens output', () => {
    const output: LensOutput = {
      workspace_id: 'w1',
      lens_name: 'scoped_output',
      metrics: {},
      generated_at: '2024-09-11T14:16:00.000Z',
      source: {
        platform: 'lens',
        data_type: 'lens',
        sdk: '@aether/lens',
        environment: 'staging',
      },
    };
    expect(output.source?.platform).toBe('lens');
    expect(output.source?.data_type).toBe('lens');
  });
});
