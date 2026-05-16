import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useFraudStats() {
  return useQuery({
    key: 'fraud:stats',
    fetcher: () => api.fraud.stats(),
    staleTime: STALE,
  });
}

export function useFraudConfig() {
  return useQuery({
    key: 'fraud:config',
    fetcher: () => api.fraud.getConfig(),
    staleTime: STALE,
  });
}

export function useEvaluateFraud() {
  return useMutation({
    mutationFn: ({ event, context }: { event: Record<string, unknown>; context?: Record<string, unknown> }) =>
      api.fraud.evaluate(event, context),
  });
}

export function useEvaluateFraudBatch() {
  return useMutation({
    mutationFn: (events: unknown[]) => api.fraud.evaluateBatch(events),
  });
}

export function useUpdateFraudConfig() {
  return useMutation({
    mutationFn: (config: Record<string, unknown>) => api.fraud.updateConfig(config),
  });
}
