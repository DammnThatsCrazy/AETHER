import { useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

const STALE = 60_000;

export function useDerivativesVenues() {
  return useQuery({
    key: 'derivatives:venues',
    fetcher: () => api.derivatives.venues(),
    staleTime: STALE,
  });
}

export function useDerivativesAccounts() {
  return useQuery({
    key: 'derivatives:accounts',
    fetcher: () => api.derivatives.accounts(),
    staleTime: STALE,
  });
}

export function useDerivativesOrders(accountId?: string) {
  return useQuery({
    key: `derivatives:orders:${accountId ?? 'all'}`,
    fetcher: () => api.derivatives.orders(accountId ? { trading_account_id: accountId } : undefined),
    staleTime: 30_000,
  });
}

export function useDerivativesFills(accountId?: string) {
  return useQuery({
    key: `derivatives:fills:${accountId ?? 'all'}`,
    fetcher: () => api.derivatives.fills(accountId ? { trading_account_id: accountId } : undefined),
    staleTime: 30_000,
  });
}

export function useDerivativesPositions(params?: { trading_account_id?: string; status?: string }) {
  return useQuery({
    key: `derivatives:positions:${params?.trading_account_id ?? 'all'}:${params?.status ?? 'all'}`,
    fetcher: () => api.derivatives.positions(params),
    staleTime: 30_000,
  });
}

export function useDerivativesPnl(accountId?: string) {
  return useQuery({
    key: `derivatives:pnl:${accountId ?? 'all'}`,
    fetcher: () => api.derivatives.pnl(accountId ? { trading_account_id: accountId } : undefined),
    staleTime: 30_000,
  });
}

export function useDerivativesVariances() {
  return useQuery({
    key: 'derivatives:variances',
    fetcher: () => api.derivatives.reconciliationVariances(),
    staleTime: 30_000,
  });
}
