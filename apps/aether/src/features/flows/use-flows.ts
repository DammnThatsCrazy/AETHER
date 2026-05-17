/**
 * Flows hooks — wallet links, asset transfers, and asset metadata.
 *
 * "Flows" is the ledger layer that tracks how value moves between entities:
 *   - Wallet links: which blockchain wallets are owned by which entity
 *   - Transfers: asset movements between entities (fiat + on-chain unified)
 *   - Assets: canonical asset definitions (token registry cross-reference)
 *
 * These complement the Web3 wallet profile (which is point-in-time balance
 * data) with the historical movement graph across all value rails.
 */
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

function key(prefix: string, id: string, suffix = '') {
  return `flows:${prefix}:${id}${suffix ? `:${suffix}` : ''}`;
}

/**
 * All blockchain wallets linked to an entity.
 * Covers EOAs, multisigs, smart accounts across all supported chains.
 */
export function useEntityWallets(entityId: string, limit = 50) {
  return useQuery({
    key: key('wallets', entityId, String(limit)),
    fetcher: () => api.flows.wallets.list(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Asset transfer history for an entity — both inbound and outbound,
 * across fiat and on-chain rails. Includes amount, asset, counterparty.
 */
export function useEntityTransfers(entityId: string, limit = 50) {
  return useQuery({
    key: key('transfers', entityId, String(limit)),
    fetcher: () => api.flows.transfers.list(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

/**
 * Canonical asset definition — symbol, decimals, contract address,
 * chain, logo, price. Used to resolve asset IDs in transfer records.
 */
export function useAsset(assetId: string) {
  return useQuery({
    key: key('asset', assetId),
    fetcher: () => api.flows.assets.get(assetId),
    staleTime: 300_000,
    enabled: !!assetId,
  });
}

/**
 * x402 on-chain payment history for an agent — micropayments made
 * or received via the HTTP payment protocol. Covers all x402 transactions
 * where this agent was payer or payee.
 */
export function useAgentPaymentHistory(agentId: string) {
  return useQuery({
    key: key('x402', agentId),
    fetcher: () => api.x402.agentHistory(agentId),
    staleTime: STALE,
    enabled: !!agentId,
  });
}
