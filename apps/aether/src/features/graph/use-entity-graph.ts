/**
 * Entity graph hooks — typed wrappers for per-entity graph data.
 *
 * These complement use-graph-data.ts (which builds the full tenant graph).
 * Use these when you need graph data scoped to a single entity:
 *   - Entity's direct graph neighbourhood (all linked nodes/edges)
 *   - Identity cluster (probabilistic cross-entity resolution)
 *   - Delegation chain (grantor ↔ grantee H→A/A→A records)
 *   - Identity links (H2H same-person, shares_device, shares_wallet)
 *   - Relationship edges + summary (typed H2H/H2A/A2H/A2A edges)
 *   - Cross-domain fusion profile (Web2 + Web3 + institutional unified view)
 */
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

function key(prefix: string, id: string, suffix = '') {
  return `entity-graph:${prefix}:${id}${suffix ? `:${suffix}` : ''}`;
}

/** Entity graph neighbourhood — all linked nodes and edges across H2H/H2A/A2H/A2A. */
export function useEntityGraph(entityId: string) {
  return useQuery({
    key: key('graph', entityId),
    fetcher: () => api.graph.entityGraph(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/** Identity cluster — probabilistically resolved same-actor entities with shared tissue. */
export function useIdentityCluster(entityId: string) {
  return useQuery({
    key: key('cluster', entityId),
    fetcher: () => api.graph.cluster(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Delegation records for an entity — as grantor (delegations granted),
 * as grantee (delegations received), or both. Covers H→A, H→H, A→A chains.
 */
export function useDelegations(params: {
  grantor?: string;
  grantee?: string;
  active?: boolean;
  limit?: number;
}) {
  const id = params.grantor ?? params.grantee ?? '';
  return useQuery({
    key: key('delegations', id, `${params.grantor ?? ''}:${params.grantee ?? ''}:${params.active ?? ''}:${params.limit ?? ''}`),
    fetcher: () => api.graph.delegations(params),
    staleTime: STALE,
    enabled: !!(params.grantor || params.grantee),
  });
}

/**
 * Identity links for a single entity — H2H same-person, shares_device,
 * shares_wallet. Each link has interaction_class, weight, and confidence.
 */
export function useIdentityLinks(entityId: string, limit = 50) {
  return useQuery({
    key: key('links', entityId, String(limit)),
    fetcher: () => api.graph.links(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Typed relationship edges for a user entity — H2H, H2A, A2H, A2A flows.
 * Each edge carries relation_type, weight, confidence, volume_usd.
 * Includes relationship_summary (aggregate breakdown by class/type).
 */
export function useEntityRelationships(entityId: string) {
  return useQuery({
    key: key('relationships', entityId),
    fetcher: () => api.profile.relationships(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Cross-domain fusion profile — unified view of an entity across
 * Web2, Web3, and institutional (TradFi) data sources.
 */
export function useFusionProfile(entityId: string) {
  return useQuery({
    key: key('fusion-profile', entityId),
    fetcher: () => api.graph.fusionProfile(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Cross-domain financial exposure — aggregated portfolio + risk
 * across all domains (fiat, on-chain, institutional).
 */
export function useFusionExposure(entityId: string) {
  return useQuery({
    key: key('fusion-exposure', entityId),
    fetcher: () => api.graph.fusionExposure(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}
