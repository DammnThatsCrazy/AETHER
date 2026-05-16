import { useState, useCallback } from 'react';
import { queryCache } from './cache';
import { log } from '@kyber/lib/logging';

export interface UseMutationOptions<TInput, TOutput> {
  readonly mutationFn: (input: TInput) => Promise<TOutput>;
  readonly onSuccess?: ((data: TOutput, input: TInput) => void) | undefined;
  readonly onError?: ((error: string, input: TInput) => void) | undefined;
  /**
   * Cache keys to invalidate after a successful mutation. Components subscribed
   * to these keys via useQuery will automatically re-fetch.
   */
  readonly invalidateKeys?: readonly string[] | undefined;
}

export interface UseMutationResult<TInput, TOutput> {
  readonly mutate: (input: TInput) => Promise<TOutput | null>;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly data: TOutput | null;
  readonly reset: () => void;
}

/**
 * Wraps an async operation (POST/PUT/PATCH/DELETE) with loading and error state.
 * Optionally invalidates query cache keys on success so related useQuery hooks
 * re-fetch automatically.
 *
 * Usage:
 *   const { mutate, isLoading } = useMutation({
 *     mutationFn: (id: string) => api.diagnostics.resolveError(id),
 *     invalidateKeys: ['diagnostics/errors'],
 *   });
 */
export function useMutation<TInput, TOutput>({
  mutationFn,
  onSuccess,
  onError,
  invalidateKeys,
}: UseMutationOptions<TInput, TOutput>): UseMutationResult<TInput, TOutput> {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TOutput | null>(null);

  const mutate = useCallback(
    async (input: TInput): Promise<TOutput | null> => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await mutationFn(input);
        setData(result);
        if (invalidateKeys) {
          for (const k of invalidateKeys) queryCache.invalidate(k);
        }
        onSuccess?.(result, input);
        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Mutation failed';
        log.error('[useMutation] failed', { error: err });
        setError(message);
        onError?.(message, input);
        return null;
      } finally {
        setIsLoading(false);
      }
    },
    [mutationFn, onSuccess, onError, invalidateKeys],
  );

  const reset = useCallback(() => {
    setIsLoading(false);
    setError(null);
    setData(null);
  }, []);

  return { mutate, isLoading, error, data, reset };
}
