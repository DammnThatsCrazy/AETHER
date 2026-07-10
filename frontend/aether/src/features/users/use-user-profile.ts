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

export function useUserCardLinkedActivity(userId: string) {
  return useQuery({
    key: key(userId, 'economic:card-linked'),
    fetcher: () => api.profile.cardLinkedActivity(userId),
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

/** Chronological event stream with optional type filter and limit. */
export function useUserTimeline(
  userId: string,
  params?: { limit?: number; event_type?: string },
) {
  return useQuery({
    key: key(userId, `timeline:${params?.event_type ?? ''}:${params?.limit ?? ''}`),
    fetcher: () => api.profile.timeline(userId, params),
    staleTime: STALE,
    enabled: !!userId,
  });
}

/** Data provenance — source attribution for every data point in the profile. */
export function useUserProvenance(userId: string) {
  return useQuery({
    key: key(userId, 'provenance'),
    fetcher: () => api.profile.provenance(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

/** Gold-tier data lake view for a specific domain (identity | market | onchain | social). */
export function useUserLake(
  userId: string,
  domain: 'identity' | 'market' | 'onchain' | 'social',
) {
  return useQuery({
    key: key(userId, `lake:${domain}`),
    fetcher: () => api.profile.lake(userId, domain),
    staleTime: STALE,
    enabled: !!userId,
  });
}

/** Unified social intelligence — all 12 platforms. */
export function useUserSocialIntelligence(userId: string, window = '30d') {
  return useQuery({
    key: key(userId, `social-intelligence:${window}`),
    fetcher: () => api.social.intelligence(userId, window),
    staleTime: STALE,
    enabled: !!userId,
  });
}

/** Pending recommendation cards requiring analyst approval. */
export function useUserRecommendations(userId: string) {
  return useQuery({
    key: key(userId, 'recommendations'),
    fetcher: () => api.recommendations.forUser(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useUserTier(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `tier:${window}`), fetcher: () => api.profile.tier(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserAssetComposition(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `asset-composition:${window}`), fetcher: () => api.profile.assetComposition(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserPnl(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `pnl:${window}`), fetcher: () => api.profile.pnl(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserTradingProfile(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `trading-profile:${window}`), fetcher: () => api.profile.tradingProfile(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserLocationHistory(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `location-history:${window}`), fetcher: () => api.profile.locationHistory(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserTemporalHeatmap(userId: string, window = '90d') {
  return useQuery({ key: key(userId, `temporal-heatmap:${window}`), fetcher: () => api.profile.temporalHeatmap(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserJourneyEconomics(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `journey-economics:${window}`), fetcher: () => api.profile.journeyEconomics(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserDevicePerformance(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `device-performance:${window}`), fetcher: () => api.profile.devicePerformance(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserFunnel(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `funnel:${window}`), fetcher: () => api.profile.funnel(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserTimeToConvert(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `time-to-convert:${window}`), fetcher: () => api.profile.timeToConvert(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserWeb2Profile(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `web2:${window}`), fetcher: () => api.profile.web2Profile(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserProtocolMetrics(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `protocol-metrics:${window}`), fetcher: () => api.profile.protocolMetrics(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserGovernanceActivity(userId: string, window = '30d') {
  return useQuery({ key: key(userId, `governance-activity:${window}`), fetcher: () => api.profile.governanceActivity(userId, window), staleTime: STALE, enabled: !!userId });
}

export function useUserQuality(userId: string) {
  return useQuery({ key: key(userId, 'quality'), fetcher: () => api.profile.quality(userId), staleTime: STALE, enabled: !!userId });
}

export function useUserDataFreshness(userId: string) {
  return useQuery({ key: key(userId, 'data-freshness'), fetcher: () => api.profile.dataFreshness(userId), staleTime: STALE, enabled: !!userId });
}
