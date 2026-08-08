/**
 * Offline-first projection hook (M3b).
 *
 * Each screen fetches a projection via a typed fetcher, caches successful reads in
 * the read-only projection cache, and re-serves the last cached entry when the
 * network read fails. The `status` faithfully reports how the shown data was
 * obtained:
 *
 * - `fresh`   — read from the network this mount (and cached).
 * - `offline` — network read failed; showing the cached entry within its TTL.
 * - `stale`   — network read failed; showing the cached entry past its TTL.
 * - `loading` — nothing to show yet; first fetch in flight.
 * - `error`   — network read failed and no cached entry exists.
 *
 * Hermes-safe: no WebCrypto / TextEncoder / btoa anywhere on this path.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import type { CacheState } from '@aether/mobile-core';

import { projectionCache } from './cache';

export type ProjectionStatus = 'loading' | CacheState | 'error';

export interface ProjectionResult<T> {
  data: T | null;
  status: ProjectionStatus;
  error: Error | null;
  /** Re-run the network fetch (keeps cached data visible while it runs). */
  refresh: () => void;
}

export function useProjection<T>(key: string, fetcher: () => Promise<T>): ProjectionResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<ProjectionStatus>('loading');
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

  const load = useCallback(
    async (serveCache: boolean): Promise<void> => {
      if (dataRef.current === null) {
        setStatus('loading');
      }

      // 1) Serve the last cached projection immediately when present — an
      //    offline-first read; the network fetch below replaces it with fresh data.
      if (serveCache) {
        try {
          const cached = await projectionCache.get(key);
          if (cached && mountedRef.current) {
            dataRef.current = cached.data as T;
            setData(dataRef.current);
            setStatus(cached.state);
            setError(null);
          }
        } catch {
          // Absent / corrupt entry — fall through to the network fetch.
        }
      }

      // 2) Network read (GET-only — read-only screens).
      try {
        const fresh = await fetcherRef.current();
        await projectionCache.put(key, fresh);
        if (!mountedRef.current) return;
        dataRef.current = fresh;
        setData(fresh);
        setStatus('fresh');
        setError(null);
      } catch (err) {
        const e = err instanceof Error ? err : new Error(String(err));
        let cached = null;
        try {
          // Re-read with `online: false` so an in-TTL entry reads `offline` and an
          // expired entry reads `stale` — an honest label for what is on screen.
          cached = await projectionCache.get(key, { online: false });
        } catch {
          cached = null;
        }
        if (!mountedRef.current) return;
        if (cached) {
          dataRef.current = cached.data as T;
          setData(dataRef.current);
          setStatus(cached.state);
        } else {
          dataRef.current = null;
          setData(null);
          setStatus('error');
        }
        setError(e);
      }
    },
    [key],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  const refresh = useCallback(() => {
    void load(false);
  }, [load]);

  return { data, status, error, refresh };
}
