/**
 * Exploration store — one ExplorationContextV1 + its last result envelope +
 * fetch status, built on the shared store primitive. The URL is the
 * authoritative source of the context (see url-codec); this store is the
 * in-memory mirror the provider keeps in sync and the components read/mutate.
 * Every filter mutation is validated against the field registry, so the store
 * can never hold a filter the contract does not recognise.
 */

import { createStore, useStore, type Store } from '../state/index';
import type {
  ExplorationContextV1,
  ExplorationResultEnvelope,
  PresentationSpec,
} from '@aether/shared/exploration-contract';
import type {
  GraphContext,
  GraphObjectRef,
  GraphScope,
  GraphSelectionState,
  ExplorationTrailEntry,
  GraphSnapshotRef,
} from '@aether/shared/graph-context-contract';
import { validateGraphContext } from '@aether/shared/graph-context-contract';
import type { FilterExpression, FilterGroup } from '@aether/shared/graph-contract';
import { isKnownField, isOperatorValidForField } from './registry';
import {
  explorationContextToGraphContext,
  graphScopeAuthorityKey,
  graphScopeChangeRequiresReset,
} from './graph-context-adapter';
import {
  bindSnapshot,
  clearSelection,
  createSelectionState,
  focusObject,
  replaceSelection,
  selectObject,
  setCompared,
  togglePin,
  unbindSnapshot,
  unselectObject,
  type SelectionScope,
} from './selection-model';
import {
  appendTrail,
  clearHistory,
  createExplorationHistory,
  nextFocus,
  previousFocus,
  type ExplorationHistory,
} from './history';

/** Honest, mutually-exclusive fetch states — never a blank that reads as "no data". */
export type ExplorationStatus = 'idle' | 'loading' | 'ready' | 'error' | 'not_enabled';

export interface ExplorationState {
  context: ExplorationContextV1;
  result: ExplorationResultEnvelope<unknown> | null;
  status: ExplorationStatus;
  error: string | null;
}

/**
 * The graph-first state is an additive extension of ExplorationState. The
 * existing `context` remains available to all ExplorationProvider consumers;
 * graph consumers use `graphContext`, whose scope is supplied by the host.
 * `selection` and `history` are mirrors of the corresponding graph context
 * fields and are updated together by graph actions.
 */
export interface GraphExplorationState extends ExplorationState {
  graphContext: GraphContext;
  history: ExplorationHistory;
}

export function initialExplorationState(context: ExplorationContextV1): ExplorationState {
  return { context, result: null, status: 'idle', error: null };
}

export function createExplorationStore(context: ExplorationContextV1): Store<ExplorationState> {
  return createStore<ExplorationState>(initialExplorationState(context));
}

export function createGraphExplorationStore(context: ExplorationContextV1, scope: GraphScope): Store<GraphExplorationState> {
  const graphContext = explorationContextToGraphContext(context, scope);
  const activeScope = selectionScope(scope);
  const history = createExplorationHistory(activeScope);
  return createStore<GraphExplorationState>({
    ...initialExplorationState(context),
    graphContext,
    history,
  });
}

const EMPTY_AND: FilterGroup = { logic: 'AND', expressions: [] };

/** Append a registry-valid predicate to the top-level AND population group. */
export function withAddedFilter(
  context: ExplorationContextV1,
  expr: FilterExpression,
): ExplorationContextV1 {
  if (!isKnownField(expr.field) || !isOperatorValidForField(expr.field, expr.op)) {
    return context;
  }
  const base = context.population ?? EMPTY_AND;
  const population: FilterGroup = base.logic === 'AND'
    ? { logic: 'AND', expressions: [...base.expressions, expr] }
    : { logic: 'AND', expressions: [base, expr] };
  return { ...context, population };
}

/** Remove the top-level predicate at `index`; empties population to null when last. */
export function withoutFilterAt(context: ExplorationContextV1, index: number): ExplorationContextV1 {
  const base = context.population;
  if (!base) return context;
  const expressions = base.expressions.filter((_, i) => i !== index);
  return { ...context, population: expressions.length ? { ...base, expressions } : null };
}

