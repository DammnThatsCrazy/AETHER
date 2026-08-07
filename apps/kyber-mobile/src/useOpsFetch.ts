/**
 * Simple read-only fetch hook for the Kyber operator screens (M4a).
 *
 * A reduced version of the Aether Mobile projection hook
 * (`apps/aether-mobile/src/useProjection.ts`) WITHOUT the offline-cache portion —
 * M4 screens are read-only network reads with a plain loading / fresh / error
 * state machine and an explicit retry. Hermes-safe: no WebCrypto / TextEncoder /
 * btoa anywhere on this path.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type OpsFetchStatus = 'loading' | 'fresh' | 'error';

export interface OpsFetchResult<T> {
  data: T | null;
  status: OpsFetchStatus;
  error: Error | null;
  /** Re-run the network fetch (keeps any visible data on screen while it runs). */
  refresh: () => void;
}

export function useOpsFetch<T>(fetcher: () => Promise<T>): OpsFetchResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<OpsFetchStatus>('loading');
  const [error, setError] = useState<Error | null>(null);

  // Refs keep the effect dependency list stable and guard post-unmount setState.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const dataRef = useRef<T | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async (): Promise<void> => {
    // First load (nothing on screen yet) reports `loading`; refreshes keep the
    // last data visible while the network read runs.
    if (dataRef.current === null) {
      setStatus('loading');
    }
    try {
      const fresh = await fetcherRef.current();
      if (!mountedRef.current) return;
      dataRef.current = fresh;
      setData(fresh);
      setStatus('fresh');
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      dataRef.current = null;
      setData(null);
      setStatus('error');
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = useCallback(() => {
    void load();
  }, [load]);

  return { data, status, error, refresh };
}
