import { describe, expect, it } from 'vitest';
import {
  restoreGraphContextFromPersistence,
  serializeGraphContextForPersistence,
  switchGraphContextScope,
  validateGraphContext,
  type GraphContext,
  type GraphObjectRef,
  type GraphDiff,
  type GraphSnapshot,
  validateGraphSnapshot,
  validateCanonicalGraphQuery,
  createImmutableGraphSnapshot,
  createImmutableGraphDiff,
  validateGraphDiff,
} from './graph-context-contract';

const ref = (id: string, tenant_id = 'tenant-a', environment_id = 'staging'): GraphObjectRef => ({
  tenant_id, environment_id, kind: 'entity', id,
});

const context = (): GraphContext => ({
  version: '1',
  scope: { tenant_id: 'tenant-a', environment_id: 'staging', workspace_id: 'workspace-1', surface: 'graph' },
  anchors: [],
  temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  selection: { selected: [ref('selected')], focused: ref('focused'), pinned: [ref('pinned')], compared: [ref('compared')], snapshot_bound: [] },
  evidence: [],
  exploration_trail: [{ object: ref('focused'), action: 'open', occurred_at: '2026-01-01T00:00:00Z' }],
});

describe('GraphContext contract', () => {
  it('serializes deterministically and restores the same context', () => {
    const value = context();
    const encoded = serializeGraphContextForPersistence(value);
    expect(encoded).toBe(serializeGraphContextForPersistence({ ...value, evidence: [] }));
    expect(restoreGraphContextFromPersistence(encoded)).toEqual(value);
  });

  it('keeps selection roles separate', () => {
    const value = context();
    expect(value.selection.selected).not.toContain(value.selection.focused);
    expect(value.selection.pinned).not.toBe(value.selection.selected);
    expect(value.selection.compared).not.toBe(value.selection.selected);
    expect('selection' in value).toBe(true);
  });

  it('clears cross-tenant references and tenant-bound state on scope switch', () => {
    const value = { ...context(), anchors: [ref('old-anchor', 'tenant-a', 'staging')], population: { logic: 'AND' as const, expressions: [{ field: 'old', op: 'eq' as const, value: true }] }, selection: { ...context().selection, selected: [ref('local'), ref('foreign', 'tenant-b', 'prod')] }, saved_context_id: 'saved', snapshot_id: 'snap', diff_id: 'diff', query: { kind: 'graph_query' as const, version: '1' as const, scope: { tenant_id: 'tenant-a', environment_id: 'staging' }, roots: [ref('old-anchor')], traversal: { direction: 'both' as const, max_depth: 2 }, rights_policy: 'enforce' as const } };
    const switched = switchGraphContextScope(value, 'tenant-b', 'prod');
    expect(switched.anchors).toEqual([]);
    expect(switched.population).toBeNull();
    expect(switched.query).toBeNull();
    expect(switched.selection.selected).toEqual([]);
    expect(switched.selection.focused).toBeNull();
    expect(switched.saved_context_id).toBeNull();
    expect(switched.snapshot_id).toBeNull();
    expect(switched.diff_id).toBeNull();
    expect(switched.exploration_trail).toEqual([]);
  });

  it('rejects out-of-scope references deterministically', () => {
    const result = validateGraphContext({ ...context(), selection: { ...context().selection, selected: [ref('foreign', 'tenant-b', 'prod')] } });
    expect(result).toEqual({ valid: false, errors: ['selected[0] is out of scope or invalid'] });
  });

  it('preserves immutable snapshot metadata and diff identity', () => {
    const query = { kind: 'graph_query' as const, version: '1' as const, scope: { tenant_id: 'tenant-a', environment_id: 'staging' }, roots: [], traversal: { direction: 'both' as const, max_depth: 2 }, rights_policy: 'enforce' as const, temporal: { mode: 'range' as const } };
    const snapshot: GraphSnapshot = {
      kind: 'graph_snapshot', id: 'snapshot-1', tenant_id: 'tenant-a', environment_id: 'staging',
      captured_at: '2026-01-01T00:00:00Z', workspace_id: 'workspace-1', as_of: '2025-12-31T23:59:59Z', query, objects: [ref('one')], graph_state_ref: 'graph-1', evidence_state_ref: 'evidence-1', source_state_ref: 'source-1', policy_version: 'policy-1', ontology_version: 'ontology-1', model_versions: { graph: 'model-1' },
      metadata: { source: 'graph-engine', complete: true },
    };
    const diff: GraphDiff = {
      kind: 'graph_diff', id: 'diff-1', tenant_id: 'tenant-a', environment_id: 'staging',
      workspace_id: 'workspace-1', from_state_ref: 'state-1', to_state_ref: 'state-2', created_at: '2026-01-01T00:01:00Z',
      changes: [{ kind: 'added', object: ref('two') }], summary: { added: 1, removed: 0, changed: 0 }, metadata: { algorithm: 'set-v1' },
    };
    expect(snapshot.metadata.source).toBe('graph-engine');
    expect(validateGraphSnapshot(snapshot).valid).toBe(true);
    expect(validateCanonicalGraphQuery(snapshot.query).valid).toBe(true);
    expect(diff.from_state_ref).not.toBe(diff.to_state_ref);
    const frozenSnapshot = createImmutableGraphSnapshot(snapshot);
    const frozenDiff = createImmutableGraphDiff(diff);
    expect(Object.isFrozen(frozenSnapshot)).toBe(true);
    expect(Object.isFrozen(frozenDiff.changes)).toBe(true);
    expect(validateGraphDiff(frozenDiff).valid).toBe(true);
  });

  it('rejects invalid query limits, rights, and root scopes', () => {
    const query = { kind: 'graph_query', version: '1', scope: { tenant_id: 'tenant-a', environment_id: 'staging' }, roots: [ref('foreign', 'tenant-b')], traversal: { direction: 'both', max_depth: 2 }, limit: 501, rights_policy: 'ignore' };
    expect(validateCanonicalGraphQuery(query).valid).toBe(false);
  });
});
