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
import type { FilterExpression, FilterGroup } from '@aether/shared/graph-contract';
import { isKnownField, isOperatorValidForField } from './registry';

/** Honest, mutually-exclusive fetch states — never a blank that reads as "no data". */
export type ExplorationStatus = 'idle' | 'loading' | 'ready' | 'error' | 'not_enabled';

export interface ExplorationState {
  context: ExplorationContextV1;
  result: ExplorationResultEnvelope<unknown> | null;
  status: ExplorationStatus;
  error: string | null;
}

export function initialExplorationState(context: ExplorationContextV1): ExplorationState {
  return { context, result: null, status: 'idle', error: null };
}

export function createExplorationStore(context: ExplorationContextV1): Store<ExplorationState> {
  return createStore<ExplorationState>(initialExplorationState(context));
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

export function useExplorationStore<S>(
  store: Store<ExplorationState>,
  selector: (state: ExplorationState) => S,
): S {
  return useStore(store, selector);
}
