import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useX402Graph() {
  return useQuery({
    key: 'x402:graph',
    fetcher: () => api.x402.graph(),
    staleTime: STALE,
  });
}

export function useX402AgentHistory(agentId: string) {
  return useQuery({
    key: `x402:agent-history:${agentId}`,
    fetcher: () => api.x402.agentHistory(agentId),
    staleTime: STALE,
    enabled: !!agentId,
  });
}

export function useCaptureX402() {
  return useMutation({
    mutationFn: (transaction: Record<string, unknown>) => api.x402.capture(transaction),
  });
}

export function useSnapshotX402Graph() {
  return useMutation({
    mutationFn: () => api.x402.snapshotGraph(),
  });
}
