import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useEntityTransfers(entityId: string, limit = 50) {
  return useQuery({
    key: `flows:transfers:${entityId}:${limit}`,
    fetcher: () => api.flows.transfers.list(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useEntityWallets(entityId: string, limit = 50) {
  return useQuery({
    key: `flows:wallets:${entityId}:${limit}`,
    fetcher: () => api.flows.wallets.list(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useFlowAsset(assetId: string) {
  return useQuery({
    key: `flows:asset:${assetId}`,
    fetcher: () => api.flows.assets.get(assetId),
    staleTime: STALE,
    enabled: !!assetId,
  });
}

export function useRecordTransfer() {
  return useMutation({
    mutationFn: (transfer: { from_entity_id: string; to_entity_id: string; asset_id: string; amount: number; [k: string]: unknown }) =>
      api.flows.transfers.record(transfer),
  });
}

export function useLinkWallet() {
  return useMutation({
    mutationFn: (wallet: { owner_entity_id: string; chain: string; address: string }) =>
      api.flows.wallets.link(wallet),
  });
}

export function useRegisterAsset() {
  return useMutation({
    mutationFn: (asset: { asset_type: string; chain: string; symbol: string; [k: string]: unknown }) =>
      api.flows.assets.register(asset),
  });
}
