/**
 * Exploration provider + hooks.
 *
 * Router-agnostic: the URL is authoritative, but this package must not depend
 * on any router. The host passes the authoritative `query` string in and reads
 * `toQuery()` back out to push into its own router — so the URL stays the source
 * of truth without @aether/ui importing react-router.
 */

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react';
import type { Store } from '../state/index';
import type { ExplorationContextV1, TemporalSelection } from '@aether/shared/exploration-contract';
import type { GraphContext, GraphScope } from '@aether/shared/graph-context-contract';
import {
  createGraphExplorationStore,
  createExplorationStore,
  graphExplorationActions,
  explorationActions,
  useGraphExplorationStore,
  useExplorationStore,
  type GraphExplorationActions,
  type GraphExplorationState,
  type ExplorationActions,
  type ExplorationState,
} from './store';
import { encodeExplorationContext, decodeExplorationContext } from './url-codec';
import type { ExplorationClient } from './client';
import { graphScopeChangeRequiresReset } from './graph-context-adapter';

function defaultContext(tenantId: string, surface: string): ExplorationContextV1 {
  const temporal: TemporalSelection = { mode: 'window', field: 'occurred_at', timezone: 'UTC' };
  return { version: '1', scope: { tenant_id: tenantId, surface }, temporal };
}

/** The authoritative context implied by the current URL/props (URL wins). */
function contextForProps(tenantId: string, surface: string, query?: string): ExplorationContextV1 {
  return query != null && query.length > 0
    ? decodeExplorationContext(query, { tenantId, surface })
    : defaultContext(tenantId, surface);
}

/**
 * Structural equality over the shareable state: the encoder is canonical (fixed
 * param order), so equal encodings + equal tenant mean equal context. Used to
 * skip redundant resets (and any resulting render churn) when a URL push simply
 * round-trips the state the store already holds.
 */
function sameContext(a: ExplorationContextV1, b: ExplorationContextV1): boolean {
  return (
    a.scope.tenant_id === b.scope.tenant_id &&
    a.scope.surface === b.scope.surface &&
    encodeExplorationContext(a) === encodeExplorationContext(b)
  );
}

interface ExplorationContextValue {
  store: Store<ExplorationState>;
  actions: ExplorationActions;
  /** Mounted app transport for the canonical `/v1/explore` routes. */
  client?: ExplorationClient | undefined;
  /** Encode the current context to a query string; the host syncs it to the URL. */
  toQuery: () => string;
}

export interface GraphContextValue {
  store: Store<GraphExplorationState>;
  actions: GraphExplorationActions;
  client?: ExplorationClient | undefined;
  toQuery: () => string;
  toGraphQueryContext: () => GraphContext;
  exploration: ExplorationContextValue;
}

const ExplorationReactContext = createContext<ExplorationContextValue | null>(null);
const GraphReactContext = createContext<GraphContextValue | null>(null);

export interface ExplorationProviderProps {
  tenantId: string;
  surface: string;
  /** Authoritative URL query string (no leading '?'); decoded into initial state. */
  query?: string;
  /** App-owned authenticated transport; required by mounted production hosts. */
  client?: ExplorationClient;
  children: ReactNode;
}

export function ExplorationProvider({ tenantId, surface, query, client, children }: ExplorationProviderProps) {
  const storeRef = useRef<Store<ExplorationState> | null>(null);
  if (storeRef.current === null) {
    storeRef.current = createExplorationStore(contextForProps(tenantId, surface, query));
  }
  const store = storeRef.current;
  const actions = useMemo(() => explorationActions(store), [store]);

  // The URL is authoritative: when the host router changes query/tenant/surface
  // WITHOUT remounting us (back/forward, cross-surface nav under one layout),
  // re-decode and reset the store so the UI and toQuery() never keep stale
  // context. Guarded so a self-initiated round-trip doesn't loop or churn.
  useEffect(() => {
    const next = contextForProps(tenantId, surface, query);
    if (!sameContext(next, store.getState().context)) {
      actions.setContext(next);
    }
  }, [query, tenantId, surface, store, actions]);
  const value = useMemo<ExplorationContextValue>(
    () => ({ store, actions, client, toQuery: () => encodeExplorationContext(store.getState().context) }),
    [store, actions, client],
  );
  return <ExplorationReactContext.Provider value={value}>{children}</ExplorationReactContext.Provider>;
}

