import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useStablecoinAssets(params?: { limit?: number }) {
  return useQuery({
    key: `stablecoins:assets:${params?.limit ?? 50}`,
    fetcher: () => api.stablecoins.assets({ limit: 50, ...params }),
    staleTime: STALE,
  });
}

export function useStablecoinDeployments(assetId?: string) {
  return useQuery({
    key: `stablecoins:deployments:${assetId ?? 'all'}`,
    fetcher: () => api.stablecoins.deployments(assetId ? { canonical_asset_id: assetId } : undefined),
    staleTime: STALE,
  });
}

export function useStablecoinObservations(params?: { canonical_asset_id?: string; observation_kind?: string; limit?: number }) {
  return useQuery({
    key: `stablecoins:observations:${params?.canonical_asset_id ?? 'all'}:${params?.observation_kind ?? 'all'}:${params?.limit ?? 50}`,
    fetcher: () => api.stablecoins.observations({ limit: 50, ...params }),
    staleTime: 30_000,
  });
}

export function useStablecoinValuations(params?: { deployment_id?: string; peg_status?: string }) {
  return useQuery({
    key: `stablecoins:valuations:${params?.deployment_id ?? 'all'}:${params?.peg_status ?? 'all'}`,
    fetcher: () => api.stablecoins.valuations(params),
    staleTime: 30_000,
  });
}

export function useStablecoinFlows(assetId?: string) {
  return useQuery({
    key: `stablecoins:flows:${assetId ?? 'all'}`,
    fetcher: () => api.stablecoins.flows(assetId ? { canonical_asset_id: assetId } : undefined),
    staleTime: STALE,
  });
}
