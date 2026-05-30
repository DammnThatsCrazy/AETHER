import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

// ── Chains ────────────────────────────────────────────────────────────────────

export function useChains(params?: { vm_family?: string; limit?: number }) {
  return useQuery({
    key: `web3:chains:${params?.vm_family ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.chains.list(params),
    staleTime: STALE,
  });
}

export function useChain(chainId: string) {
  return useQuery({
    key: `web3:chain:${chainId}`,
    fetcher: () => api.web3.chains.get(chainId),
    staleTime: STALE,
    enabled: !!chainId,
  });
}

// ── Protocols ─────────────────────────────────────────────────────────────────

export function useProtocols(params?: { family?: string; chain?: string; q?: string; limit?: number }) {
  return useQuery({
    key: `web3:protocols:${params?.family ?? ''}:${params?.chain ?? ''}:${params?.q ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.protocols.list(params),
    staleTime: STALE,
  });
}

export function useProtocol(protocolId: string) {
  return useQuery({
    key: `web3:protocol:${protocolId}`,
    fetcher: () => api.web3.protocols.get(protocolId),
    staleTime: STALE,
    enabled: !!protocolId,
  });
}

// ── Contracts ─────────────────────────────────────────────────────────────────

export function useContract(chainId: string, address: string) {
  return useQuery({
    key: `web3:contract:${chainId}:${address}`,
    fetcher: () => api.web3.contracts.get(chainId, address),
    staleTime: STALE,
    enabled: !!chainId && !!address,
  });
}

export function useUnclassifiedContracts(params?: { chain_id?: string; limit?: number }) {
  return useQuery({
    key: `web3:contracts:unclassified:${params?.chain_id ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.contracts.unclassified(params),
    staleTime: STALE,
  });
}

// ── Tokens ────────────────────────────────────────────────────────────────────

export function useTokens(params?: { chain_id?: string; stablecoins?: boolean; limit?: number }) {
  return useQuery({
    key: `web3:tokens:${params?.chain_id ?? ''}:${params?.stablecoins ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.tokens.list(params),
    staleTime: STALE,
  });
}

// ── Apps ──────────────────────────────────────────────────────────────────────

export function useWeb3Apps(limit = 50) {
  return useQuery({
    key: `web3:apps:${limit}`,
    fetcher: () => api.web3.apps.list(limit),
    staleTime: STALE,
  });
}

// ── Domains ───────────────────────────────────────────────────────────────────

export function useDomainLookup(domain: string) {
  return useQuery({
    key: `web3:domain:${domain}`,
    fetcher: () => api.web3.domains.get(domain),
    staleTime: STALE,
    enabled: !!domain,
  });
}

// ── Governance ────────────────────────────────────────────────────────────────

export function useGovernanceSpaces(params?: { protocol_id?: string; limit?: number }) {
  return useQuery({
    key: `web3:governance-spaces:${params?.protocol_id ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.web3.governance.listSpaces(params),
    staleTime: STALE,
  });
}

// ── Coverage ──────────────────────────────────────────────────────────────────

export function useWeb3Coverage() {
  return useQuery({
    key: 'web3:coverage',
    fetcher: () => api.web3.coverage.status(),
    staleTime: STALE,
  });
}

export function useWeb3CoverageHealth() {
  return useQuery({
    key: 'web3:coverage:health',
    fetcher: () => api.web3.coverage.health(),
    staleTime: STALE,
  });
}

// ── Migrations ────────────────────────────────────────────────────────────────

export function useProtocolMigrations(protocolId: string, limit = 50) {
  return useQuery({
    key: `web3:migrations:${protocolId}:${limit}`,
    fetcher: () => api.web3.migrations.list(protocolId, limit),
    staleTime: STALE,
    enabled: !!protocolId,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useRegisterChain() {
  return useMutation({ mutationFn: (chain: Record<string, unknown>) => api.web3.chains.register(chain) });
}

export function useRegisterProtocol() {
  return useMutation({ mutationFn: (protocol: Record<string, unknown>) => api.web3.protocols.register(protocol) });
}

export function useRegisterContract() {
  return useMutation({ mutationFn: (contract: Record<string, unknown>) => api.web3.contracts.register(contract) });
}

export function useReclassifyContract() {
  return useMutation({
    mutationFn: ({ chainId, address, body }: { chainId: string; address: string; body: Record<string, unknown> }) =>
      api.web3.contracts.reclassify(chainId, address, body),
  });
}

export function useRegisterToken() {
  return useMutation({ mutationFn: (token: Record<string, unknown>) => api.web3.tokens.register(token) });
}

export function useRegisterApp() {
  return useMutation({ mutationFn: (app: Record<string, unknown>) => api.web3.apps.register(app) });
}

export function useRegisterDomain() {
  return useMutation({ mutationFn: (domain: Record<string, unknown>) => api.web3.domains.register(domain) });
}

export function useRegisterGovernanceSpace() {
  return useMutation({ mutationFn: (space: Record<string, unknown>) => api.web3.governance.registerSpace(space) });
}

export function useClassifyContract() {
  return useMutation({
    mutationFn: ({ chainId, address }: { chainId: string; address: string }) =>
      api.web3.classify.contract(chainId, address),
  });
}

export function useClassifyObservation() {
  return useMutation({
    mutationFn: ({ observation, buildGraph }: { observation: Record<string, unknown>; buildGraph?: boolean }) =>
      api.web3.classify.observation(observation, buildGraph),
  });
}

export function useBatchObservations() {
  return useMutation({
    mutationFn: ({ observations, buildGraph, source, sourceTag }: { observations: unknown[]; buildGraph?: boolean; source?: string; sourceTag?: string }) =>
      api.web3.observations.batch(observations, buildGraph, source, sourceTag),
  });
}

export function useRecordMigration() {
  return useMutation({ mutationFn: (migration: Record<string, unknown>) => api.web3.migrations.record(migration) });
}

export function useDetectMigration() {
  return useMutation({
    mutationFn: ({ protocolId, address, chainId }: { protocolId: string; address: string; chainId: string }) =>
      api.web3.migrations.detect(protocolId, address, chainId),
  });
}
