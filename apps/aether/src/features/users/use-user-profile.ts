import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

function key(userId: string, suffix: string) {
  return `user-profile:${userId}:${suffix}`;
}

export function useUserProfile(userId: string) {
  return useQuery({
    key: key(userId, 'summary'),
    fetcher: () => api.profile.summary(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserFull(userId: string) {
  return useQuery({
    key: key(userId, 'full'),
    fetcher: () => api.profile.full(userId, { timeline_limit: 50 }),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserSessions(userId: string, limit = 20) {
  return useQuery({
    key: key(userId, `sessions:${limit}`),
    fetcher: () => api.profile.sessions(userId, limit),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserDevices(userId: string) {
  return useQuery({
    key: key(userId, 'devices'),
    fetcher: () => api.profile.devices(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserPlatforms(userId: string) {
  return useQuery({
    key: key(userId, 'platforms'),
    fetcher: () => api.profile.platforms(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserJourneys(userId: string) {
  return useQuery({
    key: key(userId, 'journeys'),
    fetcher: () => api.profile.journeys(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserWallets(userId: string) {
  return useQuery({
    key: key(userId, 'wallets'),
    fetcher: () => api.profile.wallets(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserFinancials(userId: string) {
  return useQuery({
    key: key(userId, 'financials'),
    fetcher: () => api.profile.financials(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserRewards(userId: string) {
  return useQuery({
    key: key(userId, 'rewards'),
    fetcher: () => api.profile.rewards(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserIdentifiers(userId: string) {
  return useQuery({
    key: key(userId, 'identifiers'),
    fetcher: () => api.profile.identifiers(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserIntelligence(userId: string) {
  return useQuery({
    key: key(userId, 'intelligence'),
    fetcher: () => api.profile.intelligence(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserRelationships(userId: string) {
  return useQuery({
    key: key(userId, 'relationships'),
    fetcher: () => api.profile.relationships(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserBehavioral(userId: string) {
  return useQuery({
    key: key(userId, 'behavioral'),
    fetcher: () => api.behavioral.entity(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserWhyExplain(userId: string) {
  return useQuery({
    key: key(userId, 'why-explain'),
    fetcher: () => api.expectations.explain(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserAttributionJourney(userId: string) {
  return useQuery({
    key: key(userId, 'attribution-journey'),
    fetcher: () => api.attribution.journey(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserGraph(userId: string) {
  return useQuery({
    key: key(userId, 'graph'),
    fetcher: () => api.graph.entityGraph(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserCluster(userId: string) {
  return useQuery({
    key: key(userId, 'cluster'),
    fetcher: () => api.graph.cluster(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}
