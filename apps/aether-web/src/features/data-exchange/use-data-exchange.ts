import { useCallback } from 'react';
import { useQuery, useMutation, queryCache } from '@aether/ui';
import {
  fetchDataExchangeSettings,
  fetchDataExchangeCapabilities,
  fetchDataExchangeUsage,
  fetchDataExchangeArtifacts,
  fetchDataExchangeExports,
  fetchDataExchangeImports,
  fetchDataExchangeReports,
  createDataExchangeExport,
  createDataExchangeReport,
  fetchDataExchangeDownloadUrl,
  type DataExchangeSettings,
  type DataExchangeCapabilities,
  type DataExchangeUsage,
  type DataExchangeArtifactsParams,
  type DataExchangeArtifactsResult,
  type DataExchangeExportsResult,
  type DataExchangeImportsResult,
  type DataExchangeReportsResult,
  type DataExchangeArtifact,
  type CreateDataExchangeExportInput,
  type DataExchangeExportResult,
  type CreateDataExchangeReportInput,
  type DataExchangeReportResult,
  type DataExchangeDownloadUrl,
} from './api';

const KEY_PREFIX = 'data-exchange';
const STALE = 15_000;

// ── Queries ───────────────────────────────────────────────────────────────────

export function useDataExchangeSettings(): {
  readonly settings: DataExchangeSettings | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<DataExchangeSettings>({
    key: `${KEY_PREFIX}:settings`,
    fetcher: fetchDataExchangeSettings,
    staleTime: STALE,
  });
  return { settings: data, loading: isLoading, error, refresh: refetch };
}

export function useDataExchangeCapabilities(): {
  readonly capabilities: DataExchangeCapabilities | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<DataExchangeCapabilities>({
    key: `${KEY_PREFIX}:capabilities`,
    fetcher: fetchDataExchangeCapabilities,
    staleTime: STALE,
  });
  return { capabilities: data, loading: isLoading, error, refresh: refetch };
}

export function useDataExchangeUsage(): {
  readonly usage: DataExchangeUsage | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<DataExchangeUsage>({
    key: `${KEY_PREFIX}:usage`,
    fetcher: fetchDataExchangeUsage,
    staleTime: STALE,
  });
  return { usage: data, loading: isLoading, error, refresh: refetch };
}

export function useDataExchangeArtifacts(
  params?: DataExchangeArtifactsParams,
): {
  readonly artifacts: DataExchangeArtifact[];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<DataExchangeArtifactsResult>({
    key: `${KEY_PREFIX}:artifacts:${params?.limit ?? 'all'}:${params?.offset ?? 0}`,
    fetcher: () => fetchDataExchangeArtifacts(params),
    staleTime: STALE,
  });

  return {
    artifacts: data?.artifacts ?? [],
    count: data?.count ?? 0,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useDataExchangeExports(): {
  readonly artifacts: DataExchangeArtifact[];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<DataExchangeExportsResult>({
    key: `${KEY_PREFIX}:exports`,
    fetcher: fetchDataExchangeExports,
    staleTime: STALE,
  });
  return { artifacts: data?.artifacts ?? [], count: data?.count ?? 0, loading: isLoading, error };
}

export function useDataExchangeImports(): {
  readonly imports: DataExchangeArtifact[];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<DataExchangeImportsResult>({
    key: `${KEY_PREFIX}:imports`,
    fetcher: fetchDataExchangeImports,
    staleTime: STALE,
  });
  return { imports: data?.imports ?? [], count: data?.count ?? 0, loading: isLoading, error };
}

export function useDataExchangeReports(): {
  readonly artifacts: DataExchangeArtifact[];
  readonly count: number;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<DataExchangeReportsResult>({
    key: `${KEY_PREFIX}:reports`,
    fetcher: fetchDataExchangeReports,
    staleTime: STALE,
  });
  return { artifacts: data?.artifacts ?? [], count: data?.count ?? 0, loading: isLoading, error };
}

/** Resolves the object-store download URL for an artifact (M2 signed transfer).
 * `artifact_id` must be a terminal available/committed artifact — pass `null`
 * (or omit) to keep the query disabled. */
export function useDataExchangeDownloadUrl(
  artifact_id: string | null,
): {
  readonly download: DataExchangeDownloadUrl | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<DataExchangeDownloadUrl>({
    key: `${KEY_PREFIX}:download:${artifact_id ?? 'none'}`,
    fetcher: () => fetchDataExchangeDownloadUrl(artifact_id ?? ''),
    staleTime: STALE,
    enabled: artifact_id !== null,
  });
  return { download: data, loading: isLoading, error, refresh: refetch };
}

// ── Mutations ─────────────────────────────────────────────────────────────────

const invalidate = () => queryCache.invalidatePrefix(KEY_PREFIX);

export function useCreateDataExchangeExport(): {
  readonly create: (input: CreateDataExchangeExportInput) => Promise<DataExchangeExportResult | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<
    CreateDataExchangeExportInput,
    DataExchangeExportResult
  >({
    mutationFn: createDataExchangeExport,
    onSuccess: invalidate,
  });
  const create = useCallback((input: CreateDataExchangeExportInput) => mutate(input), [mutate]);
  return { create, loading: isLoading, error };
}

export function useCreateDataExchangeReport(): {
  readonly create: (input: CreateDataExchangeReportInput) => Promise<DataExchangeReportResult | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<
    CreateDataExchangeReportInput,
    DataExchangeReportResult
  >({
    mutationFn: createDataExchangeReport,
    onSuccess: invalidate,
  });
  const create = useCallback((input: CreateDataExchangeReportInput) => mutate(input), [mutate]);
  return { create, loading: isLoading, error };
}
