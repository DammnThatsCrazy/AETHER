import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

function key(prefix: string, id: string) {
  return `intelligence:${prefix}:${id}`;
}

export function useIntelligenceAlerts(limit = 50) {
  return useQuery({
    key: `intelligence:alerts:${limit}`,
    fetcher: () => api.intelligence.alerts(limit),
    staleTime: STALE,
  });
}

export function useWalletRisk(address: string) {
  return useQuery({
    key: key('wallet-risk', address),
    fetcher: () => api.intelligence.walletRisk(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useWalletProfile(address: string) {
  return useQuery({
    key: key('wallet-profile', address),
    fetcher: () => api.intelligence.walletProfile(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useEntityCluster(entityId: string) {
  return useQuery({
    key: key('entity-cluster', entityId),
    fetcher: () => api.intelligence.entityCluster(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useProtocolAnalytics(protocolId: string) {
  return useQuery({
    key: key('protocol-analytics', protocolId),
    fetcher: () => api.intelligence.protocolAnalytics(protocolId),
    staleTime: STALE,
    enabled: !!protocolId,
  });
}
