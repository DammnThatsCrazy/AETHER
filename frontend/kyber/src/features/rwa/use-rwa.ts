import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

export function useRWAAssets(params?: { asset_class?: string; chain?: string; limit?: number }) {
  return useQuery({
    key: `rwa:assets:${params?.asset_class ?? ''}:${params?.chain ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.rwa.assets.list(params),
    staleTime: STALE,
  });
}

export function useRWAAsset(assetId: string) {
  return useQuery({
    key: `rwa:asset:${assetId}`,
    fetcher: () => api.rwa.assets.get(assetId),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRWAHolders(assetId: string, limit = 50) {
  return useQuery({
    key: `rwa:holders:${assetId}:${limit}`,
    fetcher: () => api.rwa.assets.holders(assetId, limit),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRWACashflows(assetId: string, params?: { cashflow_type?: string; limit?: number }) {
  return useQuery({
    key: `rwa:cashflows:${assetId}:${params?.cashflow_type ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.rwa.assets.cashflows(assetId, params),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRWAReserveCredibility(assetId: string) {
  return useQuery({
    key: `rwa:reserve-credibility:${assetId}`,
    fetcher: () => api.rwa.assets.reserveCredibility(assetId),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRWARedemptionPressure(assetId: string) {
  return useQuery({
    key: `rwa:redemption-pressure:${assetId}`,
    fetcher: () => api.rwa.assets.redemptionPressure(assetId),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRWAPolicies(assetId: string) {
  return useQuery({
    key: `rwa:policies:${assetId}`,
    fetcher: () => api.rwa.policies.forAsset(assetId),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRWAExposure(entityId: string, params?: { entity_type?: string; include_inferred?: boolean; include_beneficial?: boolean }) {
  return useQuery({
    key: `rwa:exposure:${entityId}:${params?.entity_type ?? ''}:${params?.include_inferred ?? ''}:${params?.include_beneficial ?? ''}`,
    fetcher: () => api.rwa.exposure(entityId, params),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useCreateRWAAsset() {
  return useMutation({ mutationFn: (asset: Record<string, unknown>) => api.rwa.assets.create(asset) });
}

export function useCreateRWAPolicy() {
  return useMutation({ mutationFn: (policy: Record<string, unknown>) => api.rwa.policies.create(policy) });
}

export function useSimulateRWATransfer() {
  return useMutation({
    mutationFn: (params: { asset_id: string; from_entity: string; to_entity: string; amount: number }) =>
      api.rwa.simulateTransfer(params),
  });
}

export function useRecordRWACashflow() {
  return useMutation({ mutationFn: (cashflow: Record<string, unknown>) => api.rwa.recordCashflow(cashflow) });
}

export function useRegisterRWAHolder() {
  return useMutation({ mutationFn: (holder: Record<string, unknown>) => api.rwa.registerHolder(holder) });
}