export interface ExplorationActions {
  setContext: (context: ExplorationContextV1) => void;
  setPopulation: (population: FilterGroup | null) => void;
  addFilter: (expr: FilterExpression) => void;
  removeFilterAt: (index: number) => void;
  setPresentation: (presentation: PresentationSpec) => void;
  setLoading: () => void;
  setResult: (result: ExplorationResultEnvelope<unknown>) => void;
  setError: (error: string) => void;
  setNotEnabled: () => void;
}

export function explorationActions(store: Store<ExplorationState>): ExplorationActions {
  const patch = (next: (c: ExplorationContextV1) => ExplorationContextV1) =>
    store.setState((s) => ({ ...s, context: next(s.context) }));
  return {
    setContext: (context) => store.setState((s) => ({ ...s, context })),
    setPopulation: (population) => patch((c) => ({ ...c, population })),
    addFilter: (expr) => patch((c) => withAddedFilter(c, expr)),
    removeFilterAt: (index) => patch((c) => withoutFilterAt(c, index)),
    setPresentation: (presentation) => patch((c) => ({ ...c, presentation })),
    setLoading: () => store.setState((s) => ({ ...s, status: 'loading', error: null })),
    setResult: (result) =>
      store.setState((s) => ({
        ...s,
        result,
        // Adopt the server's normalised context — the honest interpretation.
        context: result.normalized_context,
        status: 'ready',
        error: null,
      })),
    setError: (error) => store.setState((s) => ({ ...s, status: 'error', error })),
    setNotEnabled: () => store.setState((s) => ({ ...s, status: 'not_enabled', result: null, error: null })),
  };
}

export interface GraphExplorationActions extends ExplorationActions {
  setGraphContext: (context: GraphContext) => void;
  setScopedContext: (context: ExplorationContextV1, scope: GraphScope) => void;
  setSelection: (selection: GraphSelectionState) => void;
  selectObject: (ref: GraphObjectRef) => void;
  unselectObject: (ref: GraphObjectRef) => void;
  replaceSelection: (refs: readonly GraphObjectRef[]) => void;
  focusObject: (ref: GraphObjectRef | null) => void;
  togglePin: (ref: GraphObjectRef) => void;
  setCompared: (refs: readonly GraphObjectRef[] | GraphObjectRef) => void;
  bindSnapshot: (ref: GraphSnapshotRef) => void;
  unbindSnapshot: (ref: GraphSnapshotRef) => void;
  clearSelection: () => void;
  appendHistory: (entry: ExplorationTrailEntry, max?: number) => void;
  clearHistory: () => void;
  previousFocus: (current?: GraphObjectRef | null) => GraphObjectRef | null;
  nextFocus: (current?: GraphObjectRef | null) => GraphObjectRef | null;
}

function selectionScope(scope: GraphScope): SelectionScope {
  return { tenant_id: scope.tenant_id, workspace_id: scope.workspace_id, environment_id: scope.environment_id };
}

function graphContextToExplorationContext(context: GraphContext): ExplorationContextV1 {
  const { scope, selection, anchors, ...rest } = context;
  return {
    ...rest,
    version: '1',
    scope: { tenant_id: scope.tenant_id, surface: scope.surface },
    anchors: anchors.map(({ kind, id }) => ({ kind, id })),
    selection: {
      focused: selection.focused ? { kind: selection.focused.kind, id: selection.focused.id } : null,
      selected: selection.selected.map(({ kind, id }) => ({ kind, id })),
    },
  };
}

function withGraphSelection(state: GraphExplorationState, selection: GraphSelectionState): GraphExplorationState {
  return {
    ...state,
    // The graph context is authoritative. This narrow legacy mirror keeps the
    // existing URL codec (and ExplorationProvider consumers) shareable without
    // allowing a second selection writer.
    context: {
      ...state.context,
      selection: {
        focused: selection.focused ? { kind: selection.focused.kind, id: selection.focused.id } : null,
        selected: selection.selected.map(({ kind, id }) => ({ kind, id })),
      },
    },
    graphContext: { ...state.graphContext, selection },
  };
}

