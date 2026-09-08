import { describe, expect, it } from 'vitest';
import {
  restoreGraphContext,
  serializeGraphContext,
  switchGraphContextScope,
  validateGraphContext,
  type GraphContext,
  type GraphObjectRef,
  type GraphDiff,
  type GraphSnapshot,
} from './graph-context-contract';

const ref = (id: string, tenant_id = 'tenant-a', environment_id = 'staging'): GraphObjectRef => ({
  tenant_id, environment_id, kind: 'entity', id,
});

const context = (): GraphContext => ({
  version: '1',
  scope: { tenant_id: 'tenant-a', environment_id: 'staging', surface: 'graph' },
  temporal: { mode: 'window', field: 'occurred_at', timezone: 'UTC' },
  selected: [ref('selected')],
  focused: ref('focused'),
  pinned: [ref('pinned')],
  compared: [ref('compared')],
  evidence: [],
  exploration_trail: [{ object: ref('focused'), action: 'open', occurred_at: '2026-01-01T00:00:00Z' }],
});

describe('GraphContext contract', () => {
  it('serializes deterministically and restores the same context', () => {
    const value = context();
    const encoded = serializeGraphContext(value);
    expect(encoded).toBe(serializeGraphContext({ ...value, evidence: [] }));
    expect(restoreGraphContext(encoded)).toEqual(value);
  });

  it('keeps selection roles separate', () => {
    const value = context();
    expect(value.selected).not.toContain(value.focused);
    expect(value.pinned).not.toBe(value.selected);
    expect(value.compared).not.toBe(value.selected);
  });

  it('clears cross-tenant references and tenant-bound state on scope switch', () => {
    const value = { ...context(), selected: [ref('local'), ref('foreign', 'tenant-b', 'prod')], saved_context_id: 'saved', snapshot_id: 'snap', diff_id: 'diff' };
    const switched = switchGraphContextScope(value, 'tenant-b', 'prod');
    expect(switched.selected).toEqual([ref('foreign', 'tenant-b', 'prod')]);
    expect(switched.focused).toBeNull();
    expect(switched.saved_context_id).toBeNull();
    expect(switched.snapshot_id).toBeNull();
    expect(switched.diff_id).toBeNull();
    expect(switched.exploration_trail).toEqual([]);
  });

  it('rejects out-of-scope references deterministically', () => {
    const result = validateGraphContext({ ...context(), selected: [ref('foreign', 'tenant-b', 'prod')] });
    expect(result).toEqual({ valid: false, errors: ['selected[0] is out of scope or invalid'] });
  });

  it('preserves immutable snapshot metadata and diff identity', () => {
    const query = { kind: 'graph_query' as const, version: '1' as const, scope: { tenant_id: 'tenant-a', environment_id: 'staging' } };
    const snapshot: GraphSnapshot = {
      kind: 'graph_snapshot', id: 'snapshot-1', tenant_id: 'tenant-a', environment_id: 'staging',
      captured_at: '2026-01-01T00:00:00Z', as_of: '2025-12-31T23:59:59Z', query, objects: [ref('one')],
      metadata: { source: 'graph-engine', complete: true },
    };
    const diff: GraphDiff = {
      kind: 'graph_diff', id: 'diff-1', tenant_id: 'tenant-a', environment_id: 'staging',
      from_snapshot_id: 'snapshot-1', to_snapshot_id: 'snapshot-2', created_at: '2026-01-01T00:01:00Z',
      added: [ref('two')], removed: [], unchanged: [ref('one')], metadata: { algorithm: 'set-v1' },
    };
    expect(snapshot.metadata.source).toBe('graph-engine');
    expect(diff.from_snapshot_id).toBe(snapshot.id);
    expect(diff.id).not.toBe(diff.from_snapshot_id);
  });
});
