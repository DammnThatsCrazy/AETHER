import { describe, expect, it } from 'vitest';
import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import {
  canonicalGraphQueryToUniversalRequest,
  explorationContextToCanonicalGraphQuery,
  explorationContextToGraphContext,
  graphScopeAuthorityKey,
  graphScopeChangeRequiresReset,
} from './graph-context-adapter';

const scope = { tenant_id: 'tenant-a', workspace_id: 'workspace-a', environment_id: 'prod' } as const;
const context: ExplorationContextV1 = {
  version: '1', scope: { tenant_id: 'tenant-a', surface: 'graph' },
  anchors: [{ kind: 'entity', id: 'root-1' }],
  population: { logic: 'AND', expressions: [{ field: 'risk.risk_score', op: 'gte', value: 0.8 }] },
  temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC', range: { kind: 'instant', start: '2025-01-01T00:00:00Z', endExclusive: '2025-01-02T00:00:00Z' } },
  graph: { layers: ['identity'], edge_types: ['related_to'], depth: 3 },
  dimensions: ['entity'], lens_set: ['risk-v1'], temporal_mode: 'live',
  presentation: { view: 'graph', sort: [{ field: 'risk.risk_score', direction: 'desc' }] },
  truth: { include_evidence: true },
};

describe('graph context adapter', () => {
  it('rejects absent host scope and tenant authority from URL context', () => {
    expect(() => explorationContextToGraphContext(context, { ...scope, tenant_id: '' })).toThrow('host scope tenant_id');
    expect(() => explorationContextToGraphContext({ ...context, scope: { ...context.scope, tenant_id: 'foreign' } }, scope)).toThrow('tenant');
  });

  it('provides a stable authority key and resets on any scope boundary', () => {
    expect(graphScopeAuthorityKey(scope)).toBe(graphScopeAuthorityKey({ ...scope }));
    expect(graphScopeChangeRequiresReset(scope, { ...scope, workspace_id: 'other' })).toBe(true);
    expect(graphScopeChangeRequiresReset(scope, { ...scope, environment_id: 'staging' })).toBe(true);
    expect(graphScopeChangeRequiresReset(scope, scope)).toBe(false);
  });

  it('maps roots, FilterGroup, graph constraints, temporal state, evidence, and lens IDs', () => {
    const result = explorationContextToGraphContext(context, scope, { projection_id: 'network' as never });
    expect(result.anchors[0]).toMatchObject({ tenant_id: 'tenant-a', environment_id: 'prod', id: 'root-1' });
    expect(result.selection).toEqual({ selected: [], focused: null, pinned: [], compared: [], snapshot_bound: [] });
    const query = explorationContextToCanonicalGraphQuery(context, scope);
    expect(query.predicates).toEqual(context.population);
    expect(query.layers).toEqual(['identity']);
    expect(query.temporal).toMatchObject({ mode: 'range', range: context.temporal.range });
    expect(result.lens_set).toEqual(['risk-v1']);
  });

  it('fails closed for roots carrying a foreign scope', () => {
    const foreign = { ...context, anchors: [{ kind: 'entity', id: 'x', tenant_id: 'foreign' } as never] };
    expect(() => explorationContextToCanonicalGraphQuery(foreign, scope)).toThrow('out of host scope');
  });

  it('returns explicit loss report for legacy request gaps', () => {
    const query = explorationContextToCanonicalGraphQuery(context, scope, { rights_policy: 'explain', aggregation: { group_by: ['entity'], measures: ['count'] } });
    const result = canonicalGraphQueryToUniversalRequest(query);
    expect(result.loss_report.lost_fields).toEqual(expect.arrayContaining(['rights', 'ordering', 'aggregation']));
    expect(result.request.tenant_id).toBe('tenant-a');
    expect(result.request.filter).toEqual(context.population);
  });
});
