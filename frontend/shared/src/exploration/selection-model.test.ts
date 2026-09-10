import { describe, expect, it } from 'vitest';
import { bindSnapshot, clearSelection, createSelectionState, focusObject, replaceSelection, selectObject, setCompared, togglePin } from './selection-model';
import type { GraphObjectRef } from '@aether/shared/graph-context-contract';

const scope = { tenant_id: 't1', workspace_id: 'w1', environment_id: 'staging' } as const;
const ref = (id: string, extra = {}): GraphObjectRef => ({ ...scope, kind: 'entity', id, ...extra });
const other = ref('x', { tenant_id: 't2' });
const snapshot = { ...scope, snapshot_id: 's1' };

describe('selection model', () => {
  it('keeps focus independent from selected objects', () => {
    const state = focusObject(createSelectionState(), ref('focus'), scope);
    expect(state.focused).toEqual(ref('focus'));
    expect(state.selected).toEqual([]);
    expect(selectObject(state, ref('selected'), scope).focused).toEqual(ref('focus'));
  });
  it('fails closed for cross-scope objects and snapshots', () => {
    expect(() => selectObject(createSelectionState(), other, scope)).toThrow();
    expect(() => bindSnapshot(createSelectionState(), { ...snapshot, environment_id: 'prod' }, scope)).toThrow();
  });
  it('deduplicates and does not mutate inputs', () => {
    const state = createSelectionState({ selected: [ref('a')] });
    const next = replaceSelection(state, [ref('a'), ref('a'), ref('b')], scope);
    expect(next.selected.map((item) => item.id)).toEqual(['a', 'b']);
    expect(state.selected).toHaveLength(1);
  });
  it('supports independent pin, compare, snapshot, and clear operations', () => {
    let state = togglePin(createSelectionState(), ref('p'), scope);
    state = setCompared(state, [ref('c')], scope);
    state = bindSnapshot(state, snapshot, scope);
    expect(state.pinned).toHaveLength(1); expect(state.compared).toHaveLength(1); expect(state.snapshot_bound).toHaveLength(1);
    expect(clearSelection(state, scope)).toEqual(createSelectionState());
  });
});
