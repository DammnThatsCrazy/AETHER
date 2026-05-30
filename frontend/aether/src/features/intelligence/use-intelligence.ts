/**
 * Aether intelligence hooks — wallet risk, wallet profile, entity cluster.
 *
 * These work across all entity types and are not user-session-scoped.
 * Use for:
 *   - On-chain wallet risk assessment (mixer exposure, sanctions, exploit involvement)
 *   - Full Web3 wallet profile (balances, transactions, protocol interactions, loyalty)
 *   - Identity cluster — entities probabilistically resolved to the same real-world actor
 *   - Entity-level intelligence (trust score, risk score, anomaly score, ML features)
 */
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 120_000;

function key(prefix: string, id: string, suffix = '') {
  return `intelligence:${prefix}:${id}${suffix ? `:${suffix}` : ''}`;
}

/**
 * Wallet risk assessment — sanctions, mixer exposure, exploit involvement,
 * counterparty graph risk. Works for any EVM/SVM address.
 */
export function useWalletRisk(address: string) {
  return useQuery({
    key: key('wallet-risk', address),
    fetcher: () => api.intelligence.walletRisk(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

/**
 * Full Web3 wallet profile — token balances across chains, recent on-chain
 * transactions, protocol interactions (DEX/lending/staking/governance),
 * NFT holdings, wallet age, loyalty signals.
 */
export function useWalletProfile(address: string) {
  return useQuery({
    key: key('wallet-profile', address),
    fetcher: () => api.intelligence.walletProfile(address),
    staleTime: STALE,
    enabled: !!address,
  });
}

/**
 * Identity cluster — the set of entities probabilistically resolved to the
 * same real-world actor, with shared tissue (devices, IPs, wallets, campaigns).
 */
export function useEntityCluster(entityId: string) {
  return useQuery({
    key: key('entity-cluster', entityId),
    fetcher: () => api.intelligence.entityCluster(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Entity-level intelligence — trust score, risk score, anomaly score,
 * ML features, risk drivers, and predicted next event.
 */
export function useEntityIntelligence(entityId: string) {
  return useQuery({
    key: key('entity-intelligence', entityId),
    fetcher: () => api.profile.intelligence(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Behavioral "Why" — top anomaly signals with explanations, overall confidence,
 * contributing campaigns, and expectation gaps for any entity.
 */
export function useEntityWhyExplain(entityId: string) {
  return useQuery({
    key: key('entity-why', entityId),
    fetcher: () => api.expectations.explain(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Behavioral signals — filtered by family (intent_residue, wallet_friction,
 * continuity, sequence_scars, source_shadow, identity_deltas).
 */
export function useEntityBehavioralSignals(
  entityId: string,
  params?: { family?: string; limit?: number },
) {
  return useQuery({
    key: key('entity-signals', entityId, `${params?.family ?? ''}:${params?.limit ?? ''}`),
    fetcher: () => api.behavioral.signals(entityId, params),
    staleTime: STALE,
    enabled: !!entityId,
  });
}
