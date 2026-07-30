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
import {
  createExplorationStore,
  explorationActions,
  useExplorationStore,
  type ExplorationActions,
  type ExplorationState,
} from './store';
import { encodeExplorationContext, decodeExplorationContext } from './url-codec';
import type { ExplorationClient } from './client';

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

const ExplorationReactContext = createContext<ExplorationContextValue | null>(null);

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
