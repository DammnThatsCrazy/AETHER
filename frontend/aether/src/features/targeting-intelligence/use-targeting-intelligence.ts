import { useCallback, useState } from 'react';
import { useQuery } from '@aether/ui';
import {
  fetchCampaignTargetingIntelligence,
  fetchClusterTargetingImpact,
  fetchJourneyDeltas,
  fetchTargetingExports,
  fetchTargetingHoldouts,
  createTargetingExport,
} from './api';
import type {
  CampaignTargetingSummaryRecord,
  CampaignTargetingSummaryResult,
  ClusterTargetingImpactResponseRecord,
  ClusterTargetingImpactResult,
  CreateTargetingExportParams,
  ExportPackageListResult,
  ExportPackageRecord,
  JourneyDeltaListResult,
  JourneyDeltaRecord,
  TargetingHoldoutListResult,
  TargetingHoldoutRecord,
} from './api';

const KEY_PREFIX = 'targeting-intelligence';
const STALE = 30_000;

export function useCampaignTargetingIntelligence(campaignId: string): {
  readonly summary: CampaignTargetingSummaryRecord | null;
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<CampaignTargetingSummaryResult>({
    key: `${KEY_PREFIX}:campaign:${campaignId}`,
    fetcher: () => fetchCampaignTargetingIntelligence(campaignId),
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

export function useClusterTargetingImpact(clusterId: string): {
  readonly response: ClusterTargetingImpactResponseRecord | null;
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<ClusterTargetingImpactResult>({
    key: `${KEY_PREFIX}:cluster:${clusterId}`,
    fetcher: () => fetchClusterTargetingImpact(clusterId),
    staleTime: STALE,
  });

  return {
    response: data?.response ?? null,
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useCampaignJourneyDeltas(campaignId: string): {
  readonly journeyDeltas: JourneyDeltaRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<JourneyDeltaListResult>({
    key: `${KEY_PREFIX}:journey-deltas:${campaignId}`,
    fetcher: () => fetchJourneyDeltas(campaignId),
    staleTime: STALE,
  });

  return {
    journeyDeltas: data?.journeyDeltas ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useTargetingHoldouts(): {
  readonly holdouts: TargetingHoldoutRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<TargetingHoldoutListResult>({
    key: `${KEY_PREFIX}:holdouts`,
    fetcher: fetchTargetingHoldouts,
    staleTime: STALE,
  });

  return {
    holdouts: data?.holdouts ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useTargetingExports(): {
  readonly exports: ExportPackageRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<ExportPackageListResult>({
    key: `${KEY_PREFIX}:exports`,
    fetcher: fetchTargetingExports,
    staleTime: STALE,
  });

  return {
    exports: data?.exports ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

/**
 * Creates a tenant-exportable implementation package for a targeting
 * suggestion or intent. The package is implemented by the tenant in their
 * external campaign platform — Aether never executes it.
 */
export function useCreateTargetingExport(): {
  readonly create: (params: CreateTargetingExportParams) => Promise<ExportPackageRecord | null>;
  readonly created: ExportPackageRecord | null;
  readonly creating: boolean;
  readonly error: string | null;
  readonly reset: () => void;
} {
  const [created, setCreated] = useState<ExportPackageRecord | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(async (params: CreateTargetingExportParams) => {
    setCreating(true);
    setError(null);
    try {
      const pkg = await createTargetingExport(params);
      setCreated(pkg);
      return pkg;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setCreating(false);
    }
  }, []);

  const reset = useCallback(() => {
    setCreated(null);
    setError(null);
  }, []);

  return { create, created, creating, error, reset };
}
