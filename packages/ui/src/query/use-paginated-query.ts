import { useState, useCallback } from 'react';

const DEFAULT_LIMIT = 50;

export interface PageFetcherParams {
  readonly offset: number;
  readonly limit: number;
}

export interface PageFetcherResult<T> {
  readonly data: readonly T[];
  readonly total: number;
  readonly has_more?: boolean | undefined;
}

export type PageFetcher<T> = (params: PageFetcherParams) => Promise<PageFetcherResult<T>>;

export interface UsePaginatedQueryResult<T> {
  readonly data: readonly T[];
  readonly total: number;
  readonly hasMore: boolean;
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly offset: number;
  readonly limit: number;
  readonly fetchPage: (offset: number) => void;
  readonly fetchNext: () => void;
  readonly fetchPrev: () => void;
  readonly refetch: () => void;
}

export function usePaginatedQuery<T>(
  fetcher: PageFetcher<T>,
  limit = DEFAULT_LIMIT,
): UsePaginatedQueryResult<T> {
  const [data, setData] = useState<readonly T[]>([]);
  const [total, setTotal] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const fetchPage = useCallback(
    async (pageOffset: number): Promise<void> => {
      setIsLoading(true);
      setError(null);
      try {
        const result = await fetcher({ offset: pageOffset, limit });
        setData(result.data);
        setTotal(result.total);
        setHasMore(result.has_more ?? result.data.length === limit);
        setOffset(pageOffset);
      } catch (err) {
        console.error('[usePaginatedQuery] fetch failed', err);
        setError(err instanceof Error ? err.message : 'Failed to fetch');
      } finally {
        setIsLoading(false);
      }
    },
    [fetcher, limit],
  );

  const fetchNext = useCallback(
    () => void fetchPage(offset + limit),
    [fetchPage, offset, limit],
  );

  const fetchPrev = useCallback(
    () => void fetchPage(Math.max(0, offset - limit)),
    [fetchPage, offset, limit],
  );

  const refetch = useCallback(
    () => void fetchPage(offset),
    [fetchPage, offset],
  );

  return {
    data,
    total,
    hasMore,
    isLoading,
    error,
    offset,
    limit,
    fetchPage: useCallback((o: number) => void fetchPage(o), [fetchPage]),
    fetchNext,
    fetchPrev,
    refetch,
  };
}
