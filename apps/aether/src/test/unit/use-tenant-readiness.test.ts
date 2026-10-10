import { describe, expect, it } from 'vitest';
import {
  deriveGraphMaturity,
  tenantReadinessQueryKey,
  type GraphReadinessCheck,
} from '@aether-app/features/activation/use-tenant-readiness';
import type { TenantReadinessResponse } from '@aether-app/lib/api/endpoints';

const checks = (overrides: Partial<Record<GraphReadinessCheck, TenantReadinessResponse['checks'][number]['status']>> = {}) =>
  Object.entries({
    events_received: 'pending',
    identity_resolution_verified: 'pending',
    graph_projection_verified: 'pending',
    profile360_verified: 'pending',
    data_quality_verified: 'pending',
    ...overrides,
  }).map(([name, status]) => ({ name, status, evidence: {} })) as TenantReadinessResponse['checks'];

const response = (overrides: Partial<TenantReadinessResponse> = {}): TenantReadinessResponse => ({
  tenant_id: 'tenant-test',
  checks: checks(),
  ready: false,
  blocking: [],
  ...overrides,
});

describe('deriveGraphMaturity', () => {
  it('reports no_data until events_received is satisfied', () => {
    expect(deriveGraphMaturity(response())).toEqual({
      state: 'no_data',
      blocking: [
        'events_received',
        'identity_resolution_verified',
        'graph_projection_verified',
        'profile360_verified',
        'data_quality_verified',
      ],
    });
  });

  it('reports building when events exist but graph requirements block readiness', () => {
    expect(deriveGraphMaturity(response({ checks: checks({ events_received: 'passed', graph_projection_verified: 'failed' }) }))).toEqual({
      state: 'building',
      blocking: ['identity_resolution_verified', 'graph_projection_verified', 'profile360_verified', 'data_quality_verified'],
    });
  });

  it('reports ready when every named requirement is passed or not_applicable', () => {
    expect(deriveGraphMaturity(response({
      ready: true,
      checks: checks({
        events_received: 'passed',
        identity_resolution_verified: 'passed',
        graph_projection_verified: 'passed',
        profile360_verified: 'not_applicable',
        data_quality_verified: 'passed',
      }),
    }))).toEqual({ state: 'ready', blocking: [] });
  });

  it('keeps failed events in the explicit no_data state', () => {
    expect(deriveGraphMaturity(response({ checks: checks({ events_received: 'failed' }) }))).toEqual({
      state: 'no_data',
      blocking: ['events_received', 'identity_resolution_verified', 'graph_projection_verified', 'profile360_verified', 'data_quality_verified'],
    });
  });
});

describe('tenant readiness cache scope', () => {
  it('partitions readiness responses by authenticated tenant and session scope', () => {
    expect(tenantReadinessQueryKey('snapshot', 'tenant/a', 'principal:1'))
      .toBe('tenant:readiness:snapshot:tenant%2Fa:principal%3A1');
    expect(tenantReadinessQueryKey('snapshot', 'tenant/a', 'principal:2'))
      .not.toBe(tenantReadinessQueryKey('snapshot', 'tenant/a', 'principal:1'));
    expect(tenantReadinessQueryKey('trust-states', 'tenant/b', 'principal:1'))
      .not.toBe(tenantReadinessQueryKey('snapshot', 'tenant/a', 'principal:1'));
  });
});
