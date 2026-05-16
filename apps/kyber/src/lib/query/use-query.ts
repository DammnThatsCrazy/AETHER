import { useState, useEffect, useCallback, useRef } from 'react';
import { queryCache } from './cache';
import { log } from '@kyber/lib/logging';

const DEFAULT_STALE_TIME_MS = 30_000;

export interface UseQueryOptions<T> {
  readonly key: string;
  readonly fetcher: () => Promise<T>;
  readonly staleTime?: number | undefined;
  readonly pollInterval?: number | undefined;
  readonly enabled?: boolean | undefined;
}

export interface UseQueryResult<T> {
  readonly data: T | null;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly refetch: () => void;
}

/**
 * Fetches data with automatic caching, deduplication, and optional polling.
 *
 * Multiple components using the same `key` share one in-flight request and the
 * cached result. `staleTime` controls how long a cached value is considered
 * fresh (default 30s). `pollInterval` triggers a background refresh on the
 * given cadence (0 = disabled).
 *
 * Usage:
 *   const { data, isLoading, error } = useQuery({
 *     key: 'diagnostics/health',
 *     fetcher: api.diagnostics.health,
 *     pollInterval: 15_000,
 *   });
 */
export function useQuery<T>({
  key,
  fetcher,
  staleTime = DEFAULT_STALE_TIME_MS,
  pollInterval,
  enabled = true,
}: UseQueryOptions<T>): UseQueryResult<T> {
  const [, forceUpdate] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Re-render when the cache entry for this key changes.
  useEffect(() => {
    return queryCache.subscribe(key, () => {
      if (mountedRef.current) forceUpdate(n => n + 1);
    });
  }, [key]);

  const execute = useCallback(
    async (force = false): Promise<void> => {
      if (!enabled) return;
      if (!force && !queryCache.isStale(key, staleTime)) return;

      // Join an in-flight request for the same key rather than firing a second one.
      const inFlight = queryCache.getInFlight<T>(key);
      if (inFlight !== null) {
        if (mountedRef.current) setIsLoading(true);
        try {
          await inFlight;
          if (mountedRef.current) {
            setIsLoading(false);
            setError(null);
          }
        } catch (err) {
          if (mountedRef.current) {
            setError(err instanceof Error ? err.message : 'Request failed');
            setIsLoading(false);
          }
        }
        return;
      }

      if (mountedRef.current) {
        setIsLoading(true);
        setError(null);
      }

      const promise = fetcherRef
        .current()
        .then((data) => {
          queryCache.set(key, data);
          if (mountedRef.current) {
            setIsLoading(false);
            setError(null);
          }
          return data;
        })
        .catch((err) => {
          log.error(`[useQuery] ${key} failed`, { error: err });
          if (mountedRef.current) {
            setError(err instanceof Error ? err.message : 'Request failed');
            setIsLoading(false);
          }
          throw err;
        });

      queryCache.setInFlight<T>(key, promise);
    },
    [key, staleTime, enabled],
  );

  // Initial fetch on mount / when dependencies change.
  useEffect(() => {
    void execute();
  }, [execute]);

  // Background polling.
  useEffect(() => {
    if (!pollInterval || pollInterval <= 0 || !enabled) return;
    const id = setInterval(() => {
      queryCache.invalidate(key);
      void execute(true);
    }, pollInterval);
    return () => clearInterval(id);
  }, [key, pollInterval, enabled, execute]);

  const cached = queryCache.get<T>(key);

  return {
    data: cached?.data ?? null,
    isLoading,
    error,
    refetch: useCallback(() => {
      queryCache.invalidate(key);
      void execute(true);
    }, [key, execute]),
  };
}
