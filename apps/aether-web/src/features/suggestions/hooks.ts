import { useCallback, useState } from 'react';
import { useQuery, useMutation } from '@aether/ui';
import { fetchTenantSuggestions, submitFeedback } from './api';

type AnyRecord = Record<string, any>;

const STALE = 60_000;

export function useTenantSuggestions(params?: {
  readonly status?: string;
  readonly priority?: string;
  readonly limit?: number;
  readonly offset?: number;
}): {
  readonly data: AnyRecord[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const key = `suggestions:list:${params?.status ?? 'all'}:${params?.priority ?? 'all'}:${params?.limit ?? 50}:${params?.offset ?? 0}`;
  const { data, isLoading, error, refetch } = useQuery<AnyRecord[]>({
    key,
    fetcher: () => fetchTenantSuggestions(params),
    staleTime: STALE,
  });

  return {
    data: data ?? [],
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useSuggestionFeedback(): {
  readonly submit: (id: string, feedback: 'helpful' | 'not_helpful' | 'dismissed') => Promise<void>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<
    { id: string; feedback: 'helpful' | 'not_helpful' | 'dismissed' },
    void
  >({
    mutationFn: ({ id, feedback }) => submitFeedback(id, feedback),
  });

  const submit = useCallback(
    (id: string, feedback: 'helpful' | 'not_helpful' | 'dismissed') =>
      mutate({ id, feedback }).then(() => undefined),
    [mutate],
  );

  return { submit, loading: isLoading, error };
}
