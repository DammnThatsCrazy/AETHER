import { useQuery } from '@aether/ui';
import {
  fetchAISummary,
  fetchAIInvocations,
  fetchAIWorkflows,
  fetchAIModels,
  fetchAIWasteFindings,
  fetchAIRecommendations,
} from './api';
import type {
  AIEfficiencySummaryRecord,
  AIEfficiencySummaryResult,
  AIExecutionFactRecord,
  AIInvocationListParams,
  AIInvocationListResult,
  AIWorkflowEconomicsRecord,
  AIWorkflowListResult,
  AIModelUsageRecord,
  AIModelListResult,
  AIEfficiencyFindingRecord,
  AIFindingListResult,
  AIRecommendationListResult,
} from './api';

const KEY_PREFIX = 'ai-efficiency';
const STALE = 30_000;

export function useAISummary(): {
  readonly summary: AIEfficiencySummaryRecord | null;
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AIEfficiencySummaryResult>({
    key: `${KEY_PREFIX}:summary`,
    fetcher: fetchAISummary,
    staleTime: STALE,
  });

  return {
    summary: data?.summary ?? null,
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useAIInvocations(params?: AIInvocationListParams): {
  readonly invocations: AIExecutionFactRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const key = [
    KEY_PREFIX,
    'invocations',
    params?.provider ?? 'all',
    params?.model ?? 'all',
    params?.status ?? 'all',
    params?.task_type ?? 'all',
    params?.workflow_run_id ?? 'all',
  ].join(':');
  const { data, isLoading, error, refetch } = useQuery<AIInvocationListResult>({
    key,
    fetcher: () => fetchAIInvocations(params),
    staleTime: STALE,
  });

  return {
    invocations: data?.invocations ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useAIWorkflows(): {
  readonly workflows: AIWorkflowEconomicsRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AIWorkflowListResult>({
    key: `${KEY_PREFIX}:workflows`,
    fetcher: fetchAIWorkflows,
    staleTime: STALE,
  });

  return {
    workflows: data?.workflows ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useAIModels(): {
  readonly models: AIModelUsageRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AIModelListResult>({
    key: `${KEY_PREFIX}:models`,
    fetcher: fetchAIModels,
    staleTime: STALE,
  });

  return {
    models: data?.models ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useAIWasteFindings(): {
  readonly findings: AIEfficiencyFindingRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AIFindingListResult>({
    key: `${KEY_PREFIX}:waste`,
    fetcher: fetchAIWasteFindings,
    staleTime: STALE,
  });

  return {
    findings: data?.findings ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useAIRecommendations(): {
  readonly recommendations: AIEfficiencyFindingRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AIRecommendationListResult>({
    key: `${KEY_PREFIX}:recommendations`,
    fetcher: fetchAIRecommendations,
    staleTime: STALE,
  });

  return {
    recommendations: data?.recommendations ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}
