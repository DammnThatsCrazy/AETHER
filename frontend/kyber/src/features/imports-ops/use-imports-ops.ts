import { useQuery, useMutation, queryCache } from '@aether/ui';
import {
  fetchImportsTimeline,
  fetchImportOpsDetail,
  requeueImport,
} from './api';
import type {
  ImportsTimelineParams,
  ImportsTimelineResult,
  ImportSessionRecord,
  ImportOpsDetail,
  RequeueResponse,
} from './api';

const KEY_PREFIX = 'imports-ops';
const STALE = 15_000;

// ── Queries ───────────────────────────────────────────────────────────────────

export function useImportsTimeline(params?: ImportsTimelineParams): {
  readonly sessions: ImportSessionRecord[];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<ImportsTimelineResult>({
    key: `${KEY_PREFIX}:timeline:${params?.limit ?? 'all'}`,
    fetcher: () => fetchImportsTimeline(params),
    staleTime: STALE,
  });

  return {
    sessions: data?.sessions ?? [],
    count: data?.count ?? 0,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useImportOpsDetail(id: string | null): {
  readonly detail: ImportOpsDetail | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<ImportOpsDetail>({
    key: `${KEY_PREFIX}:detail:${id ?? 'none'}`,
    fetcher: () => fetchImportOpsDetail(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { detail: data, loading: isLoading, error, refresh: refetch };
}

// ── Mutations ─────────────────────────────────────────────────────────────────

// Invalidating the whole feature prefix refreshes both the cross-tenant timeline
// and the open detail view once a requeue succeeds.
const invalidate = () => queryCache.invalidatePrefix(KEY_PREFIX);

export function useRequeueImport(): {
  readonly requeue: (id: string) => Promise<RequeueResponse | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, RequeueResponse>({
    mutationFn: id => requeueImport(id),
    onSuccess: invalidate,
  });
  return { requeue: mutate, loading: isLoading, error };
}
