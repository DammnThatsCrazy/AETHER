import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

function key(segment: string, id: string, suffix = '') {
  return `graph:${segment}:${id}${suffix ? `:${suffix}` : ''}`;
}

export function useGraphEntity(entityId: string) {
  return useQuery({
    key: key('entity', entityId),
    fetcher: () => api.graph.entityGraph(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useGraphCluster(entityId: string) {
  return useQuery({
    key: key('cluster', entityId),
    fetcher: () => api.graph.cluster(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useGraphResolutionCluster(userId: string) {
  return useQuery({
    key: key('resolution-cluster', userId),
    fetcher: () => api.graph.resolutionCluster(userId),
    staleTime: STALE,
    enabled: !!userId,
  });
}

export function useGraphLinks(entityId: string, limit = 50) {
  return useQuery({
    key: key('links', entityId, String(limit)),
    fetcher: () => api.graph.links(entityId, { limit }),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useGraphHighConfidenceLinks(minConfidence = 0.8, limit = 50) {
  return useQuery({
    key: `graph:high-confidence-links:${minConfidence}:${limit}`,
    fetcher: () => api.graph.highConfidenceLinks(minConfidence, limit),
    staleTime: STALE,
  });
}

export function useGraphDelegations(params: { grantor?: string; grantee?: string; active?: boolean; limit?: number }) {
  const id = params.grantor ?? params.grantee ?? '';
  return useQuery({
    key: key('delegations', id, `${params.grantor ?? ''}:${params.grantee ?? ''}:${params.active ?? ''}:${params.limit ?? ''}`),
    fetcher: () => api.graph.delegations(params),
    staleTime: STALE,
    enabled: !!(params.grantor || params.grantee),
  });
}

export function useGraphFusionProfile(entityId: string) {
  return useQuery({
    key: key('fusion-profile', entityId),
    fetcher: () => api.graph.fusionProfile(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useGraphFusionExposure(entityId: string) {
  return useQuery({
    key: key('fusion-exposure', entityId),
    fetcher: () => api.graph.fusionExposure(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useGraphWalletProfile(address: string) {
  return useQuery({
    key: key('wallet-profile', address),
    fetcher: () => api.graph.walletProfile(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useGraphWalletRisk(address: string) {
  return useQuery({
    key: key('wallet-risk', address),
    fetcher: () => api.graph.walletRisk(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

export function useGraphX402() {
  return useQuery({
    key: 'graph:x402',
    fetcher: () => api.graph.x402Graph(),
    staleTime: STALE,
  });
}

export function useGraphAgentX402(agentId: string) {
  return useQuery({
    key: key('agent-x402', agentId),
    fetcher: () => api.graph.agentX402(agentId),
    staleTime: STALE,
    enabled: !!agentId,
  });
}

export function useGraphSearchEntities(query: string, type?: string, limit = 50) {
  return useQuery({
    key: `graph:search:${query}:${type ?? ''}:${limit}`,
    fetcher: () => api.graph.searchEntities(query, type, limit),
    staleTime: STALE,
    enabled: query.length > 1,
  });
}

export function useValidateDelegation() {
  return useMutation({
    mutationFn: (params: { grantee_entity_id: string; action: string; resource: string; amount?: number }) =>
      api.graph.validateDelegation(params),
  });
}
