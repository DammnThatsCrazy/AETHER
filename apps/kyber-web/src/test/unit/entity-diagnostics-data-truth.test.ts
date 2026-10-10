import { describe, expect, it, vi } from 'vitest';
import { mapGraphqlNodeToEntity, mapProfileToEntity } from '@kyber/features/entities/use-entity-data';
import { mapToSystemHealth } from '@kyber/features/diagnostics/use-diagnostics-data';

describe('Kyber entity and diagnostics data truth', () => {
  it('does not manufacture entity timestamps, scores, or conclusions', () => {
    vi.setSystemTime(new Date('2035-01-01T00:00:00Z'));
    const profile = mapProfileToEntity({ user_id: 'entity-a' }, 'entity-a');
    const graph = mapGraphqlNodeToEntity({ id: 'entity-b', type: 'customer' });

    for (const entity of [profile, graph]) {
      expect(entity.createdAt).toBeUndefined();
      expect(entity.updatedAt).toBeUndefined();
      expect(entity.health.lastChecked).toBeUndefined();
      expect(entity.trustScore).toBeNull();
      expect(entity.riskScore).toBeNull();
      expect(entity.anomalyScore).toBeNull();
      expect(entity.needsHelp).toBeNull();
    }
    vi.useRealTimers();
  });

  it('preserves authoritative score zero and observation timestamps', () => {
    const entity = mapProfileToEntity({
      user_id: 'entity-a',
      trust_score: 0,
      risk_score: 0,
      anomaly_score: 0,
      needs_help: false,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-02T00:00:00Z',
      health_observed_at: '2026-01-02T00:01:00Z',
    }, 'entity-a');
    expect(entity.trustScore).toBe(0);
    expect(entity.riskScore).toBe(0);
    expect(entity.anomalyScore).toBe(0);
    expect(entity.needsHelp).toBe(false);
    expect(entity.health.lastChecked).toBe('2026-01-02T00:01:00Z');
  });

  it('does not turn absent diagnostic measurements into healthy zero lag', () => {
    const health = mapToSystemHealth(
      { status: 'unknown', services: { queue: { status: 'unknown' } } },
      { errors: [], count: 0 },
      { queue: { state: 'not-observed', failures: 0 } },
      {},
    );
    expect(health.overall.status).toBe('unknown');
    expect(health.overall.lastChecked).toBeUndefined();
    expect(health.dependencies[0]?.latencyMs).toBeNull();
    expect(health.circuitBreakers[0]?.state).toBe('unknown');
    expect(health.eventLag).toEqual({
      currentMs: null,
      avgMs: null,
      maxMs: null,
      trend: 'unknown',
    });
  });

  it('preserves authoritative diagnostic zero measurements', () => {
    const health = mapToSystemHealth(
      {
        status: 'healthy',
        timestamp: '2026-01-01T00:00:00Z',
        services: { queue: { status: 'healthy', latency_ms: 0 } },
      },
      { errors: [], count: 0 },
      {},
      {
        event_lag: { current_ms: 0, avg_ms: 0, max_ms: 0, trend: 'stable' },
        graph_lag: { current_ms: 0, avg_ms: 0, max_ms: 0, trend: 'stable' },
      },
    );
    expect(health.overall.lastChecked).toBe('2026-01-01T00:00:00Z');
    expect(health.dependencies[0]?.latencyMs).toBe(0);
    expect(health.eventLag.currentMs).toBe(0);
  });
});
