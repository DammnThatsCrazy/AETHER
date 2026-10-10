/**
 * Tiny fetch-state hook for the security console.
 *
 * Distinguishes 403 (forbidden — an authoritative backend answer) from other
 * failures so `AsyncSection` can render the right state instead of a generic
 * error blob. 401 is not handled here: the transport broadcasts it and the
 * auth provider flips the whole app to logged-out.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { KyberAuthError, describeAuthError } from '@kyber/lib/auth';

export interface SecurityResource<T> {
  readonly data: T | null;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly isForbidden: boolean;
  readonly refresh: () => Promise<void>;
}

export function useSecurityResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[] = [],
): SecurityResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isForbidden, setIsForbidden] = useState(false);
  const mountedRef = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(async () => {
    const controller = new AbortController();
    setIsLoading(true);
    try {
      const next = await loaderRef.current(controller.signal);
      if (!mountedRef.current) return;
      setData(next);
      setError(null);
      setIsForbidden(false);
    } catch (err) {
      if (!mountedRef.current) return;
      setIsForbidden(err instanceof KyberAuthError && err.isForbidden);
      setError(describeAuthError(err));
    } finally {
      if (mountedRef.current) setIsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();
    return () => {
      mountedRef.current = false;
    };
  }, [refresh]);

  return { data, isLoading, error, isForbidden, refresh };
}
