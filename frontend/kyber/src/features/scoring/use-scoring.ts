import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

export function useEntityScore(entityId: string, features?: Record<string, unknown>) {
  return useQuery({
    key: `scoring:entity:${entityId}`,
    fetcher: () => api.scoring.entityScore(entityId, features),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useWalletScore(address: string) {
  return useQuery({
    key: `scoring:wallet:${address}`,
    fetcher: () => api.scoring.walletScore(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useScoringFeatures(entityId: string) {
  return useQuery({
    key: `scoring:features:${entityId}`,
    fetcher: () => api.scoring.features(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useScoringBatch() {
  return useMutation({
    mutationFn: (entityIds: string[]) => api.scoring.batch(entityIds),
  });
}
