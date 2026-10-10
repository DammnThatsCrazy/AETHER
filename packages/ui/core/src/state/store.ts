/**
 * Minimal external store primitive (framework-agnostic core + React binding).
 *
 * Lifted from the Kyber app so every surface — and the shared exploration
 * fabric — builds on ONE store implementation. `useStore` subscribes through
 * `useSyncExternalStore`, so selectors stay tearing-free under concurrent
 * React. The old `@kyber/state` path re-exports these for zero breakage.
 */

import { useSyncExternalStore, useCallback } from 'react';

type Listener = () => void;

export interface Store<T> {
  getState: () => T;
  setState: (updater: (prev: T) => T) => void;
  subscribe: (listener: Listener) => () => void;
}

export function createStore<T>(initialState: T): Store<T> {
  let state = initialState;
  const listeners = new Set<Listener>();

  return {
    getState: () => state,
    setState: (updater) => {
      state = updater(state);
      listeners.forEach((l) => l());
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useStore<T, S>(store: Store<T>, selector: (state: T) => S): S {
  return useSyncExternalStore(
    store.subscribe,
    useCallback(() => selector(store.getState()), [store, selector]),
  );
}
