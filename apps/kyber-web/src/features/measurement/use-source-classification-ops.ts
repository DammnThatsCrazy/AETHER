import { useCallback, useEffect, useState } from 'react';
import { api } from '@kyber/lib/api';

export interface TrafficIntelligenceFilters {
  tenant?: string;
  platform?: string;
  sdk?: string;
  start?: string;
  end?: string;
}

type Operations = Awaited<ReturnType<typeof api.measurement.sourceClassificationOperations>>;

export interface UseSourceClassificationOpsResult {
  data: Operations | null;
  loading: boolean;
  error: string | null;
  fetchedAt: string | null;
  refresh: () => Promise<void>;
}

/**
 * Traffic-intelligence operations scorecard (spec §15.3). Re-fetches whenever
 * the tenant/platform/sdk/time filters change. Empty-string filters are dropped
 * so they never become `?tenant=` in the query string.
 */
export function useSourceClassificationOps(filters: TrafficIntelligenceFilters): UseSourceClassificationOpsResult {
  const { tenant, platform, sdk, start, end } = filters;
  const [data, setData] = useState<Operations | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: TrafficIntelligenceFilters = {};
      if (tenant) params.tenant = tenant;
      if (platform) params.platform = platform;
      if (sdk) params.sdk = sdk;
      if (start) params.start = start;
      if (end) params.end = end;
      const result = await api.measurement.sourceClassificationOperations(params);
      setData(result ?? null);
      setFetchedAt(new Date().toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenant, platform, sdk, start, end]);

  useEffect(() => {
    void load();
  }, [load]);

  return { data, loading, error, fetchedAt, refresh: load };
}
