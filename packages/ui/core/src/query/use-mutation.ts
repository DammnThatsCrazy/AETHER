import { useState, useCallback } from 'react';
import { queryCache } from './cache';

export interface UseMutationOptions<TInput, TOutput> {
  readonly mutationFn: (input: TInput) => Promise<TOutput>;
  readonly onSuccess?: ((data: TOutput, input: TInput) => void) | undefined;
  readonly onError?: ((error: string, input: TInput) => void) | undefined;
  readonly invalidateKeys?: readonly string[] | undefined;
}

export interface UseMutationResult<TInput, TOutput> {
  readonly mutate: (input: TInput) => Promise<TOutput | null>;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly data: TOutput | null;
  readonly reset: () => void;
}

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
        console.error('[useMutation] failed', err);
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
