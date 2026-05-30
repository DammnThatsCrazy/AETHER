import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

function key(segment: string, userId: string, suffix = '') {
  return `profile:${segment}:${userId}${suffix ? `:${suffix}` : ''}`;
}

export function useProfileSessions(userId: string, limit = 20) {
  return useQuery({
    key: key('sessions', userId, String(limit)),
    fetcher: () => api.profile.sessions(userId, limit),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileDevices(userId: string) {
  return useQuery({
    key: key('devices', userId),
    fetcher: () => api.profile.devices(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileJourneys(userId: string) {
  return useQuery({
    key: key('journeys', userId),
    fetcher: () => api.profile.journeys(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileWallets(userId: string) {
  return useQuery({
    key: key('wallets', userId),
    fetcher: () => api.profile.wallets(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileFinancials(userId: string) {
  return useQuery({
    key: key('financials', userId),
    fetcher: () => api.profile.financials(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileRelationships(userId: string) {
  return useQuery({
    key: key('relationships', userId),
    fetcher: () => api.profile.relationships(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileIntelligence(userId: string) {
  return useQuery({
    key: key('intelligence', userId),
    fetcher: () => api.profile.intelligence(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileProvenance(userId: string) {
  return useQuery({
    key: key('provenance', userId),
    fetcher: () => api.profile.provenance(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileSummary(userId: string) {
  return useQuery({
    key: key('summary', userId),
    fetcher: () => api.profile.summary(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileIdentifiers(userId: string) {
  return useQuery({
    key: key('identifiers', userId),
    fetcher: () => api.profile.identifiers(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfilePlatforms(userId: string) {
  return useQuery({
    key: key('platforms', userId),
    fetcher: () => api.profile.platforms(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileRewards(userId: string) {
  return useQuery({
    key: key('rewards', userId),
    fetcher: () => api.profile.rewards(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useProfileLake(userId: string, domain: 'identity' | 'market' | 'onchain' | 'social') {
  return useQuery({
    key: key('lake', userId, domain),
    fetcher: () => api.profile.lake(userId, domain),
    staleTime: STALE,
    enabled: !!userId,
  });
}
