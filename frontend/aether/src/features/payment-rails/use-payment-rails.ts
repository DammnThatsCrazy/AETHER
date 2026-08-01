import { useQuery, useMutation, queryCache } from '@aether/ui';
import {
  fetchFundingSessions,
  fetchFundingSession,
  fetchReconciliationRecords,
  fetchPaymentRailHealth,
  fetchProviderStatus,
  syncProviderStatus,
  repairCanonicalBacklog,
} from './api';
import type {
  FundingSessionRecord,
  FundingSessionListParams,
  FundingSessionListResult,
  ReconciliationRecordEntry,
  PaymentRailHealthRecord,
  PaymentRailHealthResult,
  ProviderAdapterStatusRecord,
  CanonicalBacklogRepairOutcome,
} from './api';

const KEY_PREFIX = 'payment-rails';
const STALE = 30_000;

export function useFundingSessions(params?: FundingSessionListParams): {
  readonly sessions: FundingSessionRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const key = [
    KEY_PREFIX,
    'sessions',
    params?.provider ?? 'all',
    params?.status ?? 'all',
    params?.flow_type ?? 'all',
    params?.rail ?? 'all',
    params?.reconciliation_state ?? 'all',
  ].join(':');
  const { data, isLoading, error, refetch } = useQuery<FundingSessionListResult>({
    key,
    fetcher: () => fetchFundingSessions(params),
    staleTime: STALE,
  });

  return {
    sessions: data?.sessions ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useFundingSession(id: string | null): {
  readonly session: FundingSessionRecord | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<FundingSessionRecord>({
    key: `${KEY_PREFIX}:session:${id ?? 'none'}`,
    fetcher: () => fetchFundingSession(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { session: data, loading: isLoading, error, refresh: refetch };
}

export function useReconciliationRecords(): {
  readonly records: ReconciliationRecordEntry[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<ReconciliationRecordEntry[]>({
    key: `${KEY_PREFIX}:reconciliation`,
    fetcher: fetchReconciliationRecords,
    staleTime: STALE,
  });

  return { records: data ?? [], loading: isLoading, error, refresh: refetch };
}

export function usePaymentRailHealth(): {
  readonly providers: PaymentRailHealthRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<PaymentRailHealthResult>({
    key: `${KEY_PREFIX}:health`,
    fetcher: fetchPaymentRailHealth,
    staleTime: STALE,
  });

  return {
    providers: data?.providers ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useProviderStatus(provider: string | null): {
  readonly status: ProviderAdapterStatusRecord | null;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<ProviderAdapterStatusRecord>({
    key: `${KEY_PREFIX}:provider-status:${provider ?? 'none'}`,
    fetcher: () => fetchProviderStatus(provider ?? ''),
    staleTime: STALE,
    enabled: provider !== null,
  });

  return { status: data, loading: isLoading, error };
}

export function useSyncProvider(): {
  readonly sync: (provider: string) => Promise<unknown | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<string, unknown>({
    mutationFn: syncProviderStatus,
    onSuccess: () => queryCache.invalidatePrefix(KEY_PREFIX),
  });

  return { sync: mutate, loading: isLoading, error };
}

export function useRepairCanonicalBacklog(): {
  readonly repair: (limit?: number) => Promise<CanonicalBacklogRepairOutcome | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<number | undefined, CanonicalBacklogRepairOutcome>({
    mutationFn: limit => repairCanonicalBacklog(limit),
    onSuccess: () => queryCache.invalidatePrefix(KEY_PREFIX),
  });

  return { repair: (limit?: number) => mutate(limit), loading: isLoading, error };
}
