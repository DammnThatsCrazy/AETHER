/**
 * Web3 reference data hooks — chains, protocols, tokens, contracts, domains.
 *
 * These resolve the metadata needed to display wallet and on-chain activity:
 *   - Chain registry: chain name, VM family, RPC URLs, explorer links
 *   - Protocol registry: DEX, lending, staking, bridge, governance protocols
 *   - Token registry: symbol, decimals, logo, price, stablecoin flag
 *   - Contract metadata: ABI classification, protocol mapping, risk flags
 *   - Domain lookup: ENS, Unstoppable Domains, Lens handles → address
 */
import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 300_000; // reference data changes rarely — 5 min stale time

// ── Chains ────────────────────────────────────────────────────────────────────

/** All supported chains. Optionally filter by VM family (evm | svm | move | other). */
export function useChains(params?: { vm_family?: string; limit?: number }) {
  return useQuery({
    key: `web3:chains:${params?.vm_family ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.chains.list(params),
    staleTime: STALE,
  });
}

/** Single chain by chain ID. */
export function useChain(chainId: string) {
  return useQuery({
    key: `web3:chain:${chainId}`,
    fetcher: () => api.web3.chains.get(chainId),
    staleTime: STALE,
    enabled: !!chainId,
  });
}

// ── Protocols ─────────────────────────────────────────────────────────────────

/**
 * Protocol registry — DEX, lending, staking, bridge, nft, governance, yield.
 * Optionally filter by family or chain.
 */
export function useProtocols(params?: { family?: string; chain?: string; q?: string; limit?: number }) {
  return useQuery({
    key: `web3:protocols:${params?.family ?? ''}:${params?.chain ?? ''}:${params?.q ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.protocols.list(params),
    staleTime: STALE,
  });
}

/** Single protocol by ID. */
export function useProtocol(protocolId: string) {
  return useQuery({
    key: `web3:protocol:${protocolId}`,
    fetcher: () => api.web3.protocols.get(protocolId),
    staleTime: STALE,
    enabled: !!protocolId,
  });
}

// ── Tokens ────────────────────────────────────────────────────────────────────

/**
 * Token registry — symbol, decimals, logo, current price, stablecoin flag.
 * Filter by chain or stablecoin status.
 */
export function useTokens(params?: { chain_id?: string; stablecoins?: boolean; limit?: number }) {
  return useQuery({
    key: `web3:tokens:${params?.chain_id ?? ''}:${params?.stablecoins ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.tokens.list(params),
    staleTime: STALE,
  });
}

// ── Contracts ─────────────────────────────────────────────────────────────────

/**
 * Contract metadata — ABI classification, protocol mapping, risk flags.
 * Useful for labelling raw contract addresses in transaction history.
 */
export function useContract(chainId: string, address: string) {
  return useQuery({
    key: `web3:contract:${chainId}:${address}`,
    fetcher: () => api.web3.contracts.get(chainId, address),
    staleTime: STALE,
    enabled: !!(chainId && address),
  });
}

// ── Domains ───────────────────────────────────────────────────────────────────

/**
 * Domain → address resolution for ENS, Unstoppable Domains, Lens, etc.
 * Pass a human-readable handle (e.g. "vitalik.eth") and get back the
 * resolved address and domain metadata.
 */
export function useDomainLookup(domain: string) {
  return useQuery({
    key: `web3:domain:${domain}`,
    fetcher: () => api.web3.domains.get(domain),
    staleTime: STALE,
    enabled: !!domain,
  });
}

// ── Onchain contracts ─────────────────────────────────────────────────────────

/**
 * On-chain contract metadata from the chain — ABI, protocol label,
 * risk classification, verification status.
 */
export function useOnchainContract(address: string) {
  return useQuery({
    key: `onchain:contract:${address}`,
    fetcher: () => api.onchain.getContract(address),
    staleTime: STALE,
    enabled: !!address,
  });
}
