import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

// ── Institutions ──────────────────────────────────────────────────────────────

export function useInstitutions(params?: { institution_type?: string; q?: string; limit?: number }) {
  return useQuery({
    key: `crossdomain:institutions:${params?.institution_type ?? ''}:${params?.q ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.crossdomain.institutions.list(params),
    staleTime: STALE,
  });
}

export function useInstitution(id: string) {
  return useQuery({
    key: `crossdomain:institution:${id}`,
    fetcher: () => api.crossdomain.institutions.get(id),
    staleTime: STALE,
    enabled: !!id,
  });
}

// ── Accounts ──────────────────────────────────────────────────────────────────

export function useCrossdomainAccounts(params?: { owner?: string; institution?: string; account_type?: string; limit?: number }) {
  return useQuery({
    key: `crossdomain:accounts:${params?.owner ?? ''}:${params?.institution ?? ''}:${params?.account_type ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.crossdomain.accounts.list(params),
    staleTime: STALE,
  });
}

export function useCrossdomainAccount(id: string) {
  return useQuery({
    key: `crossdomain:account:${id}`,
    fetcher: () => api.crossdomain.accounts.get(id),
    staleTime: STALE,
    enabled: !!id,
  });
}

export function useAccountPositions(accountId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:positions:${accountId}:${limit}`,
    fetcher: () => api.crossdomain.accounts.positions(accountId, limit),
    staleTime: STALE,
    enabled: !!accountId,
  });
}

// ── Instruments ───────────────────────────────────────────────────────────────

export function useInstruments(params?: { instrument_type?: string; issuer?: string; q?: string; limit?: number }) {
  return useQuery({
    key: `crossdomain:instruments:${params?.instrument_type ?? ''}:${params?.issuer ?? ''}:${params?.q ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.crossdomain.instruments.list(params),
    staleTime: STALE,
  });
}

export function useInstrument(id: string) {
  return useQuery({
    key: `crossdomain:instrument:${id}`,
    fetcher: () => api.crossdomain.instruments.get(id),
    staleTime: STALE,
    enabled: !!id,
  });
}

// ── Orders ────────────────────────────────────────────────────────────────────

export function useAccountOrders(accountId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:orders:${accountId}:${limit}`,
    fetcher: () => api.crossdomain.orders.list(accountId, limit),
    staleTime: STALE,
    enabled: !!accountId,
  });
}

// ── Executions ────────────────────────────────────────────────────────────────

export function useOrderExecutions(orderId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:executions:order:${orderId}:${limit}`,
    fetcher: () => api.crossdomain.executions.byOrder(orderId, limit),
    staleTime: STALE,
    enabled: !!orderId,
  });
}

export function useAccountExecutions(accountId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:executions:account:${accountId}:${limit}`,
    fetcher: () => api.crossdomain.executions.byAccount(accountId, limit),
    staleTime: STALE,
    enabled: !!accountId,
  });
}

// ── Balances ──────────────────────────────────────────────────────────────────

export function useAccountBalances(accountId: string) {
  return useQuery({
    key: `crossdomain:balances:${accountId}`,
    fetcher: () => api.crossdomain.balances.latest(accountId),
    staleTime: STALE,
    enabled: !!accountId,
  });
}

// ── Cash Movements ────────────────────────────────────────────────────────────

export function useAccountCashMovements(accountId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:cash-movements:${accountId}:${limit}`,
    fetcher: () => api.crossdomain.cashMovements.list(accountId, limit),
    staleTime: STALE,
    enabled: !!accountId,
  });
}

// ── Compliance ────────────────────────────────────────────────────────────────

export function useEntityComplianceActions(entityId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:compliance:${entityId}:${limit}`,
    fetcher: () => api.crossdomain.compliance.listActions(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

// ── Events ────────────────────────────────────────────────────────────────────

export function useEntityCrossdomainEvents(entityId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:events:entity:${entityId}:${limit}`,
    fetcher: () => api.crossdomain.events.byEntity(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useInstrumentEvents(instrumentId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:events:instrument:${instrumentId}:${limit}`,
    fetcher: () => api.crossdomain.events.byInstrument(instrumentId, limit),
    staleTime: STALE,
    enabled: !!instrumentId,
  });
}

// ── Links ─────────────────────────────────────────────────────────────────────

export function useCrossdomainLinks(entityId: string, limit = 50) {
  return useQuery({
    key: `crossdomain:links:${entityId}:${limit}`,
    fetcher: () => api.crossdomain.links.list(entityId, limit),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useHighConfidenceLinks(params?: { min_confidence?: number; limit?: number }) {
  return useQuery({
    key: `crossdomain:links:high-confidence:${params?.min_confidence ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.crossdomain.links.highConfidence(params),
    staleTime: STALE,
  });
}

// ── Fusion ────────────────────────────────────────────────────────────────────

export function useCrossdomainFusionProfile(entityId: string) {
  return useQuery({
    key: `crossdomain:fusion-profile:${entityId}`,
    fetcher: () => api.crossdomain.fusion.profile(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

export function useCrossdomainFusionExposure(entityId: string) {
  return useQuery({
    key: `crossdomain:fusion-exposure:${entityId}`,
    fetcher: () => api.crossdomain.fusion.exposure(entityId),
    staleTime: STALE,
    enabled: !!entityId,
  });
}

// ── Coverage ──────────────────────────────────────────────────────────────────

export function useCrossdomainCoverage() {
  return useQuery({
    key: 'crossdomain:coverage',
    fetcher: () => api.crossdomain.coverage.status(),
    staleTime: STALE,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useRegisterInstitution() {
  return useMutation({ mutationFn: (institution: Record<string, unknown>) => api.crossdomain.institutions.register(institution) });
}

export function useRegisterAccount() {
  return useMutation({ mutationFn: (account: Record<string, unknown>) => api.crossdomain.accounts.register(account) });
}

export function useRegisterInstrument() {
  return useMutation({ mutationFn: (instrument: Record<string, unknown>) => api.crossdomain.instruments.register(instrument) });
}

export function useRecordOrder() {
  return useMutation({ mutationFn: (order: Record<string, unknown>) => api.crossdomain.orders.record(order) });
}

export function useRecordExecution() {
  return useMutation({ mutationFn: (execution: Record<string, unknown>) => api.crossdomain.executions.record(execution) });
}

export function useRecordBalance() {
  return useMutation({ mutationFn: (balance: Record<string, unknown>) => api.crossdomain.balances.record(balance) });
}

export function useRecordCashMovement() {
  return useMutation({ mutationFn: (movement: Record<string, unknown>) => api.crossdomain.cashMovements.record(movement) });
}

export function useRecordComplianceAction() {
  return useMutation({ mutationFn: (action: Record<string, unknown>) => api.crossdomain.compliance.recordAction(action) });
}

export function useRecordCrossdomainEvent() {
  return useMutation({ mutationFn: (event: Record<string, unknown>) => api.crossdomain.events.record(event) });
}

export function useCreateCrossdomainLink() {
  return useMutation({ mutationFn: (link: Record<string, unknown>) => api.crossdomain.links.create(link) });
}
