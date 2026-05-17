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
