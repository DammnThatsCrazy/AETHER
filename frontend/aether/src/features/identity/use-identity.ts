import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useIdentityProfile(userId: string) {
  return useQuery({
    key: `identity:profile:${userId}`,
    fetcher: () => api.identity.getProfile(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useIdentityGraph(userId: string) {
  return useQuery({
    key: `identity:graph:${userId}`,
    fetcher: () => api.identity.graphNeighborhood(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useIdentityExplanation(profileId: string) {
  return useQuery({
    key: `identity-explanation:${profileId}`,
    fetcher: () => api.identity.explanation(profileId),
    staleTime: STALE,
    enabled: !!profileId,
  });
}

export function useIdentityReviewQueue(tenantId: string, limit?: number) {
  return useQuery({
    key: ['identity-review-queue', tenantId, limit ?? 50],
    fetcher: () => api.identity.reviewQueue(tenantId, limit ?? 50),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useSdkHealth(tenantId: string) {
  return useQuery({
    key: ['sdk-health', tenantId],
    fetcher: () => api.identity.sdkHealth(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useActivationStatus(tenantId: string) {
  return useQuery({
    key: ['activation-status', tenantId],
    fetcher: () => api.identity.activationStatus(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}