export interface GraphContextProviderProps {
  /** Host-authoritative identity; never derive these values from URL/deployment labels. */
  scope: GraphScope;
  /** Optional view surface. The URL may carry a shareable surface, but scope remains host authority. */
  surface?: string;
  /** Authoritative URL query string (no leading '?'); graph scope is never encoded here. */
  query?: string;
  client?: ExplorationClient;
  children: ReactNode;
}

/**
 * Graph-first extension of ExplorationProvider. It deliberately shares the
 * exploration URL codec and external store, while requiring the host to pass
 * a complete GraphScope. Workspace and environment are never inferred from a
 * route, URL parameter, or deployment profile.
 */
export function GraphContextProvider({ scope, surface = 'graph', query, client, children }: GraphContextProviderProps) {
  const storeRef = useRef<Store<GraphExplorationState> | null>(null);
  if (storeRef.current === null) {
    const context = contextForProps(scope.tenant_id, surface, query);
    storeRef.current = createGraphExplorationStore(context, scope);
  }
  const store = storeRef.current;
  const actions = useMemo(() => graphExplorationActions(store), [store]);
  const explorationStore = useMemo<Store<ExplorationState>>(() => ({
    getState: () => store.getState(),
    setState: (updater: (state: ExplorationState) => ExplorationState) => store.setState((state: GraphExplorationState) => ({ ...state, ...updater(state) })),
    subscribe: store.subscribe,
  }), [store]);
  const exploration = useMemo<ExplorationContextValue>(() => ({
    store: explorationStore,
    actions,
    client,
    toQuery: () => encodeExplorationContext(store.getState().context),
  }), [explorationStore, actions, client, store]);

  useEffect(() => {
    const nextContext = contextForProps(scope.tenant_id, surface, query);
    const currentScope = store.getState().graphContext.scope;
    const scopeChanged = graphScopeChangeRequiresReset(currentScope, scope);
    if (scopeChanged) {
      // Re-adapt under the new host scope. setContext clears graph artifacts,
      // selection, trail, result, and status before exposing the new context.
      actions.setScopedContext(nextContext, scope);
    } else if (!sameContext(nextContext, store.getState().context)) {
      actions.setScopedContext(nextContext, scope);
    }
  }, [query, scope, surface, store, actions]);

  const value = useMemo<GraphContextValue>(() => ({
    store,
    actions,
    client,
    toQuery: () => encodeExplorationContext(store.getState().context),
    toGraphQueryContext: () => store.getState().graphContext,
    exploration,
  }), [store, actions, client, exploration]);

  return (
    <ExplorationReactContext.Provider value={exploration}>
      <GraphReactContext.Provider value={value}>{children}</GraphReactContext.Provider>
    </ExplorationReactContext.Provider>
  );
}

export function useExploration(): ExplorationContextValue {
  const value = useContext(ExplorationReactContext);
  if (!value) throw new Error('useExploration must be used inside <ExplorationProvider>');
  return value;
}

export function useExplorationSelector<S>(selector: (state: ExplorationState) => S): S {
  const { store } = useExploration();
  return useExplorationStore(store, selector);
}

export function useExplorationContext(): ExplorationContextV1 {
  return useExplorationSelector((s) => s.context);
}

export function useExplorationClient(): ExplorationClient {
  const { client } = useExploration();
  if (!client) {
    throw new Error('The mounted ExplorationProvider has no authenticated exploration client');
  }
  return client;
}

export function useExplorationStatus(): ExplorationState['status'] {
  return useExplorationSelector((s) => s.status);
}

export function useExplorationFilters() {
  const { actions } = useExploration();
  const population = useExplorationSelector((s) => s.context.population ?? null);
  return {
    population,
    addFilter: actions.addFilter,
    removeFilterAt: actions.removeFilterAt,
    setPopulation: actions.setPopulation,
  };
}

export function useGraph(): GraphContextValue {
  const value = useContext(GraphReactContext);
  if (!value) throw new Error('useGraph must be used inside <GraphContextProvider>');
  return value;
}

export function useGraphContextSelector<S>(selector: (state: GraphExplorationState) => S): S {
  const { store } = useGraph();
  return useGraphExplorationStore(store, selector);
}

export function useGraphContext(): GraphContext {
  return useGraphContextSelector((state) => state.graphContext);
}

export function useGraphSelection(): GraphContext['selection'] {
  return useGraphContextSelector((state) => state.graphContext.selection);
}

export function useGraphHistory(): GraphExplorationState['history'] {
  return useGraphContextSelector((state) => state.history);
}

export function useGraphActions(): GraphExplorationActions {
  return useGraph().actions;
}