function resetGraphContext(context: GraphContext): GraphContext {
  return {
    ...context,
    anchors: [],
    population: null,
    graph: null,
    query: null,
    selection: createSelectionState(),
    evidence: [],
    rights: null,
    confidence: null,
    saved_context_id: null,
    snapshot_id: null,
    diff_id: null,
    exploration_trail: [],
    projection: null,
  };
}

function graphStateScope(state: GraphExplorationState): GraphScope {
  const { tenant_id, workspace_id, environment_id, account_id, organization_id } = state.graphContext.scope;
  return { tenant_id, workspace_id, environment_id, ...(account_id === undefined ? {} : { account_id }), ...(organization_id === undefined ? {} : { organization_id }) };
}

/** Actions for the graph extension, backed by the same external store. */
export function graphExplorationActions(store: Store<GraphExplorationState>): GraphExplorationActions {
  const update = (mutate: (state: GraphExplorationState, scope: SelectionScope) => GraphExplorationState): void => {
    store.setState((state) => mutate(state, selectionScope(graphStateScope(state))));
  };
  const setSelection = (selection: GraphSelectionState): void => {
    update((state, scope) => {
      // Run the existing selection validator against every collection before
      // accepting an externally supplied selection.
      let checked = createSelectionState();
      checked = replaceSelection(checked, selection.selected, scope);
      checked = focusObject(checked, selection.focused, scope);
      for (const ref of selection.pinned) checked = togglePin(checked, ref, scope);
      checked = setCompared(checked, selection.compared, scope);
      for (const ref of selection.snapshot_bound) checked = bindSnapshot(checked, ref, scope);
      return withGraphSelection(state, checked);
    });
  };
  const applyExplorationContext = (context: ExplorationContextV1, scope: GraphScope, clearScopedState: boolean): void => {
    const state = store.getState();
    const next = explorationContextToGraphContext(context, scope);
    const scopeChanged = graphScopeChangeRequiresReset(graphStateScope(state), scope);
    const reset = scopeChanged || clearScopedState;
    const graphContext = reset
      ? resetGraphContext(next)
      : { ...state.graphContext, ...next, exploration_trail: [...state.history.entries] };
    const history = reset ? clearHistory(selectionScope(scope)) : state.history;
    store.setState((current) => ({
      ...current,
      context: reset ? graphContextToExplorationContext(graphContext) : context,
      graphContext: { ...graphContext, exploration_trail: [...history.entries] },
      history,
      ...(reset ? { result: null, status: 'idle' as const, error: null } : {}),
    }));
  };
  const patchContext = (mutate: (context: ExplorationContextV1) => ExplorationContextV1): void => {
    const state = store.getState();
    const nextContext = mutate(state.context);
    const nextGraph = explorationContextToGraphContext(nextContext, graphStateScope(state));
    store.setState((current) => ({
      ...current,
      context: nextContext,
      graphContext: { ...current.graphContext, ...nextGraph, selection: current.graphContext.selection, exploration_trail: [...current.history.entries] },
    }));
  };
  const setResult = (result: ExplorationResultEnvelope<unknown>): void => {
    const state = store.getState();
    const normalized = explorationContextToGraphContext(result.normalized_context, graphStateScope(state));
    const history = state.history;
    store.setState((current) => ({
      ...current,
      result,
      context: result.normalized_context,
      graphContext: { ...current.graphContext, ...normalized, exploration_trail: [...history.entries] },
      history,
      status: 'ready',
      error: null,
    }));
  };
  const withGraphContext = (context: GraphContext, clearScopedState: boolean): void => {
    const scope = graphStateScope(store.getState());
    const nextScope = context.scope;
    graphScopeAuthorityKey(nextScope);
    const validation = validateGraphContext(context);
    if (!validation.valid) throw new Error(`Invalid GraphContext: ${validation.errors.join('; ')}`);
    const scopeChanged = graphScopeChangeRequiresReset(scope, nextScope);
    const next = scopeChanged || clearScopedState ? resetGraphContext(context) : context;
    const nextHistory = scopeChanged || clearScopedState
      ? clearHistory(selectionScope(nextScope))
      : store.getState().history;
    store.setState((state) => ({
      ...state,
      context: graphContextToExplorationContext(next),
      graphContext: { ...next, exploration_trail: [...nextHistory.entries] },
      history: nextHistory,
      ...(scopeChanged || clearScopedState ? { result: null, status: 'idle' as const, error: null } : {}),
    }));
  };
  return {
    setContext: (context) => applyExplorationContext(context, graphStateScope(store.getState()), true),
    setGraphContext: (context) => withGraphContext(context, false),
    setScopedContext: (context, scope) => {
      applyExplorationContext(context, scope, false);
    },
    setSelection,
    selectObject: (ref) => update((state, scope) => { const selection = selectObject(state.graphContext.selection, ref, scope); return withGraphSelection(state, selection); }),
    unselectObject: (ref) => update((state, scope) => { const selection = unselectObject(state.graphContext.selection, ref, scope); return withGraphSelection(state, selection); }),
    replaceSelection: (refs) => update((state, scope) => { const selection = replaceSelection(state.graphContext.selection, refs, scope); return withGraphSelection(state, selection); }),
    focusObject: (ref) => update((state, scope) => { const selection = focusObject(state.graphContext.selection, ref, scope); return withGraphSelection(state, selection); }),
    togglePin: (ref) => update((state, scope) => { const selection = togglePin(state.graphContext.selection, ref, scope); return withGraphSelection(state, selection); }),
    setCompared: (refs) => update((state, scope) => { const selection = setCompared(state.graphContext.selection, refs, scope); return withGraphSelection(state, selection); }),
    bindSnapshot: (ref) => update((state, scope) => { const selection = bindSnapshot(state.graphContext.selection, ref, scope); return withGraphSelection(state, selection); }),
    unbindSnapshot: (ref) => update((state, scope) => { const selection = unbindSnapshot(state.graphContext.selection, ref, scope); return withGraphSelection(state, selection); }),
    clearSelection: () => update((state, scope) => { const selection = clearSelection(state.graphContext.selection, scope); return withGraphSelection(state, selection); }),
    appendHistory: (entry, max) => update((state, scope) => { const history = appendTrail(state.history, entry, scope, max); return { ...state, history, graphContext: { ...state.graphContext, exploration_trail: [...history.entries] } }; }),
    clearHistory: () => update((state, scope) => { const history = clearHistory(scope); return { ...state, history, graphContext: { ...state.graphContext, exploration_trail: [] } }; }),
    previousFocus: (current = null) => previousFocus(store.getState().history.entries, current),
    nextFocus: (current = null) => nextFocus(store.getState().history.entries, current),
    setPopulation: (population) => patchContext((context) => ({ ...context, population })),
    addFilter: (expr) => patchContext((context) => withAddedFilter(context, expr)),
    removeFilterAt: (index) => patchContext((context) => withoutFilterAt(context, index)),
    setPresentation: (presentation) => patchContext((context) => ({ ...context, presentation })),
    setLoading: () => store.setState((state) => ({ ...state, status: 'loading', error: null })),
    setResult,
    setError: (error) => store.setState((state) => ({ ...state, status: 'error', error })),
    setNotEnabled: () => store.setState((state) => ({ ...state, status: 'not_enabled', result: null, error: null })),
  };
}

export function useExplorationStore<S>(
  store: Store<ExplorationState>,
  selector: (state: ExplorationState) => S,
): S {
  return useStore(store, selector);
}

export function useGraphExplorationStore<S>(store: Store<GraphExplorationState>, selector: (state: GraphExplorationState) => S): S {
  return useStore(store, selector);
}
