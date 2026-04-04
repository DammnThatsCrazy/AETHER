import { getRuntimeMode } from '@shiki/lib/env';

export type AdapterMode = 'mocked' | 'live';

export function getAdapterMode(): AdapterMode {
  return getRuntimeMode();
}

/**
 * Creates an adapter that switches between mock and live implementations
 * based on the current runtime mode.
 */
export function createAdapter<T>(mock: T, live: T): T {
  const mode = getAdapterMode();
  return mode === 'mocked' ? mock : live;
}

/**
 * Creates a lazy adapter that defers implementation selection to call time.
 * Useful when adapter mode may change during runtime.
 */
export function createLazyAdapter<T extends Record<string, (...args: never[]) => unknown>>(
  mock: T,
  live: T,
): T {
  return new Proxy(mock, {
    get(_target, prop) {
      const mode = getAdapterMode();
      const impl = mode === 'mocked' ? mock : live;
      return impl[prop as keyof T];
    },
  }) as T;
}
