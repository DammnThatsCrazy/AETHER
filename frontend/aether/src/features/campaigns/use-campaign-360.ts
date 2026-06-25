import { useEffect, useState, useCallback } from 'react';
import { api } from '@aether-app/lib/api/endpoints';

type AnyRecord = Record<string, unknown>;

interface UseQueryState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

function useQuery<T>(fetcher: () => Promise<T>, deps: unknown[]): UseQueryState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetcher()
      .then(r => { if (active) setData(r as T); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const refetch = useCallback(() => setTick(t => t + 1), []);
  return { data, loading, error, refetch };
}

export function useCampaign360Overview(campaignId: string, params?: { time_start?: string; time_end?: string; attribution_model?: string }) {
  return useQuery<AnyRecord>(
    () => (api.campaigns.overview(campaignId, params) as Promise<AnyRecord>),
    [campaignId, params?.time_start, params?.time_end, params?.attribution_model],
  );
}

export function useCampaign360Population(campaignId: string, params?: { population?: string; time_start?: string; time_end?: string; limit?: number }) {
  return useQuery<AnyRecord>(
    () => (api.campaigns.population(campaignId, params) as Promise<AnyRecord>),
    [campaignId, params?.population, params?.time_start, params?.time_end],
  );
}

export function useCampaign360Clusters(campaignId: string, params?: { attribution_run_id?: string; limit?: number }) {
  return useQuery<AnyRecord>(
    () => (api.campaigns.clusters(campaignId, params) as Promise<AnyRecord>),
    [campaignId, params?.attribution_run_id],
  );
}

export function useCampaign360Conversions(campaignId: string, params?: { after?: string; before?: string; include_unattributed?: boolean; limit?: number }) {
  return useQuery<AnyRecord>(
    () => (api.campaigns.conversions(campaignId, params) as Promise<AnyRecord>),
    [campaignId, params?.after, params?.before, params?.include_unattributed],
  );
}

export function useCampaign360Attribution(campaignId: string, params?: { model?: string; start_date?: string; end_date?: string }) {
  return useQuery<AnyRecord>(
    () => (api.campaigns.attribution(campaignId, params) as Promise<AnyRecord>),
    [campaignId, params?.model, params?.start_date, params?.end_date],
  );
}
