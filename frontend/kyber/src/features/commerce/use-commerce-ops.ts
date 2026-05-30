import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useFeesReport(period?: string) {
  return useQuery({
    key: `commerce:fees-report:${period ?? ''}`,
    fetcher: () => api.commerce.feesReport(period),
    staleTime: STALE,
  });
}

export function useAgentSpend(agentId: string) {
  return useQuery({
    key: `commerce:agent-spend:${agentId}`,
    fetcher: () => api.commerce.agentSpend(agentId),
    staleTime: STALE,
    enabled: !!agentId,
  });
}

export function useRecordPayment() {
  return useMutation({
    mutationFn: (payment: Record<string, unknown>) => api.commerce.recordPayment(payment),
  });
}

export function useRecordHire() {
  return useMutation({
    mutationFn: (hire: Record<string, unknown>) => api.commerce.recordHire(hire),
  });
}
