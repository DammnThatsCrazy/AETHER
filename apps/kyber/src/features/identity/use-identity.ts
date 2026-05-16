import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useIdentityProfile(userId: string) {
  return useQuery({
    key: `identity:profile:${userId}`,
    fetcher: () => api.identity.getProfile(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useIdentityGraphNeighborhood(userId: string) {
  return useQuery({
    key: `identity:graph-neighborhood:${userId}`,
    fetcher: () => api.identity.graphNeighborhood(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useCreateIdentityProfile() {
  return useMutation({
    mutationFn: (profile: Record<string, unknown>) => api.identity.createProfile(profile),
  });
}

export function useUpdateIdentityProfile() {
  return useMutation({
    mutationFn: ({ userId, updates }: { userId: string; updates: Record<string, unknown> }) =>
      api.identity.updateProfile(userId, updates),
  });
}

export function useMergeIdentityProfiles() {
  return useMutation({
    mutationFn: ({ primaryId, secondaryId }: { primaryId: string; secondaryId: string }) =>
      api.identity.mergeProfiles(primaryId, secondaryId),
  });
}
