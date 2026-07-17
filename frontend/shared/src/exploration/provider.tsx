/**
 * Exploration provider + hooks.
 *
 * Router-agnostic: the URL is authoritative, but this package must not depend
 * on any router. The host passes the authoritative `query` string in and reads
 * `toQuery()` back out to push into its own router — so the URL stays the source
 * of truth without @aether/ui importing react-router.
 */

import { createContext, useContext, useMemo, useRef, type ReactNode } from 'react';
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

function defaultContext(tenantId: string, surface: string): ExplorationContextV1 {
  const temporal: TemporalSelection = { mode: 'window', field: 'occurred_at', timezone: 'UTC' };
  return { version: '1', scope: { tenant_id: tenantId, surface }, temporal };
}

interface ExplorationContextValue {
  store: Store<ExplorationState>;
  actions: ExplorationActions;
  /** Encode the current context to a query string; the host syncs it to the URL. */
  toQuery: () => string;
}

const ExplorationReactContext = createContext<ExplorationContextValue | null>(null);

export interface ExplorationProviderProps {
  tenantId: string;
  surface: string;
  /** Authoritative URL query string (no leading '?'); decoded into initial state. */
  query?: string;
  children: ReactNode;
}

export function ExplorationProvider({ tenantId, surface, query, children }: ExplorationProviderProps) {
  const storeRef = useRef<Store<ExplorationState> | null>(null);
  if (storeRef.current === null) {
    const context = query != null && query.length > 0
      ? decodeExplorationContext(query, { tenantId, surface })
      : defaultContext(tenantId, surface);
    storeRef.current = createExplorationStore(context);
  }
  const store = storeRef.current;
  const actions = useMemo(() => explorationActions(store), [store]);
  const value = useMemo<ExplorationContextValue>(
    () => ({ store, actions, toQuery: () => encodeExplorationContext(store.getState().context) }),
    [store, actions],
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
