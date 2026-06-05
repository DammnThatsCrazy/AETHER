import { useState, useEffect, useCallback, useRef } from 'react';
import { queryCache } from './cache';

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

  const execute = useCallback(
    async (force = false): Promise<void> => {
      if (!enabled) return;
      if (!force && !queryCache.isStale(key, staleTime)) return;

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
          console.error(`[useQuery] ${key} failed`, err);
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

  useEffect(() => {
    return queryCache.subscribe(key, () => {
      if (!mountedRef.current) return;
      forceUpdate(n => n + 1);
      // Refetch on cache notifications: after invalidate() the entry is gone
      // (isStale → fetch), so an invalidateKeys mutation actually refreshes the
      // view; after our own set() the entry is fresh, so execute() early-returns
      // and we don't loop on our own writes.
      void execute();
    });
  }, [key, execute]);

  useEffect(() => {
    void execute();
  }, [execute]);

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
