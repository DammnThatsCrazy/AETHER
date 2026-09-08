import type {
  GraphObjectRef,
  GraphSelectionState,
  GraphSnapshotRef,
} from '@aether/shared/graph-context-contract';

export interface SelectionScope {
  readonly tenant_id: string;
  readonly environment_id: string;
}

export const EMPTY_SELECTION: GraphSelectionState = {
  selected: [],
  focused: null,
  pinned: [],
  compared: [],
  snapshot_bound: [],
};

export function createSelectionState(initial: Partial<GraphSelectionState> = {}): GraphSelectionState {
  const state: GraphSelectionState = {
    selected: [...(initial.selected ?? [])],
    focused: initial.focused ?? null,
    pinned: [...(initial.pinned ?? [])],
    compared: [...(initial.compared ?? [])],
    snapshot_bound: [...(initial.snapshot_bound ?? [])],
  };
  return state;
}

const sameObject = (a: GraphObjectRef, b: GraphObjectRef): boolean =>
  a.tenant_id === b.tenant_id && a.environment_id === b.environment_id && a.kind === b.kind && a.id === b.id;
const sameSnapshot = (a: GraphSnapshotRef, b: GraphSnapshotRef): boolean =>
  a.tenant_id === b.tenant_id && a.environment_id === b.environment_id && a.snapshot_id === b.snapshot_id;

function inScope(ref: GraphObjectRef, scope: SelectionScope): boolean {
  return Boolean(ref && ref.tenant_id && ref.environment_id && ref.kind && ref.id &&
    ref.tenant_id === scope.tenant_id && ref.environment_id === scope.environment_id);
}
function snapshotInScope(ref: GraphSnapshotRef, scope: SelectionScope): boolean {
  return Boolean(ref && ref.tenant_id && ref.environment_id && ref.snapshot_id &&
    ref.tenant_id === scope.tenant_id && ref.environment_id === scope.environment_id);
}
function requireObject(ref: GraphObjectRef, scope: SelectionScope): void {
  if (!inScope(ref, scope)) throw new Error('Graph object reference is outside the active scope');
}
function requireSnapshot(ref: GraphSnapshotRef, scope: SelectionScope): void {
  if (!snapshotInScope(ref, scope)) throw new Error('Graph snapshot reference is outside the active scope');
}
function objectsInScope(state: GraphSelectionState, scope: SelectionScope): void {
  [...state.selected, ...state.pinned, ...state.compared].forEach((ref) => requireObject(ref, scope));
  if (state.focused) requireObject(state.focused, scope);
  state.snapshot_bound.forEach((ref) => requireSnapshot(ref, scope));
}
function objectList(state: GraphSelectionState, key: 'selected' | 'pinned' | 'compared', ref: GraphObjectRef, add: boolean): GraphSelectionState {
  const values = state[key].filter((item) => !sameObject(item, ref));
  return { ...state, [key]: add ? [...values, ref] : values };
}

export function selectObject(state: GraphSelectionState, ref: GraphObjectRef, scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); requireObject(ref, scope); return objectList(state, 'selected', ref, true);
}
export function unselectObject(state: GraphSelectionState, ref: GraphObjectRef, scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); requireObject(ref, scope); return objectList(state, 'selected', ref, false);
}
export function replaceSelection(state: GraphSelectionState, refs: readonly GraphObjectRef[], scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); refs.forEach((ref) => requireObject(ref, scope));
  const selected = refs.filter((ref, index) => refs.findIndex((candidate) => sameObject(candidate, ref)) === index);
  return { ...state, selected };
}
export function focusObject(state: GraphSelectionState, ref: GraphObjectRef | null, scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); if (ref) requireObject(ref, scope); return { ...state, focused: ref };
}
export function togglePin(state: GraphSelectionState, ref: GraphObjectRef, scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); requireObject(ref, scope); return objectList(state, 'pinned', ref, !state.pinned.some((item) => sameObject(item, ref)));
}
export function setCompared(state: GraphSelectionState, refs: readonly GraphObjectRef[] | GraphObjectRef, scope: SelectionScope): GraphSelectionState {
  const values = Array.isArray(refs) ? refs : [refs];
  objectsInScope(state, scope); values.forEach((ref) => requireObject(ref, scope));
  const compared = values.filter((ref, index) => values.findIndex((candidate) => sameObject(candidate, ref)) === index);
  return { ...state, compared };
}
export function bindSnapshot(state: GraphSelectionState, ref: GraphSnapshotRef, scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); requireSnapshot(ref, scope);
  return state.snapshot_bound.some((item) => sameSnapshot(item, ref)) ? { ...state, snapshot_bound: [...state.snapshot_bound] } : { ...state, snapshot_bound: [...state.snapshot_bound, ref] };
}
export function unbindSnapshot(state: GraphSelectionState, ref: GraphSnapshotRef, scope: SelectionScope): GraphSelectionState {
  objectsInScope(state, scope); requireSnapshot(ref, scope); return { ...state, snapshot_bound: state.snapshot_bound.filter((item) => !sameSnapshot(item, ref)) };
}
export function clearSelection(state: GraphSelectionState, scope: SelectionScope): GraphSelectionState {
  // Scope is deliberately required so callers cannot accidentally clear into an
  // unrelated scope while reusing a stale state object.
  objectsInScope(state, scope);
  return createSelectionState();
}

// Short names are convenient for reducer-style callers.
export const select = selectObject;
export const unselect = unselectObject;
export const focus = focusObject;
export const clear = clearSelection;
